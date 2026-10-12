import asyncio
import json
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

import scheduler
from config import settings
from database.connection import Base, _migrate_add_columns
from database.models import Project, ScoringRule
from services import llm_scoring_service as llm, project_service, approved_bids
from services.project_scorer import ProjectScorer, ScoringConfig
from services.scoring_cache import ScoringCache, CacheConfig
from services.scoring_policy import (DIMENSIONS, SCORING_VERSION, digest, evaluate_result,
    policy_signature, resolve_weights, score_is_current, scoring_inputs)


def model_result(**changes):
    return {"score": 6.2, "dimension_scores": {k: 8 for k in DIMENSIONS},
            "reason": "Explicit scope; client history unknown", "suggested_bid": 300,
            "estimated_hours": 10, "provider_model": "fixture", **changes}


def project(**changes):
    return Project(freelancer_id=123, title="Python API integration",
        full_description="Deliver Python API with acceptance tests", status="active",
        currency_code="USD", budget_minimum=100, budget_maximum=500, type_id=1,
        skills='["Python"]', submitdate=str(int(time.time())), **changes)


def stamp(p, score=8):
    p.ai_score = score
    p.suggested_bid = 300
    p.estimated_hours = 10
    p.hourly_rate = 30
    p.scored_at = datetime.now(timezone.utc).replace(tzinfo=None)
    p.score_metadata = json.dumps({"source": "llm", "version": SCORING_VERSION,
        "input_hash": digest(scoring_inputs(p)), "policy_hash": policy_signature(),
        "total": score, "estimated_hours": 10, "quote_usd": 300})


@pytest.fixture
def db_scope(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    @contextmanager
    def scope():
        with Session(engine) as db:
            yield db
            db.commit()
    monkeypatch.setattr(scheduler.common, "get_db_context", scope)
    yield scope
    engine.dispose()


def fake_service(monkeypatch, result):
    service = llm.LLMScoringService(llm.LLMScoringConfig(
        providers=[llm.LLMProviderConfig(name="openai", api_key="dummy")],
        cache_enabled=False, generate_proposals=False))
    monkeypatch.setattr(service, "_create_provider_client",
        lambda _: (SimpleNamespace(close=AsyncMock()), object()))
    monkeypatch.setattr(service, "_score_with_providers", AsyncMock(return_value=(True, result)))
    return service


def test_low_net_hourly_is_preserved_without_newcomer_bonus(monkeypatch, db_scope):
    service = fake_service(monkeypatch, model_result(suggested_bid=30, estimated_hours=10))
    with db_scope() as db:
        p = project()
        p.budget_minimum, p.budget_maximum = 10, 30
        db.add(p); db.commit()
        assert asyncio.run(service.score_projects_concurrent([p], db, max_retries=0))[:2] == (1, 0)
        metadata = json.loads(p.score_metadata)
        assert p.hourly_rate == 3
        assert metadata["net_hourly_usd"] == 2.5
        assert metadata["dimensions"]["budget_efficiency"] < 2
        assert p.ai_score == round(sum(metadata["dimensions"][k] * metadata["weights"][k]
                                      for k in DIMENSIONS), 2)
        assert p.ai_score < 7
    assert scheduler.select_bid_candidates(3, ["active"], 0, 1, True) == []


@pytest.mark.parametrize("field,value", [
    ("score", "NaN"), ("score", "Infinity"), ("score", True),
    ("suggested_bid", float("inf")), ("suggested_bid", 0),
    ("estimated_hours", -1), ("estimated_hours", 1.5),
    ("estimated_hours", None), ("dimension_scores", {"tech": 8}),
    ("dimension_scores", {k: float("nan") for k in DIMENSIONS}),
])
def test_bad_model_output_never_persists_a_score(monkeypatch, db_scope, field, value):
    service = fake_service(monkeypatch, model_result(**{field: value}))
    with db_scope() as db:
        p = project(); db.add(p); db.commit()
        assert asyncio.run(service.score_projects_concurrent([p], db, max_retries=0))[:2] == (0, 1)
        assert p.ai_score is None and p.score_metadata is None
    assert llm.OpenAIProvider()._parse_response(json.dumps(model_result(**{field: value})), "fixture") is None


@pytest.mark.parametrize("payload", [
    {"bid_stats": {"bid_count": 100}}, {"owner_info": {"payment_verified": False}},
    {"skills": ["Design"]}, {"age_hours": 100}, {"scoring_context": {"model": "different"}},
])
def test_cache_changes_with_dynamic_inputs_and_model(payload):
    cache = ScoringCache(CacheConfig(persistent=False))
    original = {"id": 1, "title": "Python", "description": "Scope", "budget_maximum": 300}
    cache.set_llm_score(original, model_result(), "same-prompt")
    assert cache.get_llm_score({**original, **payload}, "same-prompt") is None


@pytest.mark.parametrize("change", [
    {"bid_stats": {"bid_count": 100}}, {"owner_info": {"payment_verified": False}},
    {"submitdate": str(int(time.time()) - 3600)},
])
def test_dynamic_sync_invalidates_score(db_scope, change):
    p = project(); stamp(p)
    project_service._apply_project_fields(p, change)
    assert p.ai_score is None and p.score_metadata is None and p.scored_at is None


def test_freshness_checks_time_source_version_policy_and_inputs():
    p = project(); stamp(p)
    assert score_is_current(p)
    p.scored_at -= timedelta(hours=settings.SCORING_TTL_HOURS)
    assert not score_is_current(p)
    stamp(p)
    assert not score_is_current(p, "different-policy")
    metadata = json.loads(p.score_metadata)
    metadata["source"] = "manual"; p.score_metadata = json.dumps(metadata)
    assert not score_is_current(p)
    stamp(p); p.bid_stats = '{"bid_count": 100}'
    assert not score_is_current(p)
    stamp(p); p.suggested_bid = 200
    assert not score_is_current(p)


def test_rule_hours_do_not_match_incidental_words_or_shrink_platforms():
    scorer = ProjectScorer()
    assert scorer.estimate_project_hours({"title": "Python happy repair"}) == scorer.estimate_project_hours({"title": "Python repair"})
    assert scorer.estimate_project_hours({"title": "API integration make report"}) == scorer.estimate_project_hours({"title": "API integration"})
    assert scorer.estimate_project_hours({"title": "AI platform", "full_description": "TypeScript update bug script"}) >= 80
    assert scorer.estimate_project_hours({"title": "Fix Android app bug", "full_description": "Small isolated crash fix"}) <= 20


@pytest.mark.parametrize("title", ["Edit a wedding video", "Design a social media banner", "Write AI marketing articles"])
def test_non_development_tasks_do_not_match_generic_capability_words(title):
    assert not project_service._check_skill_match({"title": title})


def test_weight_overrides_apply_without_mutating_yaml(db_scope):
    original = dict(settings.scoring_rules["weights"])
    cfg = ScoringConfig(weights={k: float(k == "tech") for k in DIMENSIONS}, user_skills=["python"])
    p = project()
    result = ProjectScorer(cfg).score_project(p.to_dict())
    assert result.ai_score == result.score_breakdown.tech_score
    with db_scope() as db:
        db.add(ScoringRule(name="tech_match", weight=0.5, is_active=True))
        db.commit()
        assert resolve_weights(db)["tech"] > original["tech"]
    assert settings.scoring_rules["weights"] == original


def test_invalid_top_candidate_is_skipped_before_limit(db_scope):
    with db_scope() as db:
        top = project(); stamp(top, 9)
        top.estimated_hours = 100
        metadata = json.loads(top.score_metadata)
        metadata["estimated_hours"] = 100
        top.score_metadata = json.dumps(metadata)
        second = project()
        second.freelancer_id = 124
        stamp(second, 8)
        db.add_all([top, second])
    assert [p["freelancer_id"] for p in scheduler.select_bid_candidates(3, ["active"], 7, 1, True)] == [124]


def test_legacy_and_expired_scores_do_not_enter_candidates(db_scope):
    with db_scope() as db:
        p = project(); stamp(p)
        p.scored_at -= timedelta(hours=settings.SCORING_TTL_HOURS + 1)
        db.add(p)
        legacy = project(); legacy.freelancer_id = 124; legacy.ai_score = 9
        db.add(legacy)
    assert scheduler.select_bid_candidates(3, ["active"], 7, 3, True) == []


def test_failed_preparation_backfills_and_defers_bad_candidate(monkeypatch, db_scope):
    from services.qqbot_service import QQBotConfig
    from services.qqbot_store import QQBotStore
    from services import qqbot_events
    config = QQBotConfig.from_env()
    monkeypatch.setattr(scheduler, "_determine_bid_period", lambda _: 7)
    monkeypatch.setattr(qqbot_events, "notify_snapshot", lambda *_: None)
    calls = []
    async def prepare(db, pid, *_args, **_kwargs):
        calls.append(pid)
        if pid == 123:
            raise ValueError("Proposal quality failed")
        # A fixture snapshot does not involve any real QQ message.
        return {"id": "fixture"}
    monkeypatch.setattr(approved_bids, "prepare_bid", prepare)
    monkeypatch.setattr(QQBotStore, "get", lambda *_: {"state": "pending"})
    submit = AsyncMock()
    monkeypatch.setattr(approved_bids, "submit_approved_bid", submit)
    with db_scope() as db:
        first = project(); stamp(first, 9)
        second = project(); second.freelancer_id = 124; stamp(second, 8)
        db.add_all([first, second])
    selector = lambda: scheduler.select_bid_candidates(3, ["active"], 7, 1, True)
    import logging
    result = asyncio.run(scheduler._step_auto_bid(selector(), True, logging.getLogger("repair"), selector))
    assert calls == [123, 124]
    assert [r["status"] for r in result] == ["error", "dry_run"]
    assert selector()[0]["freelancer_id"] == 124
    submit.assert_not_awaited()


def test_schema_upgrade_is_idempotent_and_keeps_legacy_rows(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE projects (id INTEGER PRIMARY KEY, title TEXT, ai_score FLOAT)"))
        conn.execute(text("INSERT INTO projects VALUES (1, 'Existing project', 8)"))
    _migrate_add_columns(engine)
    _migrate_add_columns(engine)
    assert {"score_metadata", "scored_at"} <= {c["name"] for c in inspect(engine).get_columns("projects")}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT title, ai_score, score_metadata FROM projects")).one() == ("Existing project", 8, None)
    engine.dispose()


def test_cli_rescores_legacy_fixed_project_before_applying_limit(monkeypatch, db_scope, tmp_path):
    import importlib.util
    from pathlib import Path
    script = Path(__file__).resolve().parents[2] / "scripts/manual_pipeline/03_score_concurrent.py"
    spec = importlib.util.spec_from_file_location("repair_score_cli", script)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    with db_scope() as db:
        hourly = project(); hourly.freelancer_id = 124; hourly.type_id = 2
        fixed = project(); fixed.ai_score = 8
        fixed.submitdate = str(int(time.time()) - 120)
        db.add_all([hourly, fixed])
    monkeypatch.setattr(cli.common, "load_env", lambda: None)
    monkeypatch.setattr(cli.common, "get_settings", lambda: settings)
    monkeypatch.setattr(type(settings), "get_enabled_llm_providers",
                        lambda self: [{"name": "openai", "model": "fixture", "api_key": "dummy"}])
    captured = []
    async def score(**kwargs):
        captured.extend(p.freelancer_id for p in kwargs["projects"])
        return 1, 0, 8, 123
    call = AsyncMock(side_effect=score)
    monkeypatch.setattr(cli, "get_scoring_service", lambda: SimpleNamespace(score_projects_concurrent=call))
    assert cli.main(["--limit", "1", "--lock-file", str(tmp_path / "lock")]) == 0
    assert captured == [123]


def test_partial_client_metadata_remains_unknown():
    p = project(owner_info='{"id": 456}')
    payload = {"budget_maximum": 500, "age_hours": 1, "bid_stats": None}
    result = evaluate_result(p, model_result(), payload, resolve_weights(), policy_signature())
    assert "customer" in result["metadata"]["unknown"]
    assert result["metadata"]["dimensions"]["customer"] == 5
    assert result["metadata"]["dimensions"]["risk"] <= 5


def test_one_project_strategy_uses_the_same_economic_contract(monkeypatch):
    service = fake_service(monkeypatch, model_result(suggested_bid=30))
    p = project(); p.budget_minimum, p.budget_maximum = 10, 30
    result = asyncio.run(service.score_single_project(p))
    assert result["hourly_rate"] == 3
    assert result["metadata"]["net_hourly_usd"] == 2.5
    assert result["score"] < 7


def test_reserved_candidate_is_excluded_while_next_valid_one_is_selected(db_scope):
    from database.models import BidSubmission
    with db_scope() as db:
        first = project(); stamp(first, 9)
        second = project(); second.freelancer_id = 124; stamp(second, 8)
        db.add_all([first, second]); db.flush()
        db.add(BidSubmission(project_freelancer_id=123, status="outcome_unknown",
                             amount=300, currency_code="USD", period=7))
    assert [p["freelancer_id"] for p in scheduler.select_bid_candidates(3, ["active"], 7, 1, True)] == [124]
