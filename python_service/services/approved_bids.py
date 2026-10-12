"""Prepare immutable bid snapshots; every automatic submission needs a QQ approval."""
from __future__ import annotations

import asyncio
import json
import math
import time
import hashlib

from config import settings
from database.models import Project
from services import bid_service
from services.freelancer_client import get_freelancer_client, FreelancerAPIError
from services.project_service import _apply_project_fields, project_material_fields
from services.proposal_service import get_proposal_service
from services.qqbot_service import QQBotConfig
from services.qqbot_store import QQBotStore, canonical_hash
from services.proposal_competition import (ensure_competitor_context, load_competitor_context,
    evaluate_proposal_competition, POLICY_VERSION)
from utils.currency_converter import get_currency_converter


def project_version(project: Project) -> str:
    return canonical_hash(project_material_fields(project))


def risk_review(project: Project) -> tuple[bool, list[str]]:
    try:
        owner = json.loads(project.owner_info) if isinstance(project.owner_info, str) else project.owner_info
    except ValueError:
        owner = None
    if not isinstance(owner, dict) or not owner:
        return True, ['客户资料未知，需人工核对付款验证、历史及交付范围']
    status = owner.get('status') if isinstance(owner.get('status'), dict) else {}
    payment = owner.get('payment_verified', status.get('payment_verified'))
    if payment is False:
        raise ValueError('客户明确未完成付款验证，暂不准备自动提交候选')
    unknown = payment is not True
    return unknown, ['客户付款验证未确认'] if unknown else []


def validate_terms(project: Project, amount: float, period: int) -> tuple[float, list[str]]:
    if not isinstance(period, int) or isinstance(period, bool) or not 1 <= period <= 365:
        raise ValueError('工期必须在 1–365 天之间')
    rate = get_currency_converter().get_rate_sync(project.currency_code or 'USD')
    if rate is None or not math.isfinite(rate) or rate <= 0:
        raise ValueError('报价币种汇率尚未核实')
    usd = amount * rate
    if not math.isfinite(usd) or not 5 <= usd <= settings.BID_MAX_AMOUNT_USD:
        raise ValueError('报价超出受控提交金额范围')
    hours = project.estimated_hours
    if hours is not None and (isinstance(hours, bool) or not isinstance(hours, int) or hours <= 0):
        raise ValueError("估算工时必须是正整数")
    if hours and hours > settings.BID_MAX_ESTIMATED_HOURS:
        raise ValueError('估算工时超过受控提交上限')
    if hours and period * 6 < hours:
        raise ValueError('所选工期无法覆盖当前估算工时')
    notes = []
    if not hours:
        notes.append('估算工时未知，需人工确认工作量与交付周期')
    elif (usd-max(usd*0.1, 5)) / hours < settings.BID_MIN_NET_HOURLY_USD:
        raise ValueError('按普通固定价费用估算的净时薪低于配置下限')
    if project.type_id != 1:
        raise ValueError('当前受控投标只支持已确认的 fixed 项目')
    return usd, notes


async def prepare_bid(db, project_id: int, amount: float, period: int,
                      description=None, amount_currency=None, store=None) -> dict:
    config = QQBotConfig.from_env()
    config.require_target()
    if not config.approvers:
        raise ValueError('QQ 审批者 OpenID 尚未配置')
    project = db.query(Project).filter_by(freelancer_id=project_id).first()
    if project is None:
        raise ValueError('项目不在本地数据库中')
    from services import workflow_service as workflow
    queue_row = workflow.require_preparable(db, project)
    native = bid_service._resolve_submission_amount(project, amount, amount_currency)
    usd, notes = validate_terms(project, native, period)
    _, risks = risk_review(project)
    # Until all platform eligibility fields are authoritative, require an operator
    # to review the dashboard/profile/bid quota rather than treating absence as success.
    review_required = True
    notes.append('账号资料完整度与剩余投标额度需人工核对；执行前会再次核验账号及技能')
    notes.append('净时薪按普通 fixed 费用估算，不含税费、特殊项目收费和接口成本')
    state = store or QQBotStore(config.state_path)
    version = project_version(project)
    context = await ensure_competitor_context(db, project)
    # Reuse an unexpired snapshot; avoid paying for a new draft every polling cycle.
    for old in state.list_active(limit=100):
        p = old['payload']
        if ((queue_row is None or queue_row.approval_id == old['id'])
                and p['project_id'] == project_id and p['project_version'] == version
                and p['amount'] == native and p['period'] == period
                and p['qq_app_id'] == config.app_id and p['qq_target_id'] == config.target_id
                and p['qq_target_type'] == config.target_type
                and p['account_id'] == settings.FREELANCER_USER_ID
                and p.get("workflow_context_hash", workflow.digest([])) == workflow.context_hash(project)
                and p['estimated_hours'] == project.estimated_hours
                and p['review_notes'] == risks+notes
                and p.get('competition_review',{}).get('policy_version') == POLICY_VERSION
                and p.get('competition_review',{}).get('context_digest') == context['digest']
                and (p['competition_review']['benchmark']['status'] != 'ready'
                     or p['competition_review']['benchmark']['valid_until'] > time.time())
                and (description is None or p['description'] == description)):
            workflow.mark_prepared(db, project, old["id"])
            db.commit()
            return old
    if not description:
        generated = await get_proposal_service().generate_proposal(project,
            score_data={'suggested_bid': native, 'estimated_hours': project.estimated_hours, 'period': period},
            db=db, competition_context=context)
        if not generated.get('success') or generated.get('validation_passed') is not True:
            raise ValueError('最终提案生成或校验未通过')
        description = generated.get('proposal')
    if len(description or '') > 1200:
        raise ValueError('最终文案过长，无法在 QQ 展示完整审批内容；请缩短后重新准备')
    valid, reason = bid_service.check_content_risk(description or '', project, native)
    if not valid:
        raise ValueError(f'最终提案未通过：{reason}')
    review = evaluate_proposal_competition(project.to_dict(), description, native, period, context)
    if review['blocking_issues']:
        raise ValueError('竞标评估未通过：'+'；'.join(review['blocking_issues']))
    payload = {'project_id': project_id, 'title': project.title, 'project_version': version,
        'amount': native, 'amount_usd': usd, 'currency': project.currency_code or 'USD',
        'period': period, 'description': description, 'account_id': settings.FREELANCER_USER_ID,
        'estimated_hours': project.estimated_hours,
        'review_required': review_required, 'review_notes': risks+notes,
        'competition_review': review, 'workflow_context_hash': workflow.context_hash(project),
        'qq_target_type': config.target_type, 'qq_target_id': config.target_id, 'qq_app_id': config.app_id}
    ttl = 1800
    if context['status'] == 'ready':
        ttl = min(ttl, max(1, context['valid_until']-time.time()))
    # Validate the complete notification before saving a candidate that cannot be reviewed.
    from services.qqbot_events import preview_text
    preview = {'payload':payload,'id':'0'*16,'digest':'0'*64,'expires_at':time.time()+ttl}
    if len(preview_text(preview)) > 1800:
        raise ValueError('完整提案与竞标摘要超过 QQ 长度限制，请缩短后重新准备')
    snapshot = state.create(payload,ttl=ttl)
    project.ai_proposal_draft = description
    workflow.mark_prepared(db, project, snapshot["id"])
    from database.models import AuditLog
    db.add(AuditLog(action='proposal_evaluation',entity_type='project',entity_id=project_id,
        response_data=json.dumps(review,ensure_ascii=False),status=review['status']))
    db.commit()
    return snapshot


async def submit_approved_bid(db, approval_id: str, store=None) -> dict:
    if not settings.BID_SUBMISSION_ENABLED:
        raise ValueError('真实投标开关未开启；批准记录不会自动触发提交')
    config = QQBotConfig.from_env()
    state = store or QQBotStore(config.state_path)
    record = state.get(approval_id)
    payload = record['payload']
    _validate_frozen_review(payload)
    if record['actor'] not in config.approvers or record['scope'] != config.target_type or record['target'] != config.target_id:
        raise ValueError('审批者或接收对象已改变，需要重新批准')
    if payload['qq_app_id'] != config.app_id or payload['account_id'] != settings.FREELANCER_USER_ID:
        raise ValueError('机器人或投标账号已改变，需要重新批准')
    project = db.query(Project).filter_by(freelancer_id=payload['project_id']).first()
    if project is None or project_version(project) != payload['project_version']:
        raise ValueError('项目内容或预算已变化，需要重新准备和批准')
    from services import workflow_service as workflow
    queue_row = workflow.require_preparable(db, project)
    if queue_row is not None and queue_row.approval_id != approval_id:
        raise ValueError("队列决定或候选已变化，旧批准不能重新使用")
    if payload.get("workflow_context_hash", workflow.digest([])) != workflow.context_hash(project):
        raise ValueError("澄清信息已变化，需要重新准备和批准")
    validate_terms(project, payload['amount'], payload['period'])
    current_context = load_competitor_context(db, project)
    benchmark = payload['competition_review']['benchmark']
    if ((benchmark['status'] == 'ready' or current_context['status'] == 'ready')
            and current_context['digest'] != payload['competition_review']['context_digest']):
        raise ValueError('竞标对比数据已变化或失效，需要重新准备和批准')
    # Reserve approval and daily attempt BEFORE any external side effect.
    state.claim(approval_id, settings.BID_MAX_DAILY_ATTEMPTS)
    workflow.event(db, "submission", "attempted", project_id=project.freelancer_id,
                   key=f"attempted:{approval_id}")
    db.commit()
    try:
        client = get_freelancer_client()
        remote = await client.get_project(project.freelancer_id,
            project_details={'full_description': True, 'job_details': True})
        if remote.get('id') != project.freelancer_id:
            raise ValueError('远端项目标识不完整')
        _apply_project_fields(project, remote)
        if project_version(project) != payload['project_version']:
            raise ValueError('远端需求或预算已变化，需要重新批准')
        current_review, _ = risk_review(project)
        if not remote.get('owner_info'):
            current_review = True
        if current_review and not record['risk_reviewed']:
            raise ValueError('最新客户资料不足，需要显式人工风险复核')
        from freelancersdk.resources.users.users import get_self
        account = await asyncio.to_thread(get_self, client.session, {'jobs': True, 'status': True})
        if str(account.get('id')) != settings.FREELANCER_USER_ID:
            raise ValueError('Token 对应账号与配置不一致')
        own_jobs = {j.get('id') if isinstance(j, dict) else j for j in account.get('jobs') or []}
        required = {j.get('id') if isinstance(j, dict) else j for j in remote.get('jobs') or []}
        if not own_jobs or not required or not (own_jobs & required):
            raise ValueError('账号技能资格未通过')
        status = account.get('status') or {}
        if isinstance(status, dict) and status.get('email_verified') is False:
            raise ValueError('账号邮箱尚未验证')
        if payload['review_required'] and not record['risk_reviewed']:
            raise ValueError('尚未完成未知资料的人工风险复核')
        if record['expires_at'] <= time.time():
            raise ValueError('远端核验期间批准已过期，需要重新批准')
        _validate_frozen_review(payload)
        fresh_config = QQBotConfig.from_env()
        if (record['actor'] not in fresh_config.approvers or fresh_config.target_id != record['target']
                or fresh_config.target_type != record['scope'] or fresh_config.app_id != payload['qq_app_id']):
            raise ValueError('核验期间审批权限或接收对象已变化')
        # Submit EXACTLY the approved text and terms; never generate another draft.
        result = await bid_service.create_bid(db, project.freelancer_id, payload['amount'],
            payload['period'], payload['description'], amount_currency=payload['currency'])
    except FreelancerAPIError as exc:
        state.finish(approval_id, 'outcome_unknown' if exc.status_code == 409 else 'blocked', str(exc))
        _record_execution_result(db, workflow, payload['project_id'], approval_id,
            'outcome_unknown' if exc.status_code == 409 else 'failed', type(exc).__name__)
        raise
    except Exception as exc:
        state.finish(approval_id, 'blocked', str(exc))
        _record_execution_result(db, workflow, payload['project_id'], approval_id, 'failed', type(exc).__name__)
        raise
    state.finish(approval_id, 'submitted')
    _record_execution_result(db, workflow, payload["project_id"], approval_id, "submitted")
    return result


def _record_execution_result(db, workflow, project_id, approval_id, outcome, reason=None):
    # Submission ledger and QQ outcome are already durable. Observability failures
    # must not turn confirmed success into an apparently retryable failure.
    try:
        db.rollback()
        workflow.event(db, "submission", outcome, project_id=project_id, reason=reason,
                       key=f"submission:{approval_id}:{outcome}")
        workflow.reconcile(db)
        db.commit()
    except Exception:
        db.rollback()
        import logging
        logging.getLogger(__name__).warning("Submission workflow observation could not be saved")


def _validate_frozen_review(payload):
    review = payload.get('competition_review') or {}
    if (review.get('policy_version') != POLICY_VERSION or review.get('blocking_issues')
            or review.get('text_digest') != hashlib.sha256(payload['description'].encode()).hexdigest()
            or review.get('amount') != payload['amount'] or review.get('period') != payload['period']):
        raise ValueError('缺少当前版本的最终标书竞标评估，需要重新准备和批准')
    benchmark = review.get('benchmark') or {}
    if benchmark.get('currency') != payload['currency']:
        raise ValueError('竞标评估币种与批准内容不一致')
    if benchmark.get('status') == 'ready' and (benchmark.get('valid_until') or 0) <= time.time():
        raise ValueError('竞标评估已过期，需要重新准备和批准')


def check_request(approval_id, project_id, amount, period, description, amount_currency=None):
    payload = QQBotStore(QQBotConfig.from_env().state_path).get(approval_id)['payload']
    if project_id != payload['project_id'] or period != payload['period']:
        raise ValueError('提交参数与批准的项目或工期不一致')
    currency = amount_currency or payload['currency']
    expected = payload['amount_usd'] if currency == 'USD' else payload['amount']
    if currency not in {'USD', payload['currency']} or not math.isfinite(amount) or abs(amount-expected) > 0.001:
        raise ValueError('提交金额或币种与批准内容不一致')
    if description is not None and description != payload['description']:
        raise ValueError('提交文案与批准内容不一致')
