from contextlib import contextmanager
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api import messages, projects
from database.connection import Base, get_db
from database.models import Message, MessageThread, Project
from main import app


@pytest.fixture
def local_reads(monkeypatch):
    engine = create_engine("sqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(freelancer_id=123, title="Cached Python API project", status="active",
                          full_description="Build a Python API integration with acceptance tests",
                          budget_minimum=100, budget_maximum=500, currency_code="USD", type_id=1)
        db.add(project)
        db.flush()
        db.add(MessageThread(freelancer_thread_id=42, project_id=project.id,
                             project_freelancer_id=123, unread_count=1))
        db.add(Message(freelancer_message_id=77, thread_id=42,
                       message="Stored message", user_id=1001, is_read=False))
        db.commit()

    @contextmanager
    def committed_session():
        with Session(engine) as db:
            yield db
            db.commit()  # Reproduce the real commit/expire/close lifecycle.

    def request_session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = request_session
    monkeypatch.setattr(messages, "get_db_session", committed_session)
    remote = AsyncMock(return_value={"id": 123, "title": "Refreshed project"})
    monkeypatch.setattr(projects.project_service, "get_project_details", remote)
    yield TestClient(app), remote, engine
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def test_cached_project_detail_does_not_call_remote(local_reads):
    client, remote, _ = local_reads
    result = client.get("/api/v1/projects/123", headers={"X-API-Key": "test-api-key"})
    assert result.status_code == 200
    assert result.json()["data"]["title"] == "Cached Python API project"
    remote.assert_not_called()


@pytest.mark.parametrize("path", ["/api/v1/projects/123?refresh=true", "/api/v1/projects/999"])
def test_explicit_refresh_and_uncached_project_use_remote(local_reads, path):
    client, remote, _ = local_reads
    result = client.get(path, headers={"X-API-Key": "test-api-key"})
    assert result.status_code == 200
    remote.assert_awaited_once()


def test_threads_survive_session_expiration_and_filter_correctly(local_reads):
    client, _, _ = local_reads
    headers = {"X-API-Key": "test-api-key"}
    response = client.get("/api/v1/messages/threads", headers=headers)
    assert response.status_code == 200
    assert response.json()["data"][0]["thread_id"] == 42
    assert client.get("/api/v1/messages/threads?project_id=999", headers=headers).json()["data"] == []


def test_messages_serialize_and_persist_read_state(local_reads):
    client, _, engine = local_reads
    response = client.get("/api/v1/messages/42", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 200
    row = response.json()["data"][0]
    assert row["message"] == "Stored message"
    assert row["is_read"] is True
    with Session(engine) as db:
        assert db.query(Message).one().is_read is True


def test_cached_project_with_nullable_metadata_scores_and_persists(local_reads, monkeypatch):
    client, remote, engine = local_reads
    from services.llm_scoring_service import LLMScoringService, LLMScoringConfig, LLMProviderConfig
    from services.scoring_policy import DIMENSIONS
    from types import SimpleNamespace
    service = LLMScoringService(LLMScoringConfig(
        providers=[LLMProviderConfig(name="openai", api_key="test")], cache_enabled=False))
    monkeypatch.setattr(service, "_create_provider_client", lambda _: (SimpleNamespace(close=AsyncMock()), object()))
    monkeypatch.setattr(service, "_score_with_providers", AsyncMock(return_value=(True, {
        "dimension_scores": {k: 8 for k in DIMENSIONS}, "reason": "Known scope, unknown client",
        "suggested_bid": 300, "estimated_hours": 10, "provider_model": "fixture"})))
    monkeypatch.setattr(projects, "get_scoring_service", lambda: service)
    response = client.post("/api/v1/projects/123/score", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert 0 <= data["ai_score"] <= 10
    assert data["estimated_hours"] > 0
    assert data["hourly_rate"] == 30
    assert data["score_metadata"]["source"] == "llm"
    assert data["score_metadata"]["unknown"] == ["customer", "competition", "publication_time"]
    remote.assert_not_called()
    with Session(engine) as db:
        row = db.query(Project).one()
        assert row.ai_score == data["ai_score"]
        assert row.hourly_rate == data["hourly_rate"]


def test_web_scoring_never_falls_back_when_no_provider(local_reads, monkeypatch):
    from types import SimpleNamespace
    client, _, _ = local_reads
    monkeypatch.setattr(projects, 'get_scoring_service', lambda: SimpleNamespace(
        score_projects_concurrent=AsyncMock(return_value=(0, 1, 0, None))))
    result = client.post('/api/v1/projects/123/score', headers={'X-API-Key': 'test-api-key'})
    assert result.status_code == 422
