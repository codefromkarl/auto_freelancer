"""Manage only this installation's optional, permission-gated platform worker."""

import os
import json
import time
from desktop.locking import InstanceLock
import subprocess
import sys
from pathlib import Path


class PlatformWorker:
    def __init__(self, store, vault, licenses):
        self.store = store
        self.vault = vault
        self.licenses = licenses
        self.process = None

    def status(self):
        alive = self.process is not None and self.process.poll() is None
        try:
            with InstanceLock(self.store.directory / "platform-worker.lock"):
                pass
            locked = False
        except RuntimeError:
            locked = True
        if locked:
            try:
                record = json.loads(
                    (self.store.directory / "platform-session.json").read_text()
                )
                pid = (
                    record.get("pid")
                    if record.get("installation_id")
                    == self.store.load().installation_id
                    else None
                )
            except (OSError, ValueError):
                pid = None
            return {"running": True, "pid": pid, "recovered": self.process is None}
        return {"running": alive, "pid": self.process.pid if alive else None}

    def start(self, mode):
        if self.status()["running"]:
            raise ValueError("The platform worker is already running.")
        self.licenses.require_platform("platform_read")
        if mode == "automatic":
            self.licenses.require_platform("platform_bid")
        config = self.store.load()
        if not config.freelancer_user_id or not self.vault.get("freelancer_token"):
            raise ValueError("Configure your own platform account ID and token first.")
        if (
            not self.vault.get("model_api_key")
            or not config.provider.model
            or not config.profile.skills
        ):
            raise ValueError("Complete the model and skills setup first.")
        config.platform_mode = mode
        self.store.save(config)
        env = os.environ.copy()
        env["BIDMASTER_LOCAL_MODE"] = "1"
        env["BIDMASTER_WORKER"] = "1"
        env["BIDMASTER_DATA_DIR"] = str(self.store.directory)
        # Do not inherit QQ or business-system integrations from a developer environment.
        for key in list(env):
            if key.startswith(("QQ_BOT_", "GITHUB_", "GITLAB_", "NOTION_", "TRELLO_")):
                env.pop(key, None)
        args = (
            [sys.executable, "--worker"]
            if getattr(sys, "frozen", False)
            else [sys.executable, "-m", "desktop.launcher", "--worker"]
        )
        with open(
            self.store.directory / "platform-worker.log", "ab", buffering=0
        ) as log:
            self.process = subprocess.Popen(
                args,
                cwd=Path(__file__).resolve().parent.parent,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        return self.status()

    def stop(self):
        if self.status()["running"]:
            # The desktop worker translates this stop file into the scheduler's graceful flag.
            (self.store.directory / "stop-platform").touch()
        return {**self.status(), "stopping": self.status()["running"]}

    def close(self):
        self.stop()
        if self.process and self.process.poll() is None:
            self.process.wait()
        while self.status()["running"]:
            time.sleep(0.5)
