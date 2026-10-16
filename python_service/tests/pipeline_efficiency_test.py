import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import logging
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import scheduler
from config import settings
from database.connection import Base
from database.models import Project, WorkflowEvent
from services import llm_scoring_service as llm, project_service, workflow_service as workflow
from services.proposal_service import ProposalService, ProposalConfig, DefaultProposalValidator
from services.scoring_policy import DIMENSIONS, score_is_current


@pytest.fixture
def scope(monkeypatch):
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    @contextmanager
    def context():
        with Session(engine) as db:
            yield db
            db.commit()
    monkeypatch.setattr(scheduler.common, 'get_db_context', context)
    yield context
    engine.dispose()


def make_project(pid=123):
    return Project(freelancer_id=pid, title='Python API integration', type_id=1,
        full_description='Deliver Python requests integration with tests and README',
        status='active', skills='["Python"]', currency_code='USD',
        budget_minimum=100, budget_maximum=500, submitdate=str(int(time.time())),
        owner_info='{"status":{"payment_verified":true}}', bid_stats='{"bid_count":3}')


def service(monkeypatch):
    result = {'dimension_scores': {k: 8 for k in DIMENSIONS},
              'reason': 'Bounded API integration', 'estimated_hours': 10,
              'suggested_bid': 300, 'provider_model': 'fixture',
              'clarification_questions': [], '_tokens': 10, '_usage_known': True}
    obj = llm.LLMScoringService(llm.LLMScoringConfig(
        providers=[llm.LLMProviderConfig(name='openai', api_key='fixture')],
        cache_enabled=False, generate_proposals=False))
    provider = SimpleNamespace(score=AsyncMock(return_value=result), close=AsyncMock())
    monkeypatch.setattr(obj, '_create_provider_client', lambda _: (provider, object()))
    return obj, provider


@pytest.mark.parametrize('update', [
    {'bid_stats': {'bid_count': 80, 'bid_avg': 200}},
    {'submitdate': str(int(time.time()) - 3600)},
    {'owner_info': {'status': {'payment_verified': False}}},
    {'owner_info': {'status': {'payment_verified': None}}},
])
def test_live_changes_recompute_without_model_and_preserve_model_clock(scope, monkeypatch, update):
    obj, provider = service(monkeypatch)
    with scope() as db:
        p = make_project(); db.add(p); db.commit()
        assert asyncio.run(obj.score_projects_concurrent([p], db))[:2] == (1, 0)
        before = json.loads(p.score_metadata)['model_assessment']
        project_service._apply_project_fields(p, update)
        assert not score_is_current(p)
        assert asyncio.run(obj.score_projects_concurrent([p], db))[:2] == (1, 0)
        after = json.loads(p.score_metadata)
        assert after['model_assessment'] == before
        assert score_is_current(p)
        last = db.query(WorkflowEvent).filter_by(stage='score').order_by(WorkflowEvent.id.desc()).first()
        detail = json.loads(last.details)
        assert detail['model_calls'] == 0 and detail['assessment_reused']
        if 'owner_info' in update:
            assert after['dimensions']['risk'] <= 5
        payload = provider.score.call_args.args[2]
        assert 'bid_stats' not in payload and 'age_hours' not in payload
    assert provider.score.await_count == 1


@pytest.mark.parametrize('update', [
    {'description': 'A completely different API deliverable'},
    {'jobs': [{'name': 'Java'}]}, {'budget': {'maximum': 600}},
    {'owner_info': {'status': {'payment_verified': True}, 'reputation': {'rating': 1}}},
])
def test_material_or_reputation_changes_require_real_reassessment(scope, monkeypatch, update):
    obj, provider = service(monkeypatch)
    with scope() as db:
        p = make_project(); db.add(p); db.commit()
        asyncio.run(obj.score_projects_concurrent([p], db))
        project_service._apply_project_fields(p, update)
        asyncio.run(obj.score_projects_concurrent([p], db))
    assert provider.score.await_count == 2


def test_program_refresh_cannot_extend_model_expiry(scope, monkeypatch):
    obj, provider = service(monkeypatch)
    with scope() as db:
        p = make_project(); db.add(p); db.commit()
        asyncio.run(obj.score_projects_concurrent([p], db))
        metadata = json.loads(p.score_metadata)
        metadata['model_assessment']['evaluated_at'] = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
        p.score_metadata = json.dumps(metadata)
        p.scored_at = workflow.now()
        assert not score_is_current(p)
        asyncio.run(obj.score_projects_concurrent([p], db))
        assert score_is_current(p)
    assert provider.score.await_count == 2


def test_custom_prompt_and_model_policy_changes_do_not_reuse(scope, monkeypatch):
    obj, provider = service(monkeypatch)
    with scope() as db:
        p = make_project(); db.add(p); db.commit()
        asyncio.run(obj.score_projects_concurrent([p], db))
        asyncio.run(obj.score_projects_concurrent([p], db, system_prompt='New domain-specific evaluator'))
        monkeypatch.setattr(settings, 'BID_MIN_NET_HOURLY_USD', 20)
        asyncio.run(obj.score_projects_concurrent([p], db, system_prompt='New domain-specific evaluator'))
        obj.providers[0].model = 'a-different-model'
        asyncio.run(obj.score_projects_concurrent([p], db, system_prompt='New domain-specific evaluator'))
    assert provider.score.await_count == 4


def test_reused_assessment_does_not_clear_existing_preparation_block(scope, monkeypatch):
    obj, provider = service(monkeypatch)
    with scope() as db:
        p = make_project(); db.add(p); db.commit()
        asyncio.run(obj.score_projects_concurrent([p], db))
        metadata = json.loads(p.score_metadata); metadata['candidate_blocked'] = 'quality_failed'
        p.score_metadata = json.dumps(metadata)
        project_service._apply_project_fields(p, {'bid_stats': {'bid_count': 7}})
        asyncio.run(obj.score_projects_concurrent([p], db))
        assert json.loads(p.score_metadata)['candidate_blocked'] == 'quality_failed'
        assert workflow.refresh_readiness(db, p, 6).state == 'deferred'
    assert provider.score.await_count == 1


def test_gate_precedes_limit_and_does_not_reject_feasible_capped_quote(scope, monkeypatch):
    monkeypatch.setattr(settings, 'BID_APPROVAL_MODE', 'automatic')
    monkeypatch.setattr(settings, 'BID_MIN_NET_HOURLY_USD', 10)
    monkeypatch.setattr(settings, 'BID_MIN_AUTO_SCORE', 6)
    monkeypatch.setattr(settings, 'BID_AUTO_REQUIRE_VERIFIED_CLIENT_PAYMENT', False)
    obj, _ = service(monkeypatch)
    with scope() as db:
        bad, good = make_project(123), make_project(124)
        good.owner_info = None
        db.add_all([bad, good]); db.commit()
        asyncio.run(obj.score_projects_concurrent([bad, good], db))
        metadata = json.loads(bad.score_metadata); metadata['model_dimensions']['tech'] = 6
        bad.score_metadata = json.dumps(metadata)
        # Total score may be high, but tech must still pass before the limit.
        bad.ai_score = metadata['total'] = 9; bad.score_metadata = json.dumps(metadata)
    candidates = scheduler.select_bid_candidates(3, ['active'], 6, 1, True)
    assert [c['freelancer_id'] for c in candidates] == [124]
    with scope() as db:
        assert db.query(Project).filter_by(freelancer_id=124).one().suggested_bid == 300
        assert db.query(workflow.CandidateWorkflow).filter_by(project_freelancer_id=123).one().state == 'deferred'


def test_automatic_delivery_missing_issues_enter_existing_bounded_revision(monkeypatch):
    monkeypatch.setattr(settings, 'BID_APPROVAL_MODE', 'automatic')
    first = ('The Python requests integration will implement the requested API and document setup. '
             'The delivery plan uses Python requests with clear logging and a README. '
             'I will keep the implementation modular and handle API errors consistently. '
             'I will document configuration for repeatable local setup. Which endpoint should the integration use?')
    second = first + ' I will test acceptance using sample responses after repository access and credentials are supplied.'
    client = SimpleNamespace(generate_proposal=AsyncMock(side_effect=[first, second]))
    obj = ProposalService(llm_client=client, config=ProposalConfig(max_retries=2))
    p = make_project()
    result = asyncio.run(obj.generate_proposal(p, {'suggested_bid': 300, 'period': 3},
        competition_context={'status': 'missing', 'currency': 'USD', 'price': {}, 'examples': [],
                             '_corpus': [], 'feature_mentions': {}, 'digest': 'fixture'}))
    assert result['success'] and result['attempts'] == 2
    first_prompt = client.generate_proposal.call_args_list[0].kwargs['user_prompt']
    assert 'requests stack' in first_prompt and 'Requirement checklist' in first_prompt
    revised = client.generate_proposal.call_args_list[1].kwargs['system_prompt']
    assert '验收方案' in revised and '范围/访问前提' in revised
    assert DefaultProposalValidator()._count_anchor_hits('use requests with retry handling', ['requests stack']) == 1


def test_outcome_sync_failure_does_not_reclassify_submission(scope, monkeypatch):
    async def completed(*_args, **_kwargs):
        return {'bids_submitted': 1, 'bids_failed': 0}
    from services import bid_outcome_service
    monkeypatch.setattr(scheduler, '_run_cycle', completed)
    monkeypatch.setattr(bid_outcome_service, 'sync_bid_outcomes', AsyncMock(side_effect=RuntimeError('read failed')))
    summary = asyncio.run(scheduler.run_cycle(logger=logging.getLogger('fixture'), outcome_sync_enabled=True))
    assert summary['bids_submitted'] == 1 and summary['bids_failed'] == 0
    assert summary['bid_outcomes']['error_type'] == 'RuntimeError'


def test_single_entry_point_preserves_preparation_block_on_reuse(scope, monkeypatch):
    obj, provider = service(monkeypatch)
    with scope() as db:
        p = make_project(); db.add(p); db.commit()
        asyncio.run(obj.score_projects_concurrent([p], db))
        metadata = json.loads(p.score_metadata); metadata['candidate_blocked'] = 'quality_failed'
        p.score_metadata = json.dumps(metadata)
        updated = asyncio.run(obj.score_single_project(p, db=db))
        assert updated['metadata']['candidate_blocked'] == 'quality_failed'
        assert updated['metadata']['model_assessment'] == metadata['model_assessment']
    assert provider.score.await_count == 1
