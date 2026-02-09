import sys
import asyncio
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON_SERVICE = REPO_ROOT / "python_service"
sys.path.insert(0, str(PYTHON_SERVICE))

import pytest

from services.llm_scoring_service import LLMScoringService, LLMProviderConfig, LLMProvider
from config import settings, Settings


class DummyClient:
    def __init__(self, result, delay=0):
        self.result = result
        self.delay = delay


class FakeProvider(LLMProvider):
    def __init__(self, score, delay=0):
        self._score = score
        self._delay = delay

    def get_client(self, api_key=None, base_url=None):
        return DummyClient(self._score, self._delay)

    async def score(self, client, model, payload, system_prompt):
        if client.delay > 0:
            await asyncio.sleep(client.delay)
        return {
            "score": client.result,
            "reason": "r",
            "suggested_bid": 100,
            "estimated_hours": 10,
            "hourly_rate": 10.0,
            "provider_model": model,
        }

    async def close(self, client):
        return None


@pytest.mark.asyncio
async def test_llm_scoring_ensemble(monkeypatch):
    service = LLMScoringService()
    # Mock providers
    p1_config = LLMProviderConfig(name="openai", model="m1", api_key="k")
    p2_config = LLMProviderConfig(name="openai", model="m2", api_key="k")
    service.providers = [p1_config, p2_config]

    def _create_provider_client(provider_config):
        if provider_config.model == "m1":
            provider = FakeProvider(6.0)
        else:
            provider = FakeProvider(8.0)
        client = provider.get_client()
        return provider, client

    monkeypatch.setattr(service, "_create_provider_client", _create_provider_client)
    monkeypatch.setattr(settings, "LLM_SCORING_MODE", "ensemble")

    payload = {"id": 1, "title": "t"}
    ok, result = await service._score_with_providers(payload)
    assert ok is True
    # (6.0 + 8.0) / 2 = 7.0
    assert result["score"] == 7.0


@pytest.mark.asyncio
async def test_llm_scoring_race(monkeypatch):
    service = LLMScoringService()
    # Mock providers: m1 is slow, m2 is fast
    p1_config = LLMProviderConfig(name="openai", model="m1", api_key="k")
    p2_config = LLMProviderConfig(name="openai", model="m2", api_key="k")
    service.providers = [p1_config, p2_config]

    def _create_provider_client(provider_config):
        if provider_config.model == "m1":
            provider = FakeProvider(6.0, delay=0.5) # Slow
        else:
            provider = FakeProvider(8.0, delay=0.01) # Fast
        client = provider.get_client()
        return provider, client

    monkeypatch.setattr(service, "_create_provider_client", _create_provider_client)
    monkeypatch.setattr(settings, "LLM_SCORING_MODE", "race")

    payload = {"id": 1, "title": "t"}
    ok, result = await service._score_with_providers(payload)
    assert ok is True
    # Fast one should win
    assert result["score"] == 8.0


@pytest.mark.asyncio


async def test_llm_scoring_single(monkeypatch):


    service = LLMScoringService()


    # Mock providers: two configured, but only one should be called


    p1_config = LLMProviderConfig(name="openai", model="m1", api_key="k")


    p2_config = LLMProviderConfig(name="openai", model="m2", api_key="k")


    service.providers = [p1_config, p2_config]





    call_count = 0





    class CountingProvider(FakeProvider):


        async def score(self, client, model, payload, system_prompt):


            nonlocal call_count


            call_count += 1


            return await super().score(client, model, payload, system_prompt)





    def _create_provider_client(provider_config):


        provider = CountingProvider(7.5)


        client = provider.get_client()


        return provider, client





    monkeypatch.setattr(service, "_create_provider_client", _create_provider_client)


    monkeypatch.setattr(settings, "LLM_SCORING_MODE", "single")





    payload = {"id": 1, "title": "t"}


    ok, result = await service._score_with_providers(payload)


    assert ok is True


    assert result["score"] == 7.5


    assert call_count == 1


def test_settings_anthropic_auth_token_used_as_api_key():
    cfg = Settings(
        _env_file=None,
        FREELANCER_OAUTH_TOKEN="x",
        FREELANCER_USER_ID="1",
        PYTHON_API_KEY="k",
        OPENAI_ENABLED=False,
        ZHIPU_ENABLED=False,
        DEEPSEEK_ENABLED=False,
        ANTHROPIC_ENABLED=True,
        ANTHROPIC_API_KEY="",
        ANTHROPIC_AUTH_TOKEN="cr_test_token_123",
        ANTHROPIC_BASE_URL="https://lldai.online/api",
        ANTHROPIC_MODEL="claude-3-5-sonnet",
    )

    providers = cfg.get_enabled_llm_providers()
    anthropic = next((p for p in providers if p.get("name") == "anthropic"), None)

    assert anthropic is not None
    assert anthropic["api_key"] == "cr_test_token_123"


def test_settings_anthropic_base_url_in_provider_config():
    cfg = Settings(
        _env_file=None,
        FREELANCER_OAUTH_TOKEN="x",
        FREELANCER_USER_ID="1",
        PYTHON_API_KEY="k",
        OPENAI_ENABLED=False,
        ZHIPU_ENABLED=False,
        DEEPSEEK_ENABLED=False,
        ANTHROPIC_ENABLED=True,
        ANTHROPIC_API_KEY="ak_test_123",
        ANTHROPIC_AUTH_TOKEN="",
        ANTHROPIC_BASE_URL="https://lldai.online/api",
        ANTHROPIC_MODEL="claude-3-5-sonnet",
    )

    providers = cfg.get_enabled_llm_providers()
    anthropic = next((p for p in providers if p.get("name") == "anthropic"), None)

    assert anthropic is not None
    assert anthropic["base_url"] == "https://lldai.online/api"


def test_newcomer_profile_boosts_small_projects(monkeypatch):
    service = LLMScoringService()

    class DummyProject:
        freelancer_id = 101
        currency_code = "USD"
        budget_minimum = 120
        budget_maximum = 350
        bid_stats = '{"bid_count": 15}'

    monkeypatch.setattr(settings, "BID_SELECTION_PROFILE", "newcomer")

    adjusted = service._apply_bid_profile_score_adjustment(
        project=DummyProject(),
        score=6.2,
        estimated_hours=12,
        hourly_rate=24.0,
    )
    assert adjusted > 6.2


def test_newcomer_profile_penalizes_large_complex_projects(monkeypatch):
    service = LLMScoringService()

    class DummyProject:
        freelancer_id = 102
        currency_code = "USD"
        budget_minimum = 9000
        budget_maximum = 15000
        bid_stats = '{"bid_count": 60}'

    monkeypatch.setattr(settings, "BID_SELECTION_PROFILE", "newcomer")

    adjusted = service._apply_bid_profile_score_adjustment(
        project=DummyProject(),
        score=7.6,
        estimated_hours=120,
        hourly_rate=95.0,
    )
    assert adjusted < 7.6


@pytest.mark.asyncio
async def test_score_projects_uses_db_prompt_before_default(monkeypatch):
    service = LLMScoringService()
    service.config.default_system_prompt = "DEFAULT_PROMPT"
    service.providers = [LLMProviderConfig(name="openai", model="m1", api_key="k")]
    service._cache = None

    class DummyProject:
        freelancer_id = 301
        title = "Small automation task"
        description = "Task"
        preview_description = "Task"
        budget_minimum = 100
        budget_maximum = 300
        currency_code = "USD"
        skills = None
        bid_stats = '{"bid_count": 8}'
        owner_info = None
        type_id = 1

        def to_dict(self):
            return {
                "id": self.freelancer_id,
                "title": self.title,
                "description": self.description,
                "budget": {"minimum": self.budget_minimum, "maximum": self.budget_maximum},
                "currency_code": self.currency_code,
            }

    class DummyProvider(FakeProvider):
        pass

    monkeypatch.setattr(
        service,
        "fetch_system_prompt",
        lambda db, category="scoring": (
            "You are a scorer. Return strict JSON with fields: "
            "score, reason, suggested_bid, estimated_hours, hourly_rate."
        ),
    )

    def _create_provider_client(provider_config):
        provider = DummyProvider(7.0)
        return provider, provider.get_client()

    monkeypatch.setattr(service, "_create_provider_client", _create_provider_client)

    class FakeScorer:
        def fetch_weights_from_db(self, db):
            return None

        def estimate_project_hours(self, project_dict):
            return 10

    import services.llm_scoring_service as llm_scoring_module
    monkeypatch.setattr(llm_scoring_module, "get_project_scorer", lambda: FakeScorer())

    from services import project_service
    monkeypatch.setattr(project_service, "update_project_ai_analysis", lambda *args, **kwargs: None)

    captured = {"prompt": None}

    async def _fake_score_with_providers(payload, provider_clients=None, system_prompt=None):
        captured["prompt"] = system_prompt
        return True, {
            "score": 7.0,
            "reason": "r",
            "suggested_bid": 120,
            "estimated_hours": 10,
            "hourly_rate": 22.0,
            "provider_model": "m1",
        }

    monkeypatch.setattr(service, "_score_with_providers", _fake_score_with_providers)

    await service.score_projects_concurrent(
        projects=[DummyProject()],
        db=object(),
        batch_size=1,
        max_retries=0,
    )

    assert "suggested_bid" in (captured["prompt"] or "")


@pytest.mark.asyncio
async def test_score_projects_falls_back_to_default_when_db_prompt_invalid(monkeypatch):
    service = LLMScoringService()
    service.config.default_system_prompt = "DEFAULT_PROMPT"
    service.providers = [LLMProviderConfig(name="openai", model="m1", api_key="k")]
    service._cache = None

    class DummyProject:
        freelancer_id = 302
        title = "Small automation task"
        description = "Task"
        preview_description = "Task"
        budget_minimum = 100
        budget_maximum = 300
        currency_code = "USD"
        skills = None
        bid_stats = '{"bid_count": 8}'
        owner_info = None
        type_id = 1

        def to_dict(self):
            return {
                "id": self.freelancer_id,
                "title": self.title,
                "description": self.description,
                "budget": {"minimum": self.budget_minimum, "maximum": self.budget_maximum},
                "currency_code": self.currency_code,
            }

    monkeypatch.setattr(
        service,
        "fetch_system_prompt",
        lambda db, category="scoring": (
            "Analyze the following project description and extract key requirements, skills, and potential risks."
        ),
    )

    class FakeScorer:
        def fetch_weights_from_db(self, db):
            return None

        def estimate_project_hours(self, project_dict):
            return 10

    import services.llm_scoring_service as llm_scoring_module
    monkeypatch.setattr(llm_scoring_module, "get_project_scorer", lambda: FakeScorer())

    from services import project_service
    monkeypatch.setattr(project_service, "update_project_ai_analysis", lambda *args, **kwargs: None)

    captured = {"prompt": None}

    async def _fake_score_with_providers(payload, provider_clients=None, system_prompt=None):
        captured["prompt"] = system_prompt
        return True, {
            "score": 7.0,
            "reason": "r",
            "suggested_bid": 120,
            "estimated_hours": 10,
            "hourly_rate": 22.0,
            "provider_model": "m1",
        }

    monkeypatch.setattr(service, "_score_with_providers", _fake_score_with_providers)
    monkeypatch.setattr(service, "_create_provider_client", lambda cfg: (FakeProvider(7.0), FakeProvider(7.0).get_client()))

    await service.score_projects_concurrent(
        projects=[DummyProject()],
        db=object(),
        batch_size=1,
        max_retries=0,
    )

    assert captured["prompt"] == "DEFAULT_PROMPT"
