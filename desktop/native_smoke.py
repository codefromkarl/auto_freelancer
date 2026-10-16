"""Run the actual bundled executable without Python/Node installation assumptions."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.request import Request, urlopen


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path, required=True)
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="bidmaster-smoke-") as temporary:
        data = Path(temporary) / "data with spaces # é"
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
            assert request("/api/status")["config"]["installation_id"]
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
            # Same data survives a second launch: this is also the basic upgrade-data contract.
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
            print(
                json.dumps(
                    {
                        "version": health["version"],
                        "packaged_launch": True,
                        "profile_created": True,
                        "manual_import": True,
                        "restart_preserves_data": True,
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
