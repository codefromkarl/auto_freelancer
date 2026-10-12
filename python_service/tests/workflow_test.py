import asyncio
import json
import logging
import time
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import scheduler
from config import settings
from database.connection import Base, get_db
from database.models import Project, CandidateWorkflow, WorkflowEvent, WorkflowRun, BidSubmission
from main import app
from services import workflow_service as workflow, project_service, approved_bids, llm_scoring_service as llm
from services.scoring_policy import digest, SCORING_VERSION, DIMENSIONS, scoring_inputs, policy_signature
from services.scoring_cache import ScoringCache, CacheConfig


def stamp(project, questions=None):
    project.ai_score, project.suggested_bid, project.estimated_hours, project.hourly_rate = 8, 300, 10, 30
    project.scored_at = workflow.now()
    project.score_metadata = json.dumps({"source": "llm", "version": SCORING_VERSION,
        "input_hash": digest(scoring_inputs(project)), "policy_hash": policy_signature(),
        "total": 8, "quote_usd": 300, "estimated_hours": 10,
        "clarification_questions": questions or []})


@pytest.fixture
def local_workflow(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    @contextmanager
    def scope():
        with Session(engine) as db:
            yield db
            db.commit()
    def dependency():
        with Session(engine) as db:
            yield db
    monkeypatch.setattr(scheduler.common, "get_db_context", scope)
    monkeypatch.setattr(project_service, "get_freelancer_client", lambda: SimpleNamespace())
    import database.connection as connection
    monkeypatch.setattr(connection, "get_db_session", scope)
    app.dependency_overrides[get_db] = dependency
    with scope() as db:
        db.add(Project(freelancer_id=123, title="Python database validation", type_id=1,
            full_description="Validate database numerical values and export a read-only report",
            budget_minimum=100, budget_maximum=500, currency_code="USD",
            submitdate=str(int(time.time())), status="active", skills='["Python"]'))
    yield scope, TestClient(app)
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def get_project(db):
    return db.query(Project).filter_by(freelancer_id=123).one()


def test_clarification_blocks_preparation_and_answers_require_rescoring(local_workflow, monkeypatch):
    scope, client = local_workflow
    with scope() as db:
        p = get_project(db)
        stamp(p, ["How many tables and rows need validation?"])
        row = workflow.apply_score(db, p)
        db.flush()
        revision = row.revision
        question = json.loads(row.questions)[0]
        with pytest.raises(ValueError, match="尚不可准备"):
            asyncio.run(approved_bids.prepare_bid(db, 123, 300, 7))
    payload = {"revision": revision, "answers": [{"id": question["id"], "answer": "Two tables, 50,000 rows; read-only access."}]}
    response = client.post("/api/v1/workflow/123/clarifications", json=payload,
                           headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 200
    assert response.json()["data"]["state"] == "needs_evaluation"
    with scope() as db:
        p = get_project(db)
        assert p.ai_score is None and p.suggested_bid is None
        context = workflow.clarification_context(p)
        assert context[0]["source"] == "operator"
        service = llm.LLMScoringService(llm.LLMScoringConfig(cache_enabled=False))
        assert service._prepare_project_payload(p)["operator_clarifications"] == context
        assert scoring_inputs(p)["clarifications"] == context
        with pytest.raises(ValueError, match="尚不可准备"):
            workflow.require_preparable(db, p)
    assert client.post("/api/v1/workflow/123/clarifications", json=payload,
                       headers={"X-API-Key": "test-api-key"}).status_code == 409


def test_missing_answers_never_clear_clarification(local_workflow):
    scope, client = local_workflow
    with scope() as db:
        p = get_project(db); stamp(p, ["How many rows?", "What acceptance rules?"])
        row = workflow.apply_score(db, p); db.flush()
        revision = row.revision; questions = json.loads(row.questions)
    result = client.post("/api/v1/workflow/123/clarifications", json={
        "revision": revision, "answers": [{"id": questions[0]["id"], "answer": "100"}]},
        headers={"X-API-Key": "test-api-key"})
    assert result.status_code == 400
    with scope() as db:
        assert db.query(CandidateWorkflow).one().state == "needs_clarification"


@pytest.mark.parametrize("action,state", [("defer", "deferred"), ("reject", "rejected")])
def test_operator_decisions_survive_scoring_and_polling(local_workflow, action, state):
    scope, _ = local_workflow
    with scope() as db:
        p = get_project(db); stamp(p)
        row = workflow.refresh_readiness(db, p, 7); db.flush()
        workflow.decide(db, 123, row.revision, action, "No time this week")
        stamp(p)
        workflow.apply_score(db, p)
        assert workflow.refresh_readiness(db, p, 7).state == state
        assert not workflow.evaluation_allowed(db, p)
    assert scheduler.select_bid_candidates(7, ["active"], 7, 3, True) == []


def test_scope_change_discards_old_answers(local_workflow):
    scope, _ = local_workflow
    with scope() as db:
        p = get_project(db); stamp(p, ["How many rows?"])
        row = workflow.apply_score(db, p); db.flush()
        workflow.resolve_questions(db, 123, row.revision,
            [{"id": json.loads(row.questions)[0]["id"], "answer": "100"}])
        assert workflow.clarification_context(p)
        project_service._apply_project_fields(p, {"description": "Build a different full platform"})
        assert workflow.clarification_context(p) == []
        row = workflow.ensure(db, p)
        assert json.loads(row.answers) == [] and row.state == "needs_evaluation"


def test_defer_date_and_stale_revision_are_enforced(local_workflow):
    scope, client = local_workflow
    with scope() as db:
        p = get_project(db); stamp(p)
        row = workflow.refresh_readiness(db, p, 7); db.flush(); revision = row.revision
    headers = {"X-API-Key": "test-api-key"}
    assert client.post("/api/v1/workflow/123/decision", headers=headers, json={
        "revision": revision, "action": "defer", "reason": "Busy", "resume_at": "2030-01-01T00:00:00"}).status_code == 422
    first = client.post("/api/v1/workflow/123/decision", headers=headers, json={
        "revision": revision, "action": "defer", "reason": "Busy",
        "resume_at": (workflow.now()+timedelta(days=1)).isoformat()+"Z"})
    assert first.status_code == 200
    assert client.post("/api/v1/workflow/123/decision", headers=headers, json={
        "revision": revision, "action": "reject", "reason": "Changed decision"}).status_code == 409
    with scope() as db:
        row = db.query(CandidateWorkflow).one(); row.resume_at = workflow.now()-timedelta(seconds=1)
        assert workflow.evaluation_allowed(db, get_project(db))


def test_unknown_submission_cannot_be_resumed(local_workflow):
    scope, client = local_workflow
    with scope() as db:
        row = workflow.ensure(db, get_project(db)); db.flush()
        db.add(BidSubmission(project_freelancer_id=123, status="outcome_unknown",
                             amount=300, currency_code="USD", period=7)); db.flush()
        workflow.reconcile(db); db.flush(); revision = row.revision
    result = client.post("/api/v1/workflow/123/decision", headers={"X-API-Key": "test-api-key"},
        json={"revision": revision, "action": "resume", "reason": "Try again"})
    assert result.status_code == 400
    with scope() as db:
        assert db.query(CandidateWorkflow).one().state == "outcome_unknown"


@pytest.mark.parametrize("path,method", [
    ("/api/v1/workflow", "GET"), ("/api/v1/workflow/stats", "GET"),
    ("/api/v1/workflow/sync", "POST"), ("/api/v1/workflow/123/decision", "POST"),
    ("/api/v1/workflow/123/clarifications", "POST"),
])
def test_workflow_api_requires_key(local_workflow, path, method):
    _, client = local_workflow
    assert client.request(method, path, json={} if method == "POST" else None).status_code == 401


def cycle_arguments():
    return dict(keywords=["python"], limit=5, since_days=7, allowed_statuses=["active"],
        bid_threshold=7, max_bids_per_cycle=1, dry_run=True, fixed_price_only=True,
        logger=logging.getLogger("workflow-tests"), weekly_report_enabled=False)


def test_failed_cycle_persists_failed_stage_and_elapsed(local_workflow, monkeypatch):
    scope, _ = local_workflow
    monkeypatch.setattr(scheduler, "_step_fetch", AsyncMock(side_effect=RuntimeError("offline")))
    with pytest.raises(RuntimeError, match="offline"):
        asyncio.run(scheduler.run_cycle(**cycle_arguments()))
    with scope() as db:
        run = db.query(WorkflowRun).one()
        assert run.status == "failed" and run.failed_stage == "fetch" and run.duration_ms >= 0
        assert json.loads(run.summary)["step_durations_ms"]["fetch"] >= 0
    assert workflow.CURRENT_RUN.get() is None


def test_expensive_competitor_fetch_follows_scoring_and_only_targets_viable_candidates(local_workflow, monkeypatch):
    scope, _ = local_workflow
    order = []
    async def fetch(*args): order.append("fetch"); return {123}
    async def score(*args, **kwargs): order.append("score"); return 1
    async def competition(*args, **kwargs):
        order.append("competition"); assert kwargs["project_ids"] == {123}; return 20
    async def prepare(*args, **kwargs): order.append("prepare"); return [{"status": "dry_run"}]
    monkeypatch.setattr(scheduler, "_step_fetch", fetch)
    monkeypatch.setattr(scheduler, "_step_score", score)
    monkeypatch.setattr(scheduler, "_step_fetch_competitor_bids", competition)
    monkeypatch.setattr(scheduler, "select_bid_candidates", lambda *args: [{"freelancer_id": 123, "ai_score": 8}])
    monkeypatch.setattr(scheduler, "_step_auto_bid", prepare)
    summary = asyncio.run(scheduler.run_cycle(**cycle_arguments()))
    assert order == ["fetch", "score", "competition", "prepare"]
    assert summary["bids_submitted"] == 0 and summary["bids_previewed"] == 1
    with scope() as db:
        assert db.query(WorkflowRun).one().status == "completed"


def test_actual_model_call_and_cache_hit_are_counted_separately(local_workflow, monkeypatch):
    scope, _ = local_workflow
    result = {"dimension_scores": {k: 8 for k in DIMENSIONS}, "reason": "Clear read-only task",
              "estimated_hours": 10, "suggested_bid": 300, "clarification_questions": [],
              "_tokens": 123, "_usage_known": True, "provider_model": "fixture"}
    provider = SimpleNamespace(score=AsyncMock(return_value=result), close=AsyncMock())
    service = llm.LLMScoringService(llm.LLMScoringConfig(
        providers=[llm.LLMProviderConfig(name="openai", api_key="dummy")], cache_enabled=False))
    service._cache = ScoringCache(CacheConfig(persistent=False))
    monkeypatch.setattr(service, "_create_provider_client", lambda _: (provider, object()))
    with scope() as db:
        p = get_project(db)
        for _ in range(2):
            assert asyncio.run(service.score_projects_concurrent([p], db, max_retries=0))[0] == 1
        usage = workflow.statistics(db, workflow.now()-timedelta(days=1))["model_usage"]
        assert usage == {"calls": 1, "cache_hits": 1, "observed_tokens": 123,
                         "token_usage_complete": True, "cost": None}
    assert provider.score.await_count == 1


def test_fetch_records_filter_reasons_and_unique_queue(local_workflow, monkeypatch):
    scope, _ = local_workflow
    base = {"type": "fixed", "status": "active", "description": "Deliver a custom Python API with tests",
            "budget": {"minimum": 100, "maximum": 500}, "currency": {"code": "USD"},
            "submitdate": int(time.time())}
    data = [{**base, "id": 124, "title": "Python API"},
            {**base, "id": 125, "title": "Wedding photography", "description": "Photograph a wedding and deliver the pictures"}]
    monkeypatch.setattr(project_service, "get_freelancer_client", lambda: SimpleNamespace(search_projects=AsyncMock(return_value=data)))
    with scope() as db:
        for _ in range(2):
            asyncio.run(project_service.search_projects(db, query="Python", sync_from_api=True, since_days=7))
        assert db.query(CandidateWorkflow).count() == 1
        stats = workflow.statistics(db, workflow.now()-timedelta(days=1))
        assert {"stage": "filter", "outcome": "excluded", "reason_code": "filtered_skill", "count": 2} in stats["stages"]


def test_empty_fetch_does_not_count_old_local_projects_as_new(local_workflow, monkeypatch):
    scope, _ = local_workflow
    monkeypatch.setattr(project_service, "get_freelancer_client",
                        lambda: SimpleNamespace(search_projects=AsyncMock(return_value=[])))
    with scope() as db:
        assert asyncio.run(project_service.search_projects(db, query="Python", sync_from_api=True, since_days=7)) == []
        assert db.query(Project).count() == 1
        assert db.query(WorkflowEvent).filter_by(stage="fetch", outcome="observed").one().count == 0


def test_qq_rejection_is_reconciled_once_and_cannot_be_overwritten(local_workflow):
    from services.qqbot_service import QQBotConfig
    from services.qqbot_store import QQBotStore
    scope, _ = local_workflow
    config = QQBotConfig.from_env()
    store = QQBotStore(config.state_path)
    snapshot = store.create({"project_id": 123, "account_id": settings.FREELANCER_USER_ID,
        "qq_app_id": config.app_id, "qq_target_id": config.target_id,
        "qq_target_type": config.target_type, "review_required": True})
    with scope() as db:
        p = get_project(db); stamp(p)
        workflow.mark_prepared(db, p, snapshot["id"])
    store.decide(snapshot["id"], snapshot["digest"][:16], actor=next(iter(config.approvers)),
                 scope=config.target_type, target=config.target_id, approve=False)
    with scope() as db:
        for _ in range(2):
            workflow.reconcile(db)
        row = db.query(CandidateWorkflow).one()
        assert row.state == "rejected" and row.held_by == "operator"
        assert workflow.refresh_readiness(db, get_project(db), 7).state == "rejected"
        assert db.query(WorkflowEvent).filter_by(stage="approval", outcome="rejected").count() == 1


def test_resuming_does_not_skip_unanswered_questions(local_workflow):
    scope, _ = local_workflow
    with scope() as db:
        p = get_project(db); stamp(p, ["How many rows?"])
        row = workflow.apply_score(db, p); db.flush()
        row = workflow.decide(db, 123, row.revision, "reject", "Wait for scope")
        row = workflow.decide(db, 123, row.revision, "resume", "Return to this opportunity")
        assert row.state == "needs_clarification"
        assert not workflow.evaluation_allowed(db, p)


def test_old_approval_cannot_revive_after_operator_resume(local_workflow, monkeypatch):
    from services.qqbot_service import QQBotConfig
    from services.qqbot_store import QQBotStore
    scope, _ = local_workflow
    config = QQBotConfig.from_env()
    store = QQBotStore(config.state_path)
    payload = {"project_id": 123, "project_version": None, "account_id": settings.FREELANCER_USER_ID,
        "qq_app_id": config.app_id, "qq_target_id": config.target_id, "qq_target_type": config.target_type,
        "description": "Frozen proposal", "amount": 300, "period": 7, "review_required": True}
    with scope() as db:
        p = get_project(db); stamp(p)
        payload["project_version"] = approved_bids.project_version(p)
        snapshot = store.create(payload)
        store.decide(snapshot["id"], snapshot["digest"][:16], actor=next(iter(config.approvers)),
                     scope=config.target_type, target=config.target_id, approve=True, risk_reviewed=True)
        workflow.mark_prepared(db, p, snapshot["id"]); db.commit()
        row = db.query(CandidateWorkflow).one()
        workflow.decide(db, 123, row.revision, "reject", "Do not proceed")
        workflow.decide(db, 123, row.revision, "resume", "Evaluate again")
        stamp(p); workflow.refresh_readiness(db, p, 7); db.commit()
        assert db.query(CandidateWorkflow).one().approval_id is None
        monkeypatch.setattr(settings, "BID_SUBMISSION_ENABLED", True)
        monkeypatch.setattr(approved_bids, "_validate_frozen_review", lambda _: None)
        remote = AsyncMock()
        monkeypatch.setattr(approved_bids, "get_freelancer_client", remote)
        with pytest.raises(ValueError, match="旧批准"):
            asyncio.run(approved_bids.submit_approved_bid(db, snapshot["id"], store))
        remote.assert_not_called()


def test_changed_or_expired_ready_candidate_cannot_prepare(local_workflow):
    scope, _ = local_workflow
    with scope() as db:
        p = get_project(db); stamp(p)
        row = workflow.refresh_readiness(db, p, 7); db.flush()
        p.scored_at -= timedelta(hours=settings.SCORING_TTL_HOURS+1)
        with pytest.raises(ValueError, match="评分已失效"):
            workflow.require_preparable(db, p)
        stamp(p)
        project_service._apply_project_fields(p, {"description": "Build a new platform with substantially different scope"})
        assert row.state == "needs_evaluation"
        with pytest.raises(ValueError, match="尚不可准备"):
            workflow.require_preparable(db, p)


def test_expired_approval_requires_manual_resume_instead_of_regenerating(local_workflow):
    from services.qqbot_service import QQBotConfig
    from services.qqbot_store import QQBotStore
    scope, _ = local_workflow
    config = QQBotConfig.from_env(); store = QQBotStore(config.state_path)
    snapshot = store.create({"project_id": 123, "account_id": settings.FREELANCER_USER_ID,
        "qq_app_id": config.app_id, "qq_target_id": config.target_id,
        "qq_target_type": config.target_type, "review_required": True})
    with store.connect() as connection:
        connection.execute("UPDATE approvals SET expires_at=? WHERE id=?", (time.time()-1, snapshot["id"]))
    with scope() as db:
        p = get_project(db); stamp(p)
        workflow.mark_prepared(db, p, snapshot["id"]); db.commit()
        workflow.reconcile(db)
        row = db.query(CandidateWorkflow).one()
        assert row.state == "deferred" and row.resume_condition == "manual"
        stamp(p); workflow.apply_score(db, p)
        assert workflow.refresh_readiness(db, p, 7).state == "deferred"
        assert not workflow.evaluation_allowed(db, p)
        project_service._apply_project_fields(p, {"description": "Updated Python database validation requirements"})
        assert row.state == "deferred" and row.resume_condition == "manual"


def test_submission_exception_never_downgrades_unknown_result_to_resumable_queue(local_workflow, monkeypatch):
    from services.qqbot_store import QQBotStore
    from services import qqbot_events
    from services.freelancer_client import FreelancerAPIError
    scope, _ = local_workflow
    with scope() as db:
        p = get_project(db); stamp(p); workflow.refresh_readiness(db, p, 7)
    async def prepare(db, pid, *args, **kwargs):
        workflow.mark_prepared(db, get_project(db), "fixture")
        return {"id": "fixture"}
    async def submit(db, identity, store):
        db.add(BidSubmission(project_freelancer_id=123, status="outcome_unknown",
                             amount=300, currency_code="USD", period=7))
        db.commit(); workflow.reconcile(db)
        raise FreelancerAPIError("Reply lost", status_code=409)
    monkeypatch.setattr(approved_bids, "prepare_bid", prepare)
    monkeypatch.setattr(approved_bids, "submit_approved_bid", submit)
    monkeypatch.setattr(qqbot_events, "notify_snapshot", lambda *args: False)
    monkeypatch.setattr(QQBotStore, "get", lambda *args: {"state": "approved"})
    candidate = {"freelancer_id": 123, "suggested_bid": 300, "estimated_hours": 10, "currency_code": "USD"}
    result = asyncio.run(scheduler._step_auto_bid([candidate], False, logging.getLogger("queue-test")))
    assert result[0]["status"] == "error"
    with scope() as db:
        assert db.query(CandidateWorkflow).one().state == "outcome_unknown"
