"""Cross-platform entry point. All customer execution is on their own machine."""

import argparse
import json
import logging
import os
from pathlib import Path
import secrets
import socket
import sys
import threading
import webbrowser

from desktop.paths import data_directory, atomic_json
from desktop.locking import InstanceLock, InstallerGuard


def bootstrap(directory):
    root = Path(__file__).resolve().parent.parent
    if str(root / "python_service") not in sys.path:
        sys.path.insert(0, str(root / "python_service"))
    os.environ["BIDMASTER_LOCAL_MODE"] = "1"
    os.environ["BIDMASTER_DATA_DIR"] = str(directory)
    os.environ["PYTHONUTF8"] = "1"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)


class CredentialFilter(logging.Filter):
    def __init__(self, directory):
        super().__init__()
        self.directory = directory

    def filter(self, record):
        from desktop.redaction import redact

        message = redact(record.getMessage())
        # Do not include exception tracebacks that may contain SDK request data.
        record.msg = message
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        return True


def worker(directory):
    bootstrap(directory)
    from desktop.configuration import ConfigStore
    from desktop.licensing import require_platform_access

    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root / "scripts/manual_pipeline"))
    import scheduler

    scheduler.common.REPO_ROOT = directory
    config = ConfigStore(directory).load()
    require_platform_access(
        directory,
        config.installation_id,
        "platform_bid" if config.platform_mode == "automatic" else "platform_read",
    )
    with InstanceLock(directory / "platform-worker.lock"), InstallerGuard():
        stop = directory / "stop-platform"
        if stop.exists():
            stop.unlink()
        record = directory / "platform-session.json"
        atomic_json(
            record,
            {
                "pid": os.getpid(),
                "installation_id": config.installation_id,
                "mode": config.platform_mode,
            },
        )

        def monitor():
            while not scheduler._shutdown:
                if stop.exists():
                    scheduler._shutdown = True
                    return
                __import__("time").sleep(0.5)

        threading.Thread(target=monitor, daemon=True).start()
        logging.getLogger().addHandler(logging.StreamHandler())
        for handler in logging.getLogger().handlers:
            handler.addFilter(CredentialFilter(directory))
        # Never read developer checkout env files from a packaged local worker.
        scheduler.common.load_env = lambda *a, **kw: None
        keywords = ",".join(config.profile.skills[:10])
        try:
            return scheduler.main(
                [
                    "--interval",
                    "30",
                    "--limit",
                    "20",
                    "--max-bids-per-cycle",
                    "2",
                    "--no-weekly-report",
                    "--keywords",
                    keywords,
                    "--submit" if config.platform_mode == "automatic" else "--dry-run",
                ]
            )
        finally:
            if (
                record.exists()
                and json.loads(record.read_text()).get("pid") == os.getpid()
            ):
                record.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="BidMaster Local — your keys, your device, your workflow."
    )
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--publisher-public-key",
        type=Path,
        help="Source-development only; installed builds have a fixed publisher identity",
    )
    parser.add_argument("--worker", action="store_true")
    parser.add_argument(
        "--version", action="version", version=__import__("desktop").__version__
    )
    args = parser.parse_args(argv)
    if args.publisher_public_key and getattr(sys, "frozen", False):
        parser.error("Installed builds have a fixed publisher public key.")
    directory = (args.data_dir or data_directory()).expanduser().resolve()
    bootstrap(directory)
    if args.worker:
        return worker(directory)
    if not 0 <= args.port <= 65535:
        parser.error("port must be 0–65535")
    import uvicorn
    from desktop.api import create_app

    session = secrets.token_urlsafe(32)
    os.environ["BIDMASTER_SESSION_TOKEN"] = session
    try:
        lock = InstanceLock(directory / "application.lock")
        lock.__enter__()
    except RuntimeError:
        from urllib.parse import urlsplit

        runtime = directory / "session.json"
        if runtime.exists():
            state = json.loads(runtime.read_text())
            url = urlsplit(state.get("url", ""))
            if (
                url.scheme == "http"
                and url.hostname == "127.0.0.1"
                and url.port
                and not url.username
            ):
                if not args.no_browser:
                    webbrowser.open(state["url"] + "/#session=" + state["session"])
                print(
                    "BidMaster is already running. Reopened the existing local session."
                )
                return 0
        raise
    try:
        installer_guard = InstallerGuard()
    except Exception:
        lock.__exit__(None, None, None)
        raise
    try:
        stream = logging.FileHandler(directory / "application.log", encoding="utf-8")
        stream.addFilter(CredentialFilter(directory))
        logging.basicConfig(level=logging.WARNING, handlers=[stream])
        listener = socket.socket()
        listener.bind(("127.0.0.1", args.port))
        listener.listen(128)
        port = listener.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        server = None

        def graceful_exit():
            # Lifespan shutdown waits for the current model call and worker receipts.
            if server:
                server.should_exit = True

        licenses = None
        if args.publisher_public_key:
            from desktop.configuration import ConfigStore
            from desktop.licensing import LicenseManager
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PublicKey,
            )

            public = args.publisher_public_key.read_bytes()
            if not isinstance(
                serialization.load_pem_public_key(public), Ed25519PublicKey
            ):
                raise RuntimeError(
                    "Use the publisher's Ed25519 public key, never a private key."
                )
            licenses = LicenseManager(
                directory, ConfigStore(directory).load().installation_id, public
            )
        app = create_app(
            directory, session, licenses=licenses, on_shutdown=graceful_exit
        )
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                access_log=False,
                log_config=None,
                loop="asyncio",
                timeout_graceful_shutdown=None,
            )
        )
        runtime = directory / "session.json"
        atomic_json(runtime, {"pid": os.getpid(), "url": url, "session": session})
        print(
            "BidMaster Local is listening on "
            + url
            + ". Keep this process running for background tasks.",
            flush=True,
        )
        if not args.no_browser:
            threading.Timer(
                1, lambda: webbrowser.open(url + "/#session=" + session)
            ).start()
        try:
            server.run(sockets=[listener])
        finally:
            listener.close()
            if runtime.exists():
                runtime.unlink()
    finally:
        installer_guard.close()
        lock.__exit__(None, None, None)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
