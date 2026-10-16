"""One durable local queue; pausing never aborts a model call or a platform receipt."""

import asyncio
import json
import threading
import uuid
from sqlalchemy import text
from desktop.database import Job, now
from desktop.engine import engine_context, execute


class JobQueue:
    def __init__(self, database, store, vault, licenses, executor=None):
        self.database = database
        self.store = store
        self.vault = vault
        self.licenses = licenses
        self.executor = executor or execute
        self.stop_event = threading.Event()
        self.thread = None
        self.busy = threading.Event()
        self.guard = threading.RLock()

    def enqueue(self, action, project_id):
        with self.guard:
            if self.thread is not None and not self.thread.is_alive():
                raise ValueError(
                    "The local queue is unavailable. Restart after checking diagnostics."
                )
            self.licenses.require("assistant")
            config = self.store.load()
            if not config.profile.skills or not config.provider.model:
                raise ValueError("Save your skills and exact model ID first.")
            if not self.vault.get("model_api_key"):
                raise ValueError("Save your model API key first.")
            with self.database.session() as db:
                db.execute(text("BEGIN IMMEDIATE"))
                if (
                    db.query(Job)
                    .filter(
                        Job.project_id == project_id,
                        Job.action == action,
                        Job.state.in_(["queued", "running"]),
                    )
                    .first()
                ):
                    raise ValueError(
                        "This project already has the same action queued or running."
                    )
                if db.query(Job).filter(Job.state == "queued").count() >= 20:
                    raise ValueError("The queue is full. Wait or cancel queued tasks.")
                cutoff = now().replace(hour=0, minute=0, second=0, microsecond=0)
                if (
                    db.query(Job).filter(Job.created_at >= cutoff).count()
                    >= config.daily_model_tasks
                ):
                    raise ValueError(
                        "Your daily task limit has been reached. It resets at 00:00 UTC."
                    )
                job = Job(
                    id=uuid.uuid4().hex,
                    project_id=project_id,
                    action=action,
                    state="queued",
                    config_revision=config.revision,
                )
                db.add(job)
                db.flush()
                return job.id

    def start(self):
        self.thread = threading.Thread(
            target=self.loop, daemon=True, name="bidmaster-local-worker"
        )
        self.thread.start()

    def loop(self):
        while not self.stop_event.wait(0.3):
            with self.guard:
                if self.store.load().queue_paused:
                    continue
                with self.database.session() as db:
                    job = (
                        db.query(Job)
                        .filter_by(state="queued")
                        .order_by(Job.created_at, Job.id)
                        .first()
                    )
                    if not job:
                        continue
                    job.state = "running"
                    job.started_at = now()
                    identity = job.id
                    action = job.action
                    project_id = job.project_id
                    revision = job.config_revision
                self.busy.set()
            try:
                self.licenses.require("assistant")
                config = self.store.load()
                if config.revision != revision:
                    raise ValueError(
                        "Configuration changed. Submit the task again to confirm the new settings."
                    )
                with engine_context(config, self.vault, self.store.directory):
                    result = asyncio.run(
                        self.executor(
                            action, project_id, self.database, config, self.vault
                        )
                    )
                state = "succeeded"
                error = None
            except Exception as exc:
                state = "failed"
                result = None
                # SDK errors can contain API keys and project text. Only our validated errors are exposed.
                from desktop.licensing import EntitlementError
                from desktop.secrets import VaultUnavailable

                error = (
                    str(exc)
                    if isinstance(exc, (EntitlementError, VaultUnavailable))
                    else (
                        str(exc)
                        if type(exc) is ValueError
                        and str(exc).startswith(
                            (
                                "The model did not",
                                "Analyze the current",
                                "Resolve the assessment",
                                "Proposal quality",
                                "Configuration changed",
                            )
                        )
                        else "Task failed. Check the provider settings and assessment; no platform submission was made."
                    )
                )
            finally:
                with self.database.session() as db:
                    job = db.get(Job, identity)
                    job.state = state
                    job.error = error
                    job.result = (
                        json.dumps(result, ensure_ascii=False) if result else None
                    )
                    job.finished_at = now()
                self.busy.clear()

    def set_paused(self, paused):
        with self.guard:
            config = self.store.load()
            config.queue_paused = paused
            self.store.save(config)

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join()  # Finish current call; do not kill a partial result.

    def cancel(self, identity):
        with self.guard, self.database.session() as db:
            job = db.get(Job, identity)
            if not job or job.state != "queued":
                raise ValueError(
                    "Only queued tasks can be cancelled. Running tasks finish safely."
                )
            job.state = "cancelled"
            job.finished_at = now()

    def list(self):
        with self.database.session() as db:
            return [
                {
                    "id": j.id,
                    "project_id": j.project_id,
                    "action": j.action,
                    "state": j.state,
                    "created_at": j.created_at.isoformat() + "Z",
                    "error": j.error,
                    "result": json.loads(j.result) if j.result else None,
                }
                for j in db.query(Job).order_by(Job.created_at.desc()).limit(50)
            ]
