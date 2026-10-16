"""Freeze final bids and execute either QQ approval or an explicit system decision."""
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
                      description=None, amount_currency=None, store=None, *, competitive_quote=False) -> dict:
    config = QQBotConfig.from_env()
    automatic = settings.BID_APPROVAL_MODE == 'automatic'
    if not automatic:
        config.require_target()
    if not automatic and not config.approvers:
        raise ValueError('QQ 审批者 OpenID 尚未配置')
    project = db.query(Project).filter_by(freelancer_id=project_id).first()
    if project is None:
        raise ValueError('项目不在本地数据库中')
    from services import workflow_service as workflow
    queue_row = workflow.require_preparable(db, project)
    native = bid_service._resolve_submission_amount(project, amount, amount_currency)
    context = await ensure_competitor_context(db, project)
    if automatic and competitive_quote:
        from services.automatic_bid_policy import resolve_quote
        selected = resolve_quote(project, native, context)
        if abs(selected-native) >= 0.005:
            _reprice_score(db, project, selected, context)
            native = selected
    usd, notes = validate_terms(project, native, period)
    _, risks = risk_review(project)
    if automatic and risks:
        risks = ['客户付款验证信息未知；仅按小额、短工时规则竞标，不代表付款已验证']
    # Until all platform eligibility fields are authoritative, require an operator
    # to review the dashboard/profile/bid quota rather than treating absence as success.
    review_required = not automatic
    if not automatic:
        notes.append('账号资料完整度与剩余投标额度需人工核对；执行前会再次核验账号及技能')
    notes.append('净时薪按普通 fixed 费用估算，不含税费、特殊项目收费和接口成本')
    state = store or QQBotStore(config.state_path)
    version = project_version(project)
    authorization = None
    if automatic:
        from services.automatic_bid_policy import validate_candidate
        authorization = validate_candidate(db, project, native, period, context)
    # Reuse an unexpired snapshot; avoid paying for a new draft every polling cycle.
    for old in state.list_active(limit=100):
        p = old['payload']
        if ((queue_row is None or queue_row.approval_id == old['id'])
                and p['project_id'] == project_id and p['project_version'] == version
                and p['amount'] == native and p['period'] == period
                and p.get('authorization') == authorization
                and (automatic or (p['qq_app_id'] == config.app_id and p['qq_target_id'] == config.target_id
                     and p['qq_target_type'] == config.target_type))
                and p['account_id'] == settings.FREELANCER_USER_ID
                and p.get("workflow_context_hash", workflow.digest([])) == workflow.context_hash(project)
                and p['estimated_hours'] == project.estimated_hours
                and p['review_notes'] == risks+notes
                and p.get('competition_review',{}).get('policy_version') == POLICY_VERSION
                and p.get('competition_review',{}).get('context_digest') == context['digest']
                and (p['competition_review']['benchmark']['status'] != 'ready'
                     or p['competition_review']['benchmark']['valid_until'] > time.time())
                and (description is None or p['description'] == description)):
            workflow.mark_prepared(db, project, old["id"], automatic=automatic)
            db.commit()
            return old
    if not description:
        generated = await get_proposal_service().generate_proposal(project,
            score_data={'suggested_bid': native, 'estimated_hours': project.estimated_hours, 'period': period,
                'scope_assumptions': json.loads(project.score_metadata or '{}').get('scope_assumptions', [])},
            db=db, competition_context=context)
        if not generated.get('success') or generated.get('validation_passed') is not True:
            from services.proposal_service import ProposalPreparationError
            raise ProposalPreparationError(generated.get('validation_issues') or
                                           [generated.get('error') or '未返回通过校验的最终提案'])
        description = generated.get('proposal')
    if not automatic and len(description or '') > 1200:
        raise ValueError('最终文案过长，无法在 QQ 展示完整审批内容；请缩短后重新准备')
    valid, reason = bid_service.check_content_risk(description or '', project, native)
    if not valid:
        raise ValueError(f'最终提案未通过：{reason}')
    review = evaluate_proposal_competition(project.to_dict(), description, native, period, context)
    if review['blocking_issues']:
        raise ValueError('竞标评估未通过：'+'；'.join(review['blocking_issues']))
    if automatic:
        authorization = validate_candidate(db, project, native, period, context, review)
    payload = {'project_id': project_id, 'title': project.title, 'project_version': version,
        'amount': native, 'amount_usd': usd, 'currency': project.currency_code or 'USD',
        'period': period, 'description': description, 'account_id': settings.FREELANCER_USER_ID,
        'estimated_hours': project.estimated_hours,
        'review_required': review_required, 'review_notes': risks+notes,
        'competition_review': review, 'workflow_context_hash': workflow.context_hash(project),
        'qq_target_type': config.target_type, 'qq_target_id': config.target_id, 'qq_app_id': config.app_id}
    if automatic:
        payload['authorization'] = authorization
    ttl = 1800
    if context['status'] == 'ready':
        ttl = min(ttl, max(1, context['valid_until']-time.time()))
    # Validate the complete notification before saving a candidate that cannot be reviewed.
    from services.qqbot_events import preview_text
    preview = {'payload':payload,'id':'0'*16,'digest':'0'*64,'expires_at':time.time()+ttl}
    if not automatic and len(preview_text(preview)) > 1800:
        raise ValueError('完整提案与竞标摘要超过 QQ 长度限制，请缩短后重新准备')
    snapshot = state.create(payload,ttl=ttl)
    project.ai_proposal_draft = description
    workflow.mark_prepared(db, project, snapshot["id"], automatic=automatic)
    from database.models import AuditLog
    db.add(AuditLog(action='proposal_evaluation',entity_type='project',entity_id=project_id,
        response_data=json.dumps(review,ensure_ascii=False),status=review['status']))
    db.commit()
    return snapshot


async def submit_approved_bid(db, approval_id: str, store=None) -> dict:
    import os
    if os.environ.get('BIDMASTER_LOCAL_MODE') == '1':
        from desktop.configuration import ConfigStore
        from desktop.paths import data_directory
        from desktop.licensing import require_platform_access
        require_platform_access(data_directory(), ConfigStore().load().installation_id, 'platform_bid')
    if not settings.BID_SUBMISSION_ENABLED:
        raise ValueError('真实投标开关未开启；批准记录不会自动触发提交')
    config = QQBotConfig.from_env()
    state = store or QQBotStore(config.state_path)
    record = state.get(approval_id)
    payload = record['payload']
    automatic = payload.get('authorization', {}).get('mode') == 'automatic'
    if automatic != (settings.BID_APPROVAL_MODE == 'automatic'):
        raise ValueError('投标授权模式已变化，需要重新准备')
    _validate_frozen_review(payload)
    if not automatic and (record['actor'] not in config.approvers or record['scope'] != config.target_type or record['target'] != config.target_id):
        raise ValueError('审批者或接收对象已改变，需要重新批准')
    if (not automatic and payload['qq_app_id'] != config.app_id) or payload['account_id'] != settings.FREELANCER_USER_ID:
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
    if automatic:
        _validate_automatic_snapshot(db, project, payload, current_context)
        # This is a system policy decision, never a fabricated QQ/user approval.
        if record['state'] == 'auto_pending':
            record = state.authorize_automatic(approval_id, payload['authorization']['policy_hash'])
            workflow.event(db, 'authorization', 'automatic', project_id=project.freelancer_id,
                details=payload['authorization'], key=f'automatic:{approval_id}')
        if (record['actor'] != 'automatic_policy' or record['scope'] != 'automatic'
                or record['target'] != settings.FREELANCER_USER_ID):
            raise ValueError('系统决策来源无效')
    # Reserve approval and daily attempt BEFORE any external side effect.
    state.claim(approval_id, settings.BID_MAX_DAILY_ATTEMPTS, automatic=automatic)
    workflow.event(db, "submission", "attempted", project_id=project.freelancer_id,
                   key=f"attempted:{approval_id}")
    db.commit()
    try:
        client = get_freelancer_client()
        remote = await client.get_project(project.freelancer_id,
            project_details={'full_description': True, 'job_details': True},
            **({'user_details': {'user_details': True, 'user_status': True, 'user_employer_reputation': True}}
               if automatic else {}))
        if remote.get('id') != project.freelancer_id:
            raise ValueError('远端项目标识不完整')
        from services.scoring_policy import scoring_inputs
        previous_inputs = scoring_inputs(project)
        previous_metadata = json.loads(project.score_metadata or '{}')
        previous_scored_at = project.scored_at
        _apply_project_fields(project, remote)
        if project_version(project) != payload['project_version']:
            raise ValueError('远端需求或预算已变化，需要重新批准')
        if automatic and not project.score_metadata:
            current_inputs = scoring_inputs(project)
            changes = {key for key in previous_inputs if previous_inputs.get(key)!=current_inputs.get(key)}
            if changes == {'bid_stats'}:
                _refresh_market_score(db, project, previous_metadata, previous_scored_at)
        current_review, _ = risk_review(project)
        if not remote.get('owner_info'):
            current_review = True
        if automatic and current_review and settings.BID_AUTO_REQUIRE_VERIFIED_CLIENT_PAYMENT:
            raise ValueError('最新客户付款资料不足，自动暂缓')
        if automatic and not remote.get('owner_info'):
            # Never preserve a cached positive verification when this read lacks it.
            project.owner_info = None
        if current_review and not record['risk_reviewed'] and not automatic:
            raise ValueError('最新客户资料不足，需要显式人工风险复核')
        from freelancersdk.resources.users.users import get_self
        account = await asyncio.to_thread(get_self, client.session,
            {'jobs': True, 'status': True, 'balance_details': True, 'membership_details': True}
            if automatic else {'jobs': True, 'status': True})
        if str(account.get('id')) != settings.FREELANCER_USER_ID:
            raise ValueError('Token 对应账号与配置不一致')
        own_jobs = {j.get('id') if isinstance(j, dict) else j for j in account.get('jobs') or []}
        required = {j.get('id') if isinstance(j, dict) else j for j in remote.get('jobs') or []}
        if not own_jobs or not required or not (own_jobs & required):
            raise ValueError('账号技能资格未通过')
        status = account.get('status') or {}
        if isinstance(status, dict) and status.get('email_verified') is False:
            raise ValueError('账号邮箱尚未验证')
        if automatic:
            from services.automatic_bid_policy import validate_account
            validate_account(account, settings.FREELANCER_USER_ID)
            _validate_automatic_snapshot(db, project, payload, current_context)
            remote_bids = await client.get_project_bids(project.freelancer_id)
            if any(str(b.get('bidder_id')) == settings.FREELANCER_USER_ID
                   and not b.get('retracted') for b in remote_bids):
                raise ValueError('平台已有本账号投标，禁止重复提交')
        if payload['review_required'] and not record['risk_reviewed']:
            raise ValueError('尚未完成未知资料的人工风险复核')
        if record['expires_at'] <= time.time():
            raise ValueError('远端核验期间批准已过期，需要重新批准')
        _validate_frozen_review(payload)
        fresh_config = QQBotConfig.from_env()
        if automatic:
            _validate_automatic_snapshot(db, project, payload, load_competitor_context(db, project))
        elif (record['actor'] not in fresh_config.approvers or fresh_config.target_id != record['target']
                or fresh_config.target_type != record['scope'] or fresh_config.app_id != payload['qq_app_id']):
            raise ValueError('核验期间审批权限或接收对象已变化')
        if not settings.BID_SUBMISSION_ENABLED:
            raise ValueError('核验期间真实投标开关已关闭')
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


def _validate_automatic_snapshot(db, project, payload, context):
    from services.automatic_bid_policy import validate_candidate, policy_hash
    if (payload['account_id'] != settings.FREELANCER_USER_ID
            or context.get('digest') != payload['competition_review'].get('context_digest')):
        raise ValueError('投标账号或竞标对比数据已变化，需要重新准备')
    if payload.get('authorization', {}).get('policy_hash') != policy_hash():
        raise ValueError('自动策略已变化，需要重新准备')
    current = validate_candidate(db, project, payload['amount'], payload['period'],
                                 context, payload['competition_review'])
    if payload.get('authorization') != current:
        raise ValueError('自动策略或评分内容已变化，需要重新准备')


def _reprice_score(db, project, native, context):
    """Recompute program economics with the same real model assessment; no fake model call."""
    from services.scoring_policy import object_value, evaluate_result, resolve_weights, policy_signature, score_is_current
    from services.llm_scoring_service import get_scoring_service
    if not score_is_current(project, policy_signature(db)):
        raise ValueError('调整报价前需要有效的原始模型评分')
    previous = object_value(project.score_metadata)
    rate = get_currency_converter().get_rate_sync(project.currency_code)
    usd = round(native*rate, 2)
    result = {'dimension_scores': previous['model_dimensions'], 'estimated_hours':project.estimated_hours,
        'suggested_bid':usd, 'reason':previous.get('model_reason') or project.ai_reason or '完整范围报价重算',
        'clarification_questions':previous.get('clarification_questions',[]),
        'scope_assumptions':previous.get('scope_assumptions',[]),
        'recommendation':previous.get('recommendation','consider'), 'provider_model':previous.get('models')}
    calculated = evaluate_result(project, result, get_scoring_service()._prepare_project_payload(project),
                                resolve_weights(db), policy_signature(db))
    if previous.get('model_assessment'):
        calculated['metadata']['model_assessment'] = previous['model_assessment']
    calculated['metadata']['pricing_adjustment'] = {
        'source':'competitive_pricing', 'model_quote_usd':previous.get('pricing_adjustment',{}).get('model_quote_usd',previous['quote_usd']),
        'quote_usd':usd, 'native_quote':native, 'market_digest':context['digest']}
    project.ai_score = calculated['score']
    project.ai_reason = calculated['reason']
    project.suggested_bid = usd
    project.hourly_rate = calculated['hourly_rate']
    project.score_metadata = json.dumps(calculated['metadata'],ensure_ascii=False)
    from database.models import AuditLog
    db.add(AuditLog(action='competitive_pricing', entity_type='project', entity_id=project.freelancer_id,
        response_data=json.dumps(calculated['metadata']['pricing_adjustment'],ensure_ascii=False),status='success'))
    db.flush()


def _refresh_market_score(db, project, previous, scored_at):
    from services.scoring_policy import evaluate_result, resolve_weights, policy_signature
    from services.llm_scoring_service import get_scoring_service
    result = {'dimension_scores':previous['model_dimensions'], 'estimated_hours':previous['estimated_hours'],
        'suggested_bid':previous['quote_usd'], 'reason':previous.get('model_reason') or '保留技术与工时评估，重算实时竞争指标',
        'provider_model':previous.get('models'), 'recommendation':previous.get('recommendation','consider'),
        'clarification_questions':previous.get('clarification_questions',[]),
        'scope_assumptions':previous.get('scope_assumptions',[])}
    computed = evaluate_result(project,result,get_scoring_service()._prepare_project_payload(project),
                               resolve_weights(db),policy_signature(db))
    if previous.get('model_assessment'):
        computed['metadata']['model_assessment'] = previous['model_assessment']
    if previous.get('pricing_adjustment'):
        computed['metadata']['pricing_adjustment']=previous['pricing_adjustment']
    computed['metadata']['market_refresh']={'source':'program','old_input_hash':previous['input_hash'],
                                          'model_calls':0,'original_scored_at_preserved':True}
    project.ai_score=computed['score'];project.ai_reason=computed['reason']
    project.estimated_hours=previous['estimated_hours'];project.suggested_bid=previous['quote_usd']
    project.hourly_rate=computed['hourly_rate'];project.scored_at=scored_at
    project.score_metadata=json.dumps(computed['metadata'],ensure_ascii=False)
    from database.models import AuditLog
    db.add(AuditLog(action='live_market_score_refresh',entity_type='project',entity_id=project.freelancer_id,
        response_data=json.dumps(computed['metadata']['market_refresh']),status='success'))
    db.flush()


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
