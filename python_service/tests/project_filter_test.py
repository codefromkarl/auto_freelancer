import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database.connection import Base
from database.models import Project
from services import project_service
from services.freelancer_client import FreelancerClient
from services.freelancer_client import FreelancerAPIError


@pytest.mark.parametrize("text,expected", [
    ("Paid chair repair and capital planning", False),
    ("FastAPI OAuth API integration", True),
    ("Implement an AI workflow", True),
    ("Maintain a website", False),
])
def test_skill_words_are_not_arbitrary_substrings(text, expected):
    assert project_service._check_skill_match({"title": text}) is expected


def test_full_description_and_named_jobs_match_without_id_guessing():
    assert project_service._check_skill_match({"preview_description": "Short summary",
        "description": "Deliver a Python backend API"})
    assert project_service._check_skill_match({"jobs": [{"id": 999, "name": "Python"}]})
    assert not project_service._check_skill_match({"jobs": [101, 104]})


@pytest.mark.parametrize("changes,reason", [
    ({"type": None}, "filtered_billing_type"),
    ({"currency": {}}, "filtered_data"),
    ({"budget": {"maximum": float('nan')}}, "filtered_data"),
    ({"currency": {"code": "XXX"}}, "filtered_data"),
])
def test_uncertain_budget_and_type_are_deferred(monkeypatch, changes, reason):
    monkeypatch.setattr(project_service, "get_currency_converter", lambda:
        SimpleNamespace(get_rate_sync=lambda code: 1.0 if code == "USD" else None))
    item = {"type": "fixed", "title": "Python API", "description": "Python API implementation",
            "budget": {"maximum": 100}, "currency": {"code": "USD"}, "status": "active"}
    item.update(changes)
    kept, stats = project_service._pre_filter_projects([item], budget_min_threshold=5)
    assert kept == []
    assert stats[reason] == 1


def test_enrichment_persists_fields_and_keeps_submission_marker():
    item = FreelancerClient._enrich_project({
        "id": 123, "title": "Python API", "owner_id": 456, "status": "active", "type": "fixed",
        "description": "A complete Python API description", "jobs": [{"id": 1, "name": "Python"}],
        "bid_stats": {"bid_count": 9}, "budget": {"minimum": 100, "maximum": 500},
        "currency": {"code": "USD"},
    }, {"456": {"id": 456, "payment_verified": True}})
    project = Project(freelancer_id=123, status="bid_submitted")
    project_service._apply_project_fields(project, item)
    assert project.full_description == item['description']
    assert project.owner_id == 456
    assert project.to_dict()['owner_info']['payment_verified'] is True
    assert project.to_dict()['bid_stats']['bid_count'] == 9
    assert project.skills == '["Python"]'
    assert project.status == 'bid_submitted'


def test_material_changes_clear_stale_score_but_unchanged_sync_preserves_it():
    project = Project(freelancer_id=123,title='Python API',full_description='Original scope',
        currency_code='USD',type_id=1,skills='["Python"]',budget_maximum=500,
        ai_score=8,ai_reason='Previously checked',suggested_bid=450,estimated_hours=20,
        hourly_rate=22.5,ai_proposal_draft='Old draft')
    unchanged = {'title':'Python API','description':'Original scope','type':'fixed',
        'jobs':[{'name':'Python'}],'currency':{'code':'USD'},'budget':{'maximum':500}}
    project_service._apply_project_fields(project,unchanged)
    assert project.ai_score==8
    project_service._apply_project_fields(project,dict(unchanged,description='New scope'))
    assert all(getattr(project,k) is None for k in ('ai_score','ai_reason','suggested_bid',
        'estimated_hours','hourly_rate','ai_proposal_draft'))


def test_freshness_uses_remote_publication_time_in_all_supported_formats():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    recent = now - timedelta(days=1)
    stale = now - timedelta(days=20)
    with Session(engine) as db:
        for i, timestamp in enumerate([str(int(recent.timestamp())),
                                      str(int(recent.timestamp()*1000)), recent.isoformat(),
                                      str(int(stale.timestamp())), None, 'invalid'], 1):
            db.add(Project(freelancer_id=i, title='Python', submitdate=timestamp,
                           created_at=now.replace(tzinfo=None)))
        db.commit()
        found = db.query(Project).filter(project_service.published_since(now-timedelta(days=7))).all()
        assert {p.freelancer_id for p in found} == {1, 2, 3}
    engine.dispose()


def test_failed_remote_sync_does_not_return_stale_local_success(monkeypatch):
    client = SimpleNamespace(search_projects=AsyncMock(side_effect=FreelancerAPIError("offline", status_code=503)))
    monkeypatch.setattr(project_service, "get_freelancer_client", lambda: client)
    with pytest.raises(FreelancerAPIError, match="offline"):
        asyncio.run(project_service.search_projects(object(), query="python", sync_from_api=True))
    assert project_service.is_currently_syncing() is False


def test_search_requests_full_metadata_and_enriches_owner(monkeypatch):
    import services.freelancer_client as client_module
    captured = {}
    def search(_session, **kwargs):
        captured.update(kwargs)
        return {"projects": [{"id": 123, "owner_id": 456, "description": "Full description"}],
                "users": {"456": {"id": 456, "payment_verified": True}}}
    monkeypatch.setattr(client_module, "search_projects", search)
    result = asyncio.run(FreelancerClient().search_projects(query="python", limit=5))
    assert captured['project_details']['full_description'] is True
    assert captured['project_details']['job_details'] is True
    assert result[0]['owner_info']['payment_verified'] is True
