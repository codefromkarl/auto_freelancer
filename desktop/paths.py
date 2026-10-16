"""User-owned state, independent of installation and the developer checkout."""

import os
import sys
from pathlib import Path


def data_directory(platform=None, env=None):
    platform = platform or sys.platform
    env = os.environ if env is None else env
    if env.get("BIDMASTER_DATA_DIR"):
        return Path(env["BIDMASTER_DATA_DIR"]).expanduser().resolve()
    home = Path.home()
    if platform == "win32":
        return Path(env.get("LOCALAPPDATA", home / "AppData" / "Local")) / "BidMaster"
    if platform == "darwin":
        return home / "Library" / "Application Support" / "BidMaster"
    return Path(env.get("XDG_DATA_HOME", home / ".local" / "share")) / "bidmaster"


def atomic_json(path, value):
    import json
    import tempfile

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
