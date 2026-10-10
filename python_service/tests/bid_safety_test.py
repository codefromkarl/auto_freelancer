import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.connection import Base
from database.models import AuditLog, Bid, BidSubmission, Project
from services import bid_service


@pytest.fixture
def bidding(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'bidding.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add(Project(freelancer_id=123, title="Python API", status="open", currency_code="USD"))
        db.commit()
    client = SimpleNamespace(user_id=999,
        get_project=AsyncMock(return_value={"status": "open"}),
        create_bid=AsyncMock(return_value={"id": 456, "bidder_id": 999}))
    monkeypatch.setattr(bid_service, "get_freelancer_client", lambda: client)
    monkeypatch.setattr(bid_service, "check_content_risk", lambda *_: (True, "ok"))
    yield sessions, client
    engine.dispose()


async def submit(db, **overrides):
    kwargs = dict(project_id=123, amount=100.25, period=7, description="Reviewed final proposal")
    kwargs.update(overrides)
    return await bid_service.create_bid(db, **kwargs)


def test_invalid_content_never_submits(bidding, monkeypatch):
    sessions, client = bidding
    monkeypatch.setattr(bid_service, "check_content_risk", lambda *_: (False, "invalid content"))
    with sessions() as db, pytest.raises(ValueError, match="content validation"):
        asyncio.run(submit(db))
    client.create_bid.assert_not_called()


def test_generation_must_be_validated_even_with_cached_draft(bidding, monkeypatch):
    sessions, client = bidding
    generator = SimpleNamespace(generate_proposal=AsyncMock(return_value={
        "success": True, "proposal": "fallback draft", "validation_passed": False}))
    monkeypatch.setattr(bid_service, "get_proposal_service", lambda: generator)
    with sessions() as db:
        db.query(Project).first().ai_proposal_draft = "Unverified cached draft"
        db.commit()
        with pytest.raises(ValueError, match="generation/validation"):
            asyncio.run(submit(db, description=None))
    client.create_bid.assert_not_called()


@pytest.mark.parametrize("remote", [{"status": "closed"}, {}, {"result": {"status": "cancelled"}}])
def test_remote_status_blocks_submission(bidding, remote):
    sessions, client = bidding
    client.get_project.return_value = remote
    with sessions() as db, pytest.raises(ValueError, match="not biddable"):
        asyncio.run(submit(db))
    client.create_bid.assert_not_called()


def test_remote_status_failure_blocks_submission(bidding):
    sessions, client = bidding
    client.get_project.side_effect = TimeoutError("lookup timed out")
    with sessions() as db, pytest.raises(ValueError, match="remote_status_check_failed"):
        asyncio.run(submit(db))
    client.create_bid.assert_not_called()


def test_success_records_exact_amount_and_blocks_repeat(bidding):
    sessions, client = bidding
    with sessions() as db:
        result = asyncio.run(submit(db))
        assert result["amount"] == 100.25
        assert db.query(Bid).count() == 1
        assert db.query(BidSubmission).one().status == "submitted"
        assert db.query(Project).one().status == "bid_submitted"
    with sessions() as db, pytest.raises(ValueError, match="reserved"):
        asyncio.run(submit(db))
    assert client.create_bid.call_count == 1


@pytest.mark.parametrize("response", [{}, {"id": None}, {"result": {"id": 0}}])
def test_incomplete_response_is_unknown_and_cannot_retry(bidding, response):
    sessions, client = bidding
    client.create_bid.return_value = response
    with sessions() as db, pytest.raises(bid_service.FreelancerAPIError, match="incomplete"):
        asyncio.run(submit(db))
    with sessions() as db:
        assert db.query(BidSubmission).one().status == "outcome_unknown"
        assert db.query(Bid).count() == 0
        with pytest.raises(ValueError, match="reserved"):
            asyncio.run(submit(db))
    assert client.create_bid.call_count == 1


def test_timeout_and_crash_reservations_block_retry(bidding):
    sessions, client = bidding
    client.create_bid.side_effect = TimeoutError("reply lost")
    with sessions() as db, pytest.raises(bid_service.FreelancerAPIError, match="unknown"):
        asyncio.run(submit(db))
    with sessions() as db:
        row = db.query(BidSubmission).one()
        assert row.status == "outcome_unknown"
        row.status = "submitting"
        db.commit()
    with sessions() as db, pytest.raises(ValueError, match="reserved"):
        asyncio.run(submit(db))
    assert client.create_bid.call_count == 1


def test_local_persistence_failure_keeps_reservation(bidding, monkeypatch):
    sessions, client = bidding
    with sessions() as db:
        commit = db.commit
        commits = 0
        def fail_final_commit():
            nonlocal commits
            commits += 1
            if commits == 2:
                raise RuntimeError("disk failure")
            commit()
        monkeypatch.setattr(db, "commit", fail_final_commit)
        with pytest.raises(bid_service.FreelancerAPIError, match="persistence failed"):
            asyncio.run(submit(db))
    with sessions() as db:
        assert db.query(BidSubmission).one().status == "outcome_unknown"
        with pytest.raises(ValueError, match="reserved"):
            asyncio.run(submit(db))
    assert client.create_bid.call_count == 1


def test_concurrent_sessions_only_submit_once(bidding):
    sessions, client = bidding
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        async def slow_remote(**_kwargs):
            started.set()
            await release.wait()
            return {"id": 456, "bidder_id": 999}
        client.create_bid.side_effect = slow_remote
        with sessions() as first, sessions() as second:
            task = asyncio.create_task(submit(first))
            await started.wait()
            try:
                with pytest.raises(ValueError, match="reserved"):
                    await submit(second)
            finally:
                release.set()
            await task
    asyncio.run(run())
    assert client.create_bid.call_count == 1


def test_candidates_exclude_unknown_submissions(bidding, monkeypatch):
    from scheduler import select_bid_candidates
    import common
    sessions, _ = bidding
    with sessions() as db:
        db.query(Project).one().ai_score = 9
        db.add(BidSubmission(project_freelancer_id=123, status="outcome_unknown",
                             amount=100, currency_code="USD", period=7))
        db.commit()
    @contextmanager
    def context():
        with sessions() as db:
            yield db
    monkeypatch.setattr(common, "get_db_context", context)
    assert select_bid_candidates(7, ["open"], 7, 3, False) == []


def test_racing_reservations_use_unique_project_key(bidding, monkeypatch):
    sessions, client = bidding
    async def run():
        checked = 0
        both_checked = asyncio.Event()
        async def status_check(*_args):
            nonlocal checked
            checked += 1
            if checked == 2:
                both_checked.set()
            await both_checked.wait()
            return True, "ok"
        monkeypatch.setattr(bid_service, "validate_project_biddable_now", status_check)
        with sessions() as first, sessions() as second:
            results = await asyncio.gather(submit(first), submit(second), return_exceptions=True)
        assert sum(isinstance(r, dict) for r in results) == 1
        assert sum(isinstance(r, ValueError) for r in results) == 1
    asyncio.run(run())
    assert client.create_bid.call_count == 1


def test_update_rejects_invalid_description(bidding, monkeypatch):
    sessions, client = bidding
    client.update_bid = AsyncMock()
    with sessions() as db:
        asyncio.run(submit(db))
        monkeypatch.setattr(bid_service, "check_content_risk", lambda *_: (False, "unsafe"))
        with pytest.raises(ValueError, match="content validation"):
            asyncio.run(bid_service.update_bid(db, 456, description="invalid replacement"))
    client.update_bid.assert_not_called()


def test_legacy_unknown_submission_blocks_retry(bidding):
    sessions, client = bidding
    with sessions() as db:
        db.add(AuditLog(action="create_bid", entity_id=123, status="success_without_local_bid_id"))
        db.commit()
        with pytest.raises(ValueError, match="reconciliation"):
            asyncio.run(submit(db))
    client.create_bid.assert_not_called()
