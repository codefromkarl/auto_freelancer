from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database.connection import Base, get_db
from database.models import Bid, Project
from main import app


def test_all_business_routes_require_key(monkeypatch):
    monkeypatch.setenv("BYPASS_AUTH", "true")  # An environment flag must not remove authentication.
    client = TestClient(app)
    routes = [r for r in app.routes if isinstance(r, APIRoute) and r.path.startswith("/api/")]
    assert routes
    for route in routes:
        path = route.path
        for parameter in route.param_convertors:
            path = path.replace("{" + parameter + "}", "123")
        for method in route.methods:
            assert client.request(method, path).status_code == 401, (method, path)
            assert client.request(method, path, headers={"X-API-Key": "wrong"}).status_code == 403, (method, path)
    assert client.get("/health").status_code == 200


def test_proposal_list_handles_empty_and_multiple_bids():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=__import__("sqlalchemy").pool.StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        app.dependency_overrides[get_db] = lambda: db
        try:
            client = TestClient(app)
            headers = {"X-API-Key": "test-api-key"}
            empty = client.get("/api/v1/proposals", headers=headers)
            assert empty.status_code == 200
            assert empty.json()["data"] == []
            project = Project(freelancer_id=123, title="Real local project")
            db.add(project)
            db.flush()
            for bid_id in (456, 457):
                db.add(Bid(freelancer_bid_id=bid_id, project_id=project.id,
                           project_freelancer_id=123, bidder_id=999, amount=100, period=7))
            db.commit()
            response = client.get("/api/v1/proposals", headers=headers)
            assert response.status_code == 200
            assert {row["id"] for row in response.json()["data"]} == {456, 457}
            assert response.json()["total"] == 2
        finally:
            app.dependency_overrides.clear()
    engine.dispose()
