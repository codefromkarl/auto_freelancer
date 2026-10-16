"""Read-only provider observations, separate from the durable submission ledger."""
from datetime import datetime, timezone
from decimal import Decimal
import math
import json

from sqlalchemy import func

from config import settings
from database.models import AuditLog, Bid, Project
from services.freelancer_client import get_freelancer_client
from services.scoring_policy import object_value

ACTION = 'bid_outcome_observation'


def latest_observations(db):
    latest = db.query(func.max(AuditLog.id)).filter_by(action=ACTION, entity_type='bid').group_by(
        AuditLog.entity_id).subquery()
    return {row.entity_id: object_value(row.response_data) or {} for row in
            db.query(AuditLog).filter(AuditLog.id.in_(latest.select())).all()}


def _thread_project(thread):
    context = thread.get('context')
    if isinstance(context, dict) and context.get('type') == 'project':
        return context.get('id')
    if thread.get('context_type') == 'project' and isinstance(context, int):
        return context
    return thread.get('project_id')


def _error_reason(exc):
    code = getattr(exc, 'status_code', None)
    return f'http_{code}' if code else type(exc).__name__


async def _responses(client, projects):
    owners = {p.freelancer_id: p.owner_id for p in projects}
    result = {pid: {'state': 'unknown', 'reason': 'customer_identity_unknown'} for pid in owners}
    try:
        threads = await client.get_project_threads(list(owners))
        by_thread = {}
        complete = len(threads) < 50
        for thread in threads:
            pid = _thread_project(thread)
            tid = thread.get('id')
            if pid not in owners or isinstance(tid, bool) or not isinstance(tid, int) or tid <= 0:
                complete = False
                continue
            by_thread[tid] = pid
        readable_threads = [tid for tid, pid in by_thread.items() if owners[pid]]
        senders = list({owners[pid] for tid, pid in by_thread.items() if tid in readable_threads})
        messages = await client.get_inbound_messages(readable_threads, senders) if readable_threads else []
        complete = complete and len(messages) < 50
        observed = {}
        for message in messages:
            pid = by_thread.get(message.get('thread_id'))
            if pid not in owners or message.get('from_user') != owners[pid] or not message.get('id'):
                complete = False
                continue
            observed[pid] = {'state': 'observed', 'last_message_at': message.get('date')}
        for pid in owners:
            has_thread = pid in by_thread.values()
            if has_thread and not owners[pid]:
                continue  # A conversation is not proof that its sender is the customer.
            result[pid] = observed.get(pid, {'state': 'none_observed' if complete else 'unknown',
                                          'reason': None if complete else 'partial_message_observation'})
    except Exception as exc:
        for pid in owners:
            result[pid] = {'state': 'unknown', 'reason': _error_reason(exc)}
    return result


async def sync_bid_outcomes(db, client=None, batch_size=50):
    if not 1 <= batch_size <= 50:
        raise ValueError('Outcome observation batch must be 1–50')
    previous = latest_observations(db)
    rows = db.query(Bid, Project).join(Project, Bid.project_id == Project.id).filter(
        Bid.bidder_id == int(settings.FREELANCER_USER_ID)).all()
    # Observe never-checked/oldest records first so histories larger than a batch rotate.
    rows.sort(key=lambda pair: (previous.get(pair[0].freelancer_bid_id, {}).get('checked_at') or '', pair[0].id))
    rows = rows[:batch_size]
    if not rows:
        return {'checked': 0, 'states': {}, 'responses': 0, 'unknown': 0}
    client = client or get_freelancer_client()
    checked_at = datetime.now(timezone.utc).isoformat()
    bid_error = None
    try:
        remote = await client.get_bid_outcomes([bid.freelancer_bid_id for bid, _ in rows])
        by_id = {item.get('id'): item for item in remote}
        if len(by_id) != len(remote):
            raise ValueError('Duplicate remote bid IDs')
    except Exception as exc:
        by_id = {}
        bid_error = _error_reason(exc)
    # A supplier-level rejection stops further GETs for this observation batch.
    responses = ({p.freelancer_id: {'state': 'unknown', 'reason': bid_error} for _, p in rows}
                 if bid_error else await _responses(client, [p for _, p in rows]))
    states = {}
    response_count = 0
    for bid, project in rows:
        record = {'checked_at': checked_at, 'bid_id': bid.freelancer_bid_id,
                  'project_id': project.freelancer_id, 'state': 'unknown',
                  'reason': bid_error or 'bid_not_returned', 'exact_readback': False}
        remote_bid = by_id.get(bid.freelancer_bid_id)
        if remote_bid:
            amount = remote_bid.get('amount')
            amount_matches = (not isinstance(amount, bool) and isinstance(amount, (int, float))
                              and math.isfinite(amount) and Decimal(str(amount)) == bid.amount)
            exact = (remote_bid.get('project_id') == bid.project_freelancer_id
                     and str(remote_bid.get('bidder_id')) == str(bid.bidder_id)
                     and amount_matches
                     and remote_bid.get('period') == bid.period
                     and remote_bid.get('description') == bid.description)
            record['exact_readback'] = exact
            if exact:
                status = {k: remote_bid.get(k) for k in ('frontend_bid_status', 'award_status', 'retracted')}
                record['remote_status'] = status
                if status['retracted'] is True:
                    state = 'withdrawn'
                elif isinstance(status['award_status'], str) and status['award_status'] in {'awarded', 'accepted'}:
                    state = 'awarded'
                elif status['frontend_bid_status'] == 'active' and status['retracted'] is False:
                    state = 'active'
                elif isinstance(status['frontend_bid_status'], str) and status['frontend_bid_status'] in {'closed', 'cancelled', 'inactive', 'rejected'}:
                    state = 'inactive'
                else:
                    state = 'unknown'
                record.update(state=state, reason=None if state != 'unknown' else 'remote_status_unknown')
            else:
                record['reason'] = 'receipt_mismatch'
        response = responses[project.freelancer_id]
        old_response = previous.get(bid.freelancer_bid_id, {}).get('customer_response') or {}
        # A previously observed inbound message is a historical fact, even when
        # the latest page is empty/partial. Do not claim the current GET succeeded.
        if old_response.get('state') == 'observed' and response['state'] != 'observed':
            response = {**response, 'previously_observed_at': old_response.get('previously_observed_at')
                        or previous[bid.freelancer_bid_id]['checked_at']}
        record['customer_response'] = response
        response_count += int(response['state'] == 'observed' or bool(response.get('previously_observed_at')))
        states[record['state']] = states.get(record['state'], 0) + 1
        db.add(AuditLog(action=ACTION, entity_type='bid', entity_id=bid.freelancer_bid_id,
                       status='success' if record['state'] != 'unknown' else 'error',
                       response_data=json.dumps(record, ensure_ascii=False)))
    from services.workflow_service import event
    event(db, 'outcome_tracking', 'observed', count=len(rows), details={'states': states})
    db.commit()
    return {'checked': len(rows), 'states': states, 'responses': response_count, 'unknown': states.get('unknown', 0)}


def outcome_summary(db, limit=50):
    observations = latest_observations(db)
    rows = db.query(Bid, Project).join(Project, Bid.project_id == Project.id).filter(
        Bid.bidder_id == int(settings.FREELANCER_USER_ID)).order_by(Bid.created_at.desc(), Bid.id.desc()).all()
    counts = {'submitted': len(rows), 'active': 0, 'awarded': 0, 'withdrawn': 0,
              'inactive': 0, 'unknown': 0, 'responses': 0}
    data = []
    for bid, project in rows:
        observation = observations.get(bid.freelancer_bid_id, {})
        state = observation.get('state', 'unknown')
        counts[state] += 1
        response = observation.get('customer_response') or {'state': 'unknown', 'reason': 'not_checked'}
        counts['responses'] += int(response['state'] == 'observed' or bool(response.get('previously_observed_at')))
        if len(data) < limit:
            data.append({'project_id': project.freelancer_id, 'title': project.title,
                         'bid_id': bid.freelancer_bid_id, 'amount': float(bid.amount),
                         'currency': project.currency_code, 'days': bid.period,
                         'state': state, 'reason': observation.get('reason', 'not_checked'),
                         'checked_at': observation.get('checked_at'), 'customer_response': response})
    return {'counts': counts, 'rows': data}
