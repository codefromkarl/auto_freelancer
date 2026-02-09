"""
Shared utilities for manual pipeline scripts.
"""
from __future__ import annotations

import fcntl
import logging
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Generator, Mapping, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON_SERVICE_ROOT = REPO_ROOT / "python_service"

if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


DEFAULT_ENV_FILE = REPO_ROOT / ".env"
FALLBACK_ENV_FILE = PYTHON_SERVICE_ROOT / ".env"
DEFAULT_LOCK_FILE = REPO_ROOT / "scripts" / "manual_pipeline" / ".pipeline.lock"
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_BIDDABLE_STATUSES = ("open", "active", "open_for_bidding")


EXIT_SUCCESS = 0
EXIT_VALIDATION_ERROR = 1
EXIT_API_ERROR = 2
EXIT_DB_ERROR = 3
EXIT_LOCK_ERROR = 4


def resolve_env_file(repo_root: Path = REPO_ROOT) -> Path:
    root_env = repo_root / ".env"
    service_env = repo_root / "python_service" / ".env"

    if root_env.exists():
        return root_env
    if service_env.exists():
        return service_env
    raise FileNotFoundError("No .env file found in repo root or python_service/.env")


def parse_env_lines(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key:
            values[key] = value
    return values


def load_env_file(path: Path) -> dict[str, str]:
    data = parse_env_lines(path.read_text(encoding="utf-8"))
    for key, value in data.items():
        os.environ.setdefault(key, value)
    return data


def load_env(repo_root: Path = REPO_ROOT) -> Path:
    env_file = resolve_env_file(repo_root)
    load_env_file(env_file)
    return env_file


def validate_env(
    env: Mapping[str, str],
    required: list[str],
    validators: Optional[dict[str, Callable[[str], bool]]] = None,
) -> Tuple[bool, list[str], list[str]]:
    missing: list[str] = []
    invalid: list[str] = []
    validators = validators or {}

    for key in required:
        value = env.get(key)
        if value is None or str(value).strip() == "":
            missing.append(key)
            continue
        validator = validators.get(key)
        if validator and not validator(str(value)):
            invalid.append(key)

    ok = not missing and not invalid
    return ok, missing, invalid


def parse_statuses(raw: str, default: Optional[list[str]] = None) -> list[str]:
    """Parse comma-separated statuses and normalize to lowercase."""
    values = [item.strip().lower() for item in (raw or "").split(",") if item.strip()]
    if values:
        return values
    return list(default or DEFAULT_BIDDABLE_STATUSES)


def get_settings():
    load_env()
    from config import settings

    return settings


def setup_logging(name: str, log_file: Optional[str] = None, level: Optional[str] = None) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    resolved_level = level
    if resolved_level is None:
        try:
            settings = get_settings()
            resolved_level = settings.LOG_LEVEL
        except Exception:
            resolved_level = "INFO"

    logger.setLevel(getattr(logging, str(resolved_level).upper(), logging.INFO))
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if log_file:
        log_path = Path(log_file)
        if log_path.parent:
            log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_db_session():
    from database.connection import SessionLocal

    return SessionLocal()


@contextmanager
def get_db_context() -> Generator[object, None, None]:
    session = get_db_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_telegram_proxies() -> Optional[dict[str, str]]:
    """
    Build explicit Telegram proxy settings from env.
    Prioritizes TELEGRAM_PROXY, then falls back to global proxies.
    """
    keys = [
        "TELEGRAM_PROXY",
        "TELEGRAM_HTTPS_PROXY",
        "TELEGRAM_HTTP_PROXY",
        "HTTPS_PROXY",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
    ]
    
    proxy = None
    for key in keys:
        val = os.getenv(key)
        if val and val.strip():
            proxy = val.strip()
            break
            
    if not proxy:
        return None
        
    if "://" not in proxy:
        proxy = f"http://{proxy}"
        
    return {"http": proxy, "https": proxy}


class FileLock:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.fd: Optional[int] = None

    def acquire(self, blocking: bool = False) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o644)
        flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
        try:
            fcntl.flock(self.fd, flags)
            return True
        except BlockingIOError:
            self.release()
            return False

    def release(self) -> None:
        if self.fd is None:
            return
        try:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)
            self.fd = None


@contextmanager
def file_lock(lock_path: Path = DEFAULT_LOCK_FILE, blocking: bool = False) -> Generator[bool, None, None]:
    lock = FileLock(Path(lock_path))
    acquired = lock.acquire(blocking=blocking)
    try:
        yield acquired
    finally:
        if acquired:
            lock.release()
