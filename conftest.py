"""Isolated local tests: dummy credentials, temporary state, no real HTTP calls."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

_runtime = Path(__file__).resolve().parent / ".runtime"
_runtime.mkdir(exist_ok=True)
_state = TemporaryDirectory(prefix="tests-", dir=_runtime)
os.environ.update(
    FREELANCER_OAUTH_TOKEN="test-token", FREELANCER_USER_ID="999",
    PYTHON_API_KEY="test-api-key",
    DATABASE_PATH=str(Path(_state.name) / "test.db"),
    LOG_FILE=str(Path(_state.name) / "test.log"),
    OPENAI_API_KEY="test-key", OPENAI_ENABLED="false", ZHIPU_ENABLED="false",
    ANTHROPIC_ENABLED="false", DEEPSEEK_ENABLED="false", LLM_API_KEY="test-key",
)


@pytest.fixture(autouse=True)
def no_external_http(monkeypatch):
    import aiohttp
    import httpx
    import requests

    def blocked(*_args, **_kwargs):
        raise AssertionError("Real HTTP calls are disabled in the local test suite")

    async def blocked_async(*_args, **_kwargs):
        blocked()

    monkeypatch.setattr(requests.sessions.Session, "request", blocked)
    monkeypatch.setattr(httpx.AsyncClient, "send", blocked_async)
    monkeypatch.setattr(aiohttp.ClientSession, "_request", blocked_async)
