import asyncio
import sys
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON_SERVICE_ROOT = REPO_ROOT / "python_service"
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

from database.connection import Base
from database.models import Bid, Project
from services import competitor_bid_service


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    return session


def _seed_project(db, freelancer_id: int):
    p = Project(
        freelancer_id=freelancer_id,
        title=f"Project {freelancer_id}",
        status="open",
        currency_code="USD",
        budget_minimum=Decimal("100"),
        budget_maximum=Decimal("500"),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def test_fetch_and_save_bids_persists_competitor_description(monkeypatch):
    db = _make_db()
    project = _seed_project(db, freelancer_id=99001)

    class _FakeClient:
        async def get_project_bids(self, _project_id):
            return [
                {
                    "id": 500001,
                    "bidder_id": 101,
                    "amount": 220,
                    "period": 6,
                    "award_status": "pending",
                    "description": "I can deliver with tests and deployment notes.",
                }
            ]

    monkeypatch.setattr(
        competitor_bid_service,
        "get_freelancer_client",
        lambda: _FakeClient(),
    )

    upserted = asyncio.run(
        competitor_bid_service.fetch_and_save_bids(db, project.freelancer_id)
    )
    assert upserted == 1

    row = db.execute(
        text(
            "SELECT description FROM competitor_bid_contents WHERE bid_id = :bid_id"
        ),
        {"bid_id": 500001},
    ).fetchone()
    assert row is not None
    assert row[0] == "I can deliver with tests and deployment notes."
    db.close()


def test_sync_bids_for_our_projects_uses_distinct_project_ids(monkeypatch):
    db = _make_db()
    project_a = _seed_project(db, freelancer_id=99011)
    project_b = _seed_project(db, freelancer_id=99012)

    db.add(Bid(
        freelancer_bid_id=600001,
        project_id=project_a.id,
        project_freelancer_id=project_a.freelancer_id,
        bidder_id=90492953,
        amount=Decimal("100"),
        period=7,
        status="active",
        submitdate="2026-02-16",
        description="a",
    ))
    db.add(Bid(
        freelancer_bid_id=600002,
        project_id=project_a.id,
        project_freelancer_id=project_a.freelancer_id,
        bidder_id=90492953,
        amount=Decimal("120"),
        period=7,
        status="active",
        submitdate="2026-02-16",
        description="b",
    ))
    db.add(Bid(
        freelancer_bid_id=600003,
        project_id=project_b.id,
        project_freelancer_id=project_b.freelancer_id,
        bidder_id=90492953,
        amount=Decimal("130"),
        period=8,
        status="active",
        submitdate="2026-02-16",
        description="c",
    ))
    db.commit()

    captured = {}

    async def _fake_batch_fetch(_db, project_freelancer_ids, concurrency):
        captured["ids"] = list(project_freelancer_ids)
        captured["concurrency"] = concurrency
        return {pid: 1 for pid in project_freelancer_ids}

    monkeypatch.setattr(
        competitor_bid_service,
        "batch_fetch_bids",
        _fake_batch_fetch,
    )

    result = asyncio.run(
        competitor_bid_service.sync_bids_for_our_projects(db, concurrency=9)
    )
    assert result == {project_a.freelancer_id: 1, project_b.freelancer_id: 1}
    assert sorted(captured["ids"]) == [project_a.freelancer_id, project_b.freelancer_id]
    assert captured["concurrency"] == 9
    db.close()
