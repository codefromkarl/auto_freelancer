import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON_SERVICE = REPO_ROOT / "python_service"
sys.path.insert(0, str(PYTHON_SERVICE))

import pytest

from services.llm_scoring_service import LLMScoringService, LLMProviderConfig, LLMProvider
from config import settings


class DummyClient:
    def __init__(self, result):
        self.result = result


@pytest.mark.asyncio
async def test_llm_scoring_ensemble(monkeypatch):
    service = LLMScoringService()
    service.providers = [
        LLMProviderConfig(name="openai", model="m1", api_key="k"),
        LLMProviderConfig(name="openai", model="m2", api_key="k"),
    ]

    class FakeProvider(LLMProvider):
        def __init__(self, score):
            self._score = score

        def get_client(self, api_key=None, base_url=None):
            return DummyClient(self._score)

        async def score(self, client, model, payload, system_prompt):
            return {
                "score": client.result,
                "reason": "r",
                "proposal": "p",
                "provider_model": model,
            }

        async def close(self, client):
            return None

    def _create_provider_client(provider_config):
        provider = FakeProvider(6.0)
        client = provider.get_client()
        return provider, client

    monkeypatch.setattr(service, "_create_provider_client", _create_provider_client)
    settings.LLM_SCORING_MODE = "ensemble"

    payload = {"id": 1, "title": "t"}
    ok, result = await service._score_with_providers(payload)
    assert ok is True
    assert result["score"] == 6.0
