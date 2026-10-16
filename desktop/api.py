"""Authenticated loopback UI/API. No customer credentials go to a publisher server."""

import json
import secrets
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr, ConfigDict, field_validator
from sqlalchemy import func

from desktop.configuration import ConfigStore, Provider, Profile
from desktop.database import Database, Job
from desktop.jobs import JobQueue
from desktop.licensing import LicenseManager, EntitlementError
from desktop.platform import PlatformWorker
from desktop.secrets import SecretStore, VaultUnavailable
from desktop import __version__


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfileInput(Input):
    profile: Profile
    daily_model_tasks: int = Field(default=50, ge=1, le=1000)


class ProviderInput(Input):
    provider: Provider
    api_key: SecretStr | None = None


class AccountInput(Input):
    account_id: int = Field(gt=0)
    token: SecretStr | None = None


class ImportInput(Input):
    title: str = Field(min_length=5, max_length=500)
    description: str = Field(min_length=30, max_length=20000)
    budget_minimum: float = Field(gt=0, le=1000000, allow_inf_nan=False)
    budget_maximum: float = Field(gt=0, le=1000000, allow_inf_nan=False)

    @field_validator("title", "description")
    @classmethod
    def meaningful_text(cls, value, info):
        value = value.strip()
        minimum = 5 if info.field_name == "title" else 30
        if len(value) < minimum:
            raise ValueError(
                f"{info.field_name} needs at least {minimum} non-padding characters"
            )
        return value


class TaskInput(Input):
    action: Literal["analyze", "proposal"]
    confirm_model_costs: Literal[True]


class PauseInput(Input):
    paused: bool


class PermissionDocument(Input):
    document: dict


class PlatformInput(Input):
    mode: Literal["preview", "automatic"]
    confirm_model_costs: Literal[True]


def create_app(
    directory,
    session_token,
    vault=None,
    licenses=None,
    executor=None,
    start_worker=True,
    on_shutdown=None,
):
    store = ConfigStore(directory)
    vault = vault or SecretStore(store.directory)
    config = store.load()
    licenses = licenses or LicenseManager(store.directory, config.installation_id)
    database = Database(store.directory)
    queue = JobQueue(database, store, vault, licenses, executor)
    platform = PlatformWorker(store, vault, licenses)

    @asynccontextmanager
    async def lifespan(app):
        if start_worker:
            queue.start()
        yield
        queue.close()
        platform.close()
        database.engine.dispose()

    app = FastAPI(
        title="BidMaster Local",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.store = store
    app.state.queue = queue
    app.state.database = database
    app.state.licenses = licenses

    @app.middleware("http")
    async def boundary(request, call_next):
        try:
            host = urlsplit("http://" + request.headers.get("host", "")).hostname
        except ValueError:
            return JSONResponse({"detail": "Invalid host."}, 400)
        if host not in {"localhost", "127.0.0.1"}:
            return JSONResponse({"detail": "Loopback access only."}, 400)
        origin = request.headers.get("origin")
        if origin and origin not in {
            f"http://127.0.0.1:{request.url.port}",
            f"http://localhost:{request.url.port}",
        }:
            return JSONResponse({"detail": "This origin is not allowed."}, 403)
        if request.url.path.startswith("/api/"):
            supplied = request.headers.get("authorization", "")
            if not secrets.compare_digest(supplied, "Bearer " + session_token):
                return JSONResponse(
                    {
                        "detail": "Open BidMaster from its launcher to authorize this session."
                    },
                    401,
                )
            try:
                declared = int(request.headers.get("content-length", "0") or 0)
            except ValueError:
                return JSONResponse({"detail": "Invalid content length."}, 400)
            if declared > 65536:
                return JSONResponse({"detail": "Request is too large."}, 413)
            if len(await request.body()) > 65536:
                return JSONResponse({"detail": "Request is too large."}, 413)
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
            }
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(
            {
                "detail": [
                    {"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]}
                    for e in exc.errors()
                ]
            },
            422,
        )

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse({"detail": str(exc)}, 400)

    @app.exception_handler(VaultUnavailable)
    async def vault_error(request, exc):
        return JSONResponse({"detail": str(exc)}, 503)

    @app.exception_handler(EntitlementError)
    async def license_error(request, exc):
        return JSONResponse({"detail": str(exc)}, 403)

    def editable():
        if queue.busy.is_set() or platform.status()["running"]:
            raise HTTPException(
                409,
                "Wait for the current task and stop the platform worker before changing configuration.",
            )

    @app.get("/api/notices")
    def notices():
        path = Path(__file__).parent / "assets" / "THIRD_PARTY_NOTICES.txt"
        if not path.exists():
            raise HTTPException(
                404, "Dependency notices are included in packaged builds."
            )
        return FileResponse(
            path, media_type="text/plain", filename="THIRD_PARTY_NOTICES.txt"
        )

    @app.get("/health")
    def health():
        return {"status": "healthy", "app": "BidMaster Local", "version": __version__}

    @app.get("/api/status")
    def status():
        conf = store.load()
        return {
            "version": __version__,
            "config": conf.model_dump(),
            "vault": vault.status(),
            "license": licenses.status(),
            "queue_busy": queue.busy.is_set(),
            "queue_alive": queue.thread is not None and queue.thread.is_alive(),
            "platform": platform.status(),
            "data_directory": str(store.directory),
            "platform_permission": _platform_status(licenses),
        }

    @app.put("/api/profile")
    def profile(body: ProfileInput):
        with queue.guard:
            editable()
            conf = store.load()
            conf.profile = body.profile
            conf.daily_model_tasks = body.daily_model_tasks
            conf.revision += 1
            store.save(conf)
        return {"saved": True}

    @app.put("/api/provider")
    def provider(body: ProviderInput):
        with queue.guard:
            editable()
            conf = store.load()
            if body.provider.base_url != conf.provider.base_url and not body.api_key:
                raise ValueError(
                    "Re-enter the API key when changing its destination endpoint."
                )
            if body.api_key is not None:
                vault.set("model_api_key", body.api_key.get_secret_value().strip())
            conf.provider = body.provider
            conf.revision += 1
            store.save(conf)
        return {"saved": True}

    @app.delete("/api/provider")
    def disconnect_provider():
        with queue.guard:
            editable()
            vault.set("model_api_key", "")
            conf = store.load()
            conf.revision += 1
            store.save(conf)
        return {"disconnected": True}

    @app.post("/api/provider/test")
    async def test_provider():
        import httpx

        conf = store.load()
        key = vault.get("model_api_key")
        if not key:
            raise ValueError("Save an API key first.")
        # No redirects/proxies; the key goes only to the user-selected HTTPS API origin.
        try:
            async with httpx.AsyncClient(
                trust_env=False, follow_redirects=False, timeout=15
            ) as client:
                result = await client.get(
                    conf.provider.base_url + "/models",
                    headers={"Authorization": "Bearer " + key},
                )
            if result.status_code != 200:
                raise HTTPException(
                    502,
                    f"Provider rejected the models check (HTTP {result.status_code}).",
                )
            data = result.json()
            if not isinstance(data.get("data"), list):
                raise ValueError("Provider returned an unsupported models response.")
            available = any(
                m.get("id") == conf.provider.model
                for m in data["data"]
                if isinstance(m, dict)
            )
            return {
                "connected": True,
                "selected_model_listed": available,
                "note": "This verifies models-list access only; a model generation request can still fail.",
            }
        except httpx.HTTPError:
            raise HTTPException(
                502,
                "Provider could not be reached. Check the endpoint, key and network.",
            ) from None
        except (json.JSONDecodeError, AttributeError):
            raise HTTPException(
                502, "Provider returned an unsupported response."
            ) from None

    @app.put("/api/account")
    def account(body: AccountInput):
        with queue.guard:
            editable()
            conf = store.load()
            from database.models import Bid

            with database.session() as db:
                if db.query(Bid).filter(Bid.bidder_id != body.account_id).first():
                    raise HTTPException(
                        409,
                        "This directory contains another account's submission records. Use a separate local data directory.",
                    )
            if conf.freelancer_user_id != body.account_id and not body.token:
                raise ValueError("Enter the token for the new account.")
            if body.token is not None:
                vault.set("freelancer_token", body.token.get_secret_value().strip())
            conf.freelancer_user_id = body.account_id
            conf.revision += 1
            store.save(conf)
        return {"saved": True}

    @app.delete("/api/account")
    def disconnect_account():
        with queue.guard:
            editable()
            vault.set("freelancer_token", "")
            conf = store.load()
            conf.freelancer_user_id = None
            conf.platform_mode = "preview"
            conf.revision += 1
            store.save(conf)
        return {"disconnected": True, "records_preserved": True}

    @app.post("/api/documents")
    def documents(body: PermissionDocument):
        with queue.guard:
            editable()
            return licenses.install(body.document)

    @app.get("/api/projects")
    def projects():
        from database.models import Project

        with database.session() as db:
            return [
                _project(p)
                for p in db.query(Project)
                .order_by(Project.created_at.desc())
                .limit(100)
            ]

    @app.post("/api/projects")
    def import_project(body: ImportInput):
        if body.budget_maximum < body.budget_minimum:
            raise ValueError("Maximum budget must be at least the minimum.")
        from database.models import Project

        with database.session() as db:
            p = Project(
                freelancer_id=-(secrets.randbelow(2_000_000_000) + 1),
                title=body.title.strip(),
                description=body.description.strip(),
                full_description=body.description.strip(),
                status="active",
                type_id=1,
                currency_code="USD",
                budget_minimum=body.budget_minimum,
                budget_maximum=body.budget_maximum,
                skills="[]",
                submitdate=str(int(time.time())),
            )
            db.add(p)
            db.flush()
            return _project(p)

    @app.put("/api/projects/{project_id}")
    def revise_project(project_id: int, body: ImportInput):
        if body.budget_maximum < body.budget_minimum:
            raise ValueError("Maximum budget must be at least the minimum.")
        if project_id >= 0:
            raise HTTPException(
                400, "Only manually imported briefs can be edited here."
            )
        from database.models import Project
        from services import workflow_service as workflow

        with queue.guard, database.session() as db:
            if (
                db.query(Job)
                .filter(
                    Job.project_id == project_id, Job.state.in_(["queued", "running"])
                )
                .first()
            ):
                raise HTTPException(
                    409, "Finish or cancel this project task before editing its brief."
                )
            project = db.query(Project).filter_by(freelancer_id=project_id).first()
            if not project:
                raise HTTPException(404, "Project not found.")
            project.title = body.title
            project.description = project.full_description = body.description
            project.budget_minimum = body.budget_minimum
            project.budget_maximum = body.budget_maximum
            workflow.invalidate_score(project)
            workflow.ensure(db, project)
            return _project(project)

    @app.post("/api/projects/{project_id}/tasks")
    def task(project_id: int, body: TaskInput):
        from database.models import Project

        with database.session() as db:
            if not db.query(Project).filter_by(freelancer_id=project_id).first():
                raise HTTPException(404, "Project not found.")
        return {"job_id": queue.enqueue(body.action, project_id)}

    @app.get("/api/jobs")
    def jobs():
        return queue.list()

    @app.post("/api/jobs/{identity}/cancel")
    def cancel(identity: str):
        queue.cancel(identity)
        return {"cancelled": True}

    @app.post("/api/queue")
    def pause(body: PauseInput):
        queue.set_paused(body.paused)
        return {"paused": body.paused}

    @app.post("/api/automation/start")
    def start_platform(body: PlatformInput):
        with queue.guard:
            if queue.busy.is_set():
                raise HTTPException(409, "Wait for the local model task to finish.")
            return platform.start(body.mode)

    @app.post("/api/automation/stop")
    def stop_platform():
        return platform.stop()

    @app.get("/api/projects/{project_id}/proposal")
    def export(project_id: int):
        from database.models import Project

        with database.session() as db:
            p = db.query(Project).filter_by(freelancer_id=project_id).first()
            if not p or not p.ai_proposal_draft:
                raise HTTPException(404, "No validated proposal is available.")
            return PlainTextResponse(
                p.ai_proposal_draft,
                headers={
                    "Content-Disposition": 'attachment; filename="bidmaster-proposal.txt"'
                },
            )

    @app.post("/api/updates/verify")
    def verify_update(body: PermissionDocument):
        from desktop.updates import ReleaseManager

        release = ReleaseManager(store.directory, licenses.public_key).verify(
            body.document
        )
        return {
            "version": release["version"],
            "bytes": release["bytes"],
            "platform": release["platform"],
            "architecture": release["architecture"],
        }

    @app.post("/api/updates/download")
    async def download_update(body: PermissionDocument):
        from desktop.updates import ReleaseManager

        return await ReleaseManager(store.directory, licenses.public_key).download(
            body.document
        )

    @app.get("/api/diagnostics")
    def diagnostics():
        with database.session() as db:
            counts = dict(
                db.query(Job.state, func.count(Job.id)).group_by(Job.state).all()
            )
        return {
            "app": "BidMaster Local",
            "version": __version__,
            "jobs": counts,
            "vault_available": vault.status()["available"],
            "license_active": licenses.status()["active"],
            "platform": platform.status(),
            "includes_credentials": False,
            "includes_project_content": False,
        }

    @app.post("/api/backup")
    def backup():
        name = "projects-" + str(int(time.time())) + ".db"
        target = store.directory / "backups"
        target.mkdir(exist_ok=True, mode=0o700)
        database.backup(target / name)
        return {
            "filename": name,
            "note": "Stored in your local data directory. Do not restore an old submission ledger without reconciliation.",
        }

    @app.post("/api/shutdown")
    def shutdown():
        queue.set_paused(True)
        platform.stop()
        if on_shutdown:
            threading.Thread(target=on_shutdown, daemon=True).start()
        return {"stopping": True, "message": "Finishing current work before exit."}

    ui = Path(__file__).parent / "ui"

    @app.get("/")
    def index():
        return FileResponse(ui / "index.html")

    app.mount("/assets", StaticFiles(directory=ui), name="assets")
    return app


def _platform_status(licenses):
    try:
        licenses.require_platform("platform_read")
        return {"available": True}
    except EntitlementError:
        return {
            "available": False,
            "message": "Platform access requires a separate publisher-verified written permission document.",
        }


def _project(p):
    from services.scoring_policy import object_value

    metadata = object_value(p.score_metadata) or {}
    return {
        "id": p.freelancer_id,
        "title": p.title,
        "description": p.full_description or p.description,
        "budget_minimum": float(p.budget_minimum),
        "budget_maximum": float(p.budget_maximum),
        "score": p.ai_score,
        "hours": p.estimated_hours,
        "quote_usd": float(p.suggested_bid) if p.suggested_bid else None,
        "net_hourly": metadata.get("net_hourly_usd"),
        "explanation": metadata.get("model_reason"),
        "questions": metadata.get("clarification_questions", []),
        "recommendation": metadata.get("recommendation"),
        "proposal": p.ai_proposal_draft or "",
    }
