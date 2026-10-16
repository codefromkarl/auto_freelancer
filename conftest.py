"""Isolated local tests: dummy credentials, temporary state, no real HTTP calls."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

_runtime = Path(__file__).resolve().parent / ".runtime"
_runtime.mkdir(exist_ok=True)
_state = TemporaryDirectory(prefix="tests-", dir=_runtime)
os.environ.update(
    BID_SUBMISSION_ENABLED='false', BID_MAX_DAILY_ATTEMPTS='1', BID_APPROVAL_MODE='qq',
    BID_MAX_DAILY_SCORED_PROJECTS='20', BID_MIN_AUTO_SCORE='7',
    BID_MIN_NET_HOURLY_USD='15',
    BID_AUTO_REQUIRE_VERIFIED_CLIENT_PAYMENT='true',
    FREELANCER_OAUTH_TOKEN="test-token", FREELANCER_USER_ID="999",
    PYTHON_API_KEY="test-api-key",
    DATABASE_PATH=str(Path(_state.name) / "test.db"),
    LOG_FILE=str(Path(_state.name) / "test.log"),
    OPENAI_API_KEY="test-key", OPENAI_ENABLED="false", ZHIPU_ENABLED="false",
    ANTHROPIC_ENABLED="false", DEEPSEEK_ENABLED="false", LLM_API_KEY="test-key",
    QQ_BOT_APP_ID="test-app", QQ_BOT_APP_SECRET="test-qq-secret",
    QQ_BOT_TARGET_TYPE="c2c", QQ_BOT_TARGET_ID="test-user",
    QQ_BOT_APPROVER_OPENIDS="test-user", QQ_BOT_STATE_PATH=str(Path(_state.name) / "qqbot.db"),
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
    try:
        import httpx2
        monkeypatch.setattr(httpx2.AsyncClient, "send", blocked_async)
    except ImportError:
        pass
    monkeypatch.setattr(aiohttp.ClientSession, "_request", blocked_async)
