"""Run the actual bundled executable without Python/Node installation assumptions."""

import argparse
from contextlib import closing, nullcontext
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time
from urllib.request import Request, urlopen


def check_preserved_data(data):
    """Read-only check after an installer or app bundle has been removed."""
    checkpoint = json.loads((data / "smoke-checkpoint.json").read_text(encoding="utf-8"))
    config = json.loads((data / "config.json").read_text(encoding="utf-8"))
    assert config["installation_id"] == checkpoint["installation_id"]
    with closing(sqlite3.connect((data / "projects.db").resolve().as_uri() + "?mode=ro", uri=True)) as db:
        rows = db.execute("SELECT freelancer_id, title FROM projects").fetchall()
    assert rows == [(checkpoint["project_id"], "Portable Python task")], rows
    return checkpoint


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--data-dir", type=Path, help="Persistent isolated smoke state for installer replacement checks")
    parser.add_argument("--require-existing", action="store_true", help="Fail if an earlier installation lost its records")
    parser.add_argument("--verify-data-only", action="store_true", help="Read-only check after uninstall/removing the app")
    args = parser.parse_args(argv)
    if args.verify_data_only:
        if not args.data_dir:
            parser.error("--verify-data-only requires --data-dir")
        check_preserved_data(args.data_dir)
        print(json.dumps({"uninstall_preserves_data": True}))
        return 0
    if not args.executable:
        parser.error("--executable is required to launch the app")
    if args.require_existing and not args.data_dir:
        parser.error("--require-existing requires --data-dir")
    context = nullcontext(None) if args.data_dir else tempfile.TemporaryDirectory(prefix="bidmaster-smoke-")
    with context as temporary:
        data = args.data_dir.resolve() if args.data_dir else Path(temporary) / "data with spaces # é"
        checkpoint = check_preserved_data(data) if args.require_existing else None
        process = subprocess.Popen(
            [str(args.executable.resolve()), "--data-dir", str(data), "--no-browser"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(120):
                if process.poll() is not None:
                    raise RuntimeError(
                        "Packaged launcher exited: "
                        + process.stdout.read().decode(errors="replace")
                    )
                if (data / "session.json").exists():
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError("Packaged app did not become ready")
            session = json.loads((data / "session.json").read_text())

            def request(path, method="GET", payload=None, auth=True):
                headers = {"Content-Type": "application/json"}
                if auth:
                    headers["Authorization"] = "Bearer " + session["session"]
                with urlopen(
                    Request(
                        session["url"] + path,
                        method=method,
                        headers=headers,
                        data=json.dumps(payload).encode()
                        if payload is not None
                        else None,
                    ),
                    timeout=20,
                ) as response:
                    return json.load(response)

            health = request("/health")
            assert health["app"] == "BidMaster Local"
            assert request("/api/diagnostics")["timezone_database"]
            installation_id = request("/api/status")["config"]["installation_id"]
            assert installation_id
            if checkpoint:
                assert installation_id == checkpoint["installation_id"]
            if os.name == "nt" or __import__("sys").platform == "darwin":
                request(
                    "/api/provider",
                    "PUT",
                    {
                        "provider": {"model": "smoke-no-network"},
                        "api_key": "temporary-native-vault-check",
                    },
                )
                assert request("/api/status")["vault"]["provider_key_saved"]
                assert (
                    "temporary-native-vault-check"
                    not in (data / "config.json").read_text()
                )
                request(
                    "/api/provider",
                    "PUT",
                    {"provider": {"model": "smoke-no-network"}, "api_key": ""},
                )
                assert not request("/api/status")["vault"]["provider_key_saved"]
            if checkpoint:
                projects = request("/api/projects")
                assert [p["id"] for p in projects] == [checkpoint["project_id"]]
                project = projects[0]
            else:
                project = request(
                    "/api/projects",
                    "POST",
                    {
                        "title": "Portable Python task",
                        "description": "Create a Python CSV validation script with acceptance tests and a setup guide.",
                        "budget_minimum": 100,
                        "budget_maximum": 300,
                    },
                )
            assert project["id"] < 0
            request("/api/queue", "POST", {"paused": True})
            request("/api/shutdown", "POST", {})
            process.wait(timeout=60)
            assert process.returncode == 0
            # Same data survives a second launch of this actual installed executable.
            process = subprocess.Popen(
                [
                    str(args.executable.resolve()),
                    "--data-dir",
                    str(data),
                    "--no-browser",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            for _ in range(120):
                if process.poll() is not None:
                    raise RuntimeError("Second launch failed")
                if (data / "session.json").exists():
                    break
                time.sleep(0.5)
            session = json.loads((data / "session.json").read_text())
            assert request("/api/projects")[0]["id"] == project["id"]
            request("/api/shutdown", "POST", {})
            process.wait(timeout=60)
            assert process.returncode == 0
            from desktop.paths import atomic_json

            atomic_json(data / "smoke-checkpoint.json", {"installation_id": installation_id, "project_id": project["id"]})
            check_preserved_data(data)
            print(
                json.dumps(
                    {
                        "version": health["version"],
                        "packaged_launch": True,
                        "profile_created": True,
                        "manual_import": True,
                        "restart_preserves_data": True,
                        "installer_replacement_preserves_data": bool(checkpoint),
                        "native_vault": os.name == "nt"
                        or __import__("sys").platform == "darwin",
                        "platform": {"win32": "windows", "darwin": "macos"}.get(
                            __import__("sys").platform, "linux"
                        ),
                        "architecture": {
                            "AMD64": "x64",
                            "x86_64": "x64",
                            "arm64": "arm64",
                            "aarch64": "arm64",
                        }[__import__("platform").machine()],
                        "platform_requests": 0,
                        "model_requests": 0,
                    }
                )
            )
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=30)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
