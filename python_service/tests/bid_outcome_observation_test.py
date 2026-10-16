import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database.connection import Base
from database.models import Project, Bid, BidSubmission, AuditLog
from services import bid_outcome_service as outcomes
from services.freelancer_client import FreelancerClient, FreelancerAPIError


@pytest.fixture
def observation_db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        p = Project(freelancer_id=123, title='Python API', owner_id=777, currency_code='USD')
        db.add(p); db.flush()
        b = Bid(freelancer_bid_id=456, project_id=p.id, project_freelancer_id=123,
                bidder_id=999, amount=250, period=3, description='Frozen full proposal', status='active')
        reservation = BidSubmission(project_freelancer_id=123, status='submitted',
                                    freelancer_bid_id=456, amount=250, currency_code='USD', period=3)
        db.add_all([b, reservation]); db.commit()
        yield db
    engine.dispose()


def client(**changes):
    bid = {'id': 456, 'project_id': 123, 'bidder_id': 999, 'amount': 250, 'period': 3,
           'description': 'Frozen full proposal', 'frontend_bid_status': 'active',
           'retracted': False, 'award_status': None}
    return SimpleNamespace(get_bid_outcomes=AsyncMock(return_value=[{**bid, **changes}]),
                           get_project_threads=AsyncMock(return_value=[]),
                           get_inbound_messages=AsyncMock(return_value=[]))


def test_exact_active_receipt_and_empty_customer_query_do_not_change_ledger(observation_db):
    db = observation_db; remote = client()
    summary = asyncio.run(outcomes.sync_bid_outcomes(db, remote))
    assert summary == {'checked': 1, 'states': {'active': 1}, 'responses': 0, 'unknown': 0}
    row = outcomes.outcome_summary(db)['rows'][0]
    assert row['state'] == 'active' and row['customer_response']['state'] == 'none_observed'
    assert isinstance(row['amount'], float) and json.dumps(row)
    assert row['checked_at'].endswith('+00:00')
    assert db.query(Bid).one().status == 'active'
    assert db.query(BidSubmission).one().status == 'submitted'
    remote.get_inbound_messages.assert_not_awaited()


@pytest.mark.parametrize('change', [
    {'bidder_id': 1000}, {'project_id': 321}, {'amount': 251}, {'period': 4},
    {'description': 'Different proposal'},
])
def test_mismatched_remote_identity_or_terms_are_unknown(observation_db, change):
    db = observation_db
    asyncio.run(outcomes.sync_bid_outcomes(db, client(**change)))
    row = outcomes.outcome_summary(db)['rows'][0]
    assert row['state'] == 'unknown' and row['reason'] == 'receipt_mismatch'
    assert db.query(BidSubmission).one().freelancer_bid_id == 456


@pytest.mark.parametrize('code', [404, 429, 503])
def test_read_failure_is_unknown_not_lost_or_resubmittable(observation_db, code):
    db = observation_db; remote = client()
    asyncio.run(outcomes.sync_bid_outcomes(db, remote))
    remote.get_bid_outcomes.side_effect = FreelancerAPIError('Sensitive provider text', code)
    asyncio.run(outcomes.sync_bid_outcomes(db, remote))
    row = outcomes.outcome_summary(db)['rows'][0]
    assert row['state'] == 'unknown' and row['reason'] == f'http_{code}'
    assert db.query(BidSubmission).one().status == 'submitted'
    assert 'Sensitive' not in db.query(AuditLog).order_by(AuditLog.id.desc()).first().response_data
    assert remote.get_project_threads.await_count == 1  # no follow-on GET after provider rejection


def test_missing_bid_does_not_preserve_stale_active_status(observation_db):
    db = observation_db; remote = client()
    asyncio.run(outcomes.sync_bid_outcomes(db, remote))
    remote.get_bid_outcomes.return_value = []
    asyncio.run(outcomes.sync_bid_outcomes(db, remote))
    assert outcomes.outcome_summary(db)['counts']['active'] == 0
    assert outcomes.outcome_summary(db)['rows'][0]['reason'] == 'bid_not_returned'


@pytest.mark.parametrize('changes,state', [
    ({'award_status': 'awarded'}, 'awarded'), ({'award_status': 'accepted'}, 'awarded'),
    ({'retracted': True}, 'withdrawn'), ({'frontend_bid_status': 'closed'}, 'inactive'),
    ({'frontend_bid_status': 'unrecognized'}, 'unknown'), ({'retracted': None}, 'unknown'),
])
def test_only_explicit_provider_state_determines_current_outcome(observation_db, changes, state):
    asyncio.run(outcomes.sync_bid_outcomes(observation_db, client(**changes)))
    assert outcomes.outcome_summary(observation_db)['rows'][0]['state'] == state
    assert observation_db.query(Bid).one().status == 'active'


def test_actual_client_message_is_tracked_without_body_or_marking_read(observation_db):
    db = observation_db; remote = client()
    remote.get_project_threads.return_value = [{'id': 100, 'context': {'type': 'project', 'id': 123}}]
    remote.get_inbound_messages.return_value = [
        {'id': 2, 'thread_id': 100, 'from_user': 777, 'date': 100, 'message': 'Private customer body'}]
    asyncio.run(outcomes.sync_bid_outcomes(db, remote))
    row = outcomes.outcome_summary(db)['rows'][0]
    assert row['customer_response']['state'] == 'observed'
    assert outcomes.outcome_summary(db)['counts']['responses'] == 1
    assert 'Private customer body' not in db.query(AuditLog).one().response_data
    remote.get_inbound_messages.assert_awaited_once_with([100], [777])
    # Empty/failed later reads cannot erase the historical observation.
    remote.get_project_threads.side_effect = FreelancerAPIError('Unavailable', 503)
    asyncio.run(outcomes.sync_bid_outcomes(db, remote))
    row = outcomes.outcome_summary(db)['rows'][0]
    assert row['customer_response']['state'] == 'unknown'
    assert row['customer_response']['previously_observed_at']
    assert outcomes.outcome_summary(db)['counts']['responses'] == 1


def test_unknown_customer_and_partial_thread_page_do_not_claim_no_response(observation_db):
    db = observation_db; remote = client()
    remote.get_project_threads.return_value = [{'id': n + 1, 'project_id': 123} for n in range(50)]
    asyncio.run(outcomes.sync_bid_outcomes(db, remote))
    assert outcomes.outcome_summary(db)['rows'][0]['customer_response']['state'] == 'unknown'
    db.query(Project).one().owner_id = None; db.commit()
    asyncio.run(outcomes.sync_bid_outcomes(db, remote))
    assert outcomes.outcome_summary(db)['rows'][0]['customer_response']['reason'] == 'customer_identity_unknown'


def test_message_from_wrong_sender_is_not_customer_response(observation_db):
    remote = client()
    remote.get_project_threads.return_value = [{'id': 100, 'project_id': 123}]
    remote.get_inbound_messages.return_value = [{'id': 2, 'thread_id': 100, 'from_user': 999}]
    asyncio.run(outcomes.sync_bid_outcomes(observation_db, remote))
    assert outcomes.outcome_summary(observation_db)['counts']['responses'] == 0
    assert outcomes.outcome_summary(observation_db)['rows'][0]['customer_response']['state'] == 'unknown'


def test_oldest_observation_rotates_batches_and_other_accounts_stay_out(observation_db):
    db = observation_db; remote = client()
    p = db.query(Project).one()
    db.add(Bid(freelancer_bid_id=457, project_id=p.id, project_freelancer_id=123,
               bidder_id=999, amount=250, period=3, description='Second history', status='active'))
    db.add(Bid(freelancer_bid_id=458, project_id=p.id, project_freelancer_id=123,
               bidder_id=1000, amount=250, period=3, description='Other account', status='active'))
    db.commit()
    asyncio.run(outcomes.sync_bid_outcomes(db, remote, batch_size=1))
    asyncio.run(outcomes.sync_bid_outcomes(db, remote, batch_size=1))
    assert [c.args[0] for c in remote.get_bid_outcomes.call_args_list] == [[456], [457]]
    assert outcomes.outcome_summary(db)['counts']['submitted'] == 2


def test_observation_client_uses_only_bounded_gets(monkeypatch):
    import services.freelancer_client as module
    calls = []
    class HTTP:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def get(self, url, **kwargs):
            calls.append((url, kwargs))
            return SimpleNamespace(status_code=200, json=lambda: {'status': 'success', 'result': {'bids': []}})
    obj = FreelancerClient(); obj._rate_limiter.acquire = AsyncMock()
    monkeypatch.setattr(module._requests, 'Session', HTTP)
    assert asyncio.run(obj.get_bid_outcomes([456])) == []
    assert calls[0][0].endswith('/api/projects/0.1/bids/')
    assert calls[0][1]['params'] == {'bids[]': [456], 'limit': 50, 'offset': 0}
    assert calls[0][1]['allow_redirects'] is False and calls[0][1]['timeout'] == (5, 15)
    with pytest.raises(ValueError): asyncio.run(obj.get_bid_outcomes([]))
    with pytest.raises(ValueError): asyncio.run(obj.get_bid_outcomes(list(range(1, 52))))
    assert len(calls) == 1


def test_fractional_provider_amount_matches_exact_decimal_currency(observation_db):
    from decimal import Decimal
    db = observation_db
    db.query(Bid).one().amount = Decimal('17150.40'); db.commit()
    asyncio.run(outcomes.sync_bid_outcomes(db, client(amount=17150.4)))
    assert outcomes.outcome_summary(db)['rows'][0]['state'] == 'active'


def test_empty_project_thread_query_is_observable_even_when_owner_is_unknown(observation_db):
    db = observation_db; remote = client()
    db.query(Project).one().owner_id = None; db.commit()
    asyncio.run(outcomes.sync_bid_outcomes(db, remote))
    remote.get_project_threads.assert_awaited_once_with([123])
    assert outcomes.outcome_summary(db)['rows'][0]['customer_response']['state'] == 'none_observed'
