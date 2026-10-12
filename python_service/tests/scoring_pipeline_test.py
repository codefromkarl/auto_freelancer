import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database.connection import Base
from database.models import Project
from services import llm_scoring_service as scoring


def test_zero_retries_really_means_one_attempt(monkeypatch):
    service = scoring.LLMScoringService(scoring.LLMScoringConfig(
        providers=[scoring.LLMProviderConfig(name='openai', api_key='dummy', max_retries=2)],
        cache_enabled=False, generate_proposals=False))
    monkeypatch.setattr(service, 'fetch_system_prompt', lambda *_: None)
    monkeypatch.setattr(service, '_prepare_project_payload', lambda _: {'id': 123})
    monkeypatch.setattr(service, '_create_provider_client', lambda _: (SimpleNamespace(close=AsyncMock()), object()))
    attempt = AsyncMock(return_value=(False, None))
    monkeypatch.setattr(service, '_score_with_providers', attempt)
    result = asyncio.run(service.score_projects_concurrent([SimpleNamespace(freelancer_id=123)], object(), max_retries=0))
    assert attempt.await_count == 1
    assert result[:2] == (0, 1)


def test_scoring_payload_uses_complete_description_and_unknown_age():
    service = scoring.LLMScoringService(scoring.LLMScoringConfig(cache_enabled=False))
    project = Project(freelancer_id=123, title='Python API', description='Short preview',
                      full_description='Complete requirements and acceptance criteria', type_id=1,
                      currency_code='USD', budget_minimum=100, budget_maximum=500)
    payload = service._prepare_project_payload(project)
    assert payload['description'] == project.full_description
    assert payload['age_hours'] is None
    assert payload['owner_info'] is None


def test_scored_usd_quote_is_converted_before_native_currency_proposal(monkeypatch):
    service = scoring.LLMScoringService(scoring.LLMScoringConfig(
        providers=[scoring.LLMProviderConfig(name='openai', api_key='dummy')], cache_enabled=False, generate_proposals=True))
    monkeypatch.setattr(service, '_create_provider_client', lambda _: (SimpleNamespace(close=AsyncMock()), object()))
    monkeypatch.setattr(service, '_score_with_providers', AsyncMock(return_value=(True, {
        'score': 8, 'dimension_scores': {k: 9 for k in scoring.DIMENSIONS}, 'reason': 'Clear scope', 'suggested_bid': 100, 'estimated_hours': 5, 'hourly_rate': 30,
    })))
    monkeypatch.setattr(scoring, 'get_currency_converter', lambda: SimpleNamespace(get_rate_sync=lambda _: 0.01))
    import services.proposal_service as proposals
    generate = AsyncMock(return_value={'success': False})
    monkeypatch.setattr(proposals, 'get_proposal_service', lambda: SimpleNamespace(generate_proposal=generate))
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(freelancer_id=123, title='Python API', description='A complete Python API implementation with acceptance tests',
                          currency_code='INR', budget_minimum=10000, budget_maximum=50000, type_id=1,
                          bid_stats='{"bid_count": 1}', owner_info='{"payment_verified": true}')
        db.add(project)
        db.commit()
        result = asyncio.run(service.score_projects_concurrent([project], db, max_retries=0))
        assert result[0] == 1
        assert generate.call_args.kwargs['score_data']['suggested_bid'] == 10000
        assert float(project.suggested_bid) == 100  # Persisted suggestions remain USD.
    engine.dispose()
