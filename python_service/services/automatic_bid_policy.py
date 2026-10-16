"""Evidence required for system decisions; no synthetic operator approval."""
import math

from config import settings
from services.scoring_policy import object_value, policy_signature, score_is_current
from services.qqbot_store import canonical_hash

VERSION = 'automatic-v2'


def assessment_digest(metadata):
    # Freeze technical judgment and quoted whole scope; live auction statistics are
    # recomputed programmatically and cannot change the model's underlying assessment.
    keys = ('source','version','policy_hash','model_dimensions','estimated_hours','quote_usd',
            'models','recommendation','clarification_questions','scope_assumptions')
    bound = {key:metadata.get(key) for key in keys}
    bound['model_dimensions'] = {key:float(value) for key,value in (metadata.get('model_dimensions') or {}).items()}
    bound['recommendation'] = metadata.get('recommendation', 'consider')
    bound['scope_assumptions'] = metadata.get('scope_assumptions', [])
    bound['clarification_questions'] = metadata.get('clarification_questions', [])
    return canonical_hash(bound)


def policy_hash():
    return canonical_hash({'version': VERSION, 'minimum_score': settings.BID_MIN_AUTO_SCORE,
        'minimum_net_hourly': settings.BID_MIN_NET_HOURLY_USD,
        'maximum_hours': settings.BID_MAX_ESTIMATED_HOURS,
        'maximum_amount_usd': settings.BID_MAX_AMOUNT_USD,
        'maximum_median_premium': 0.2,
        'verified_payment_required': settings.BID_AUTO_REQUIRE_VERIFIED_CLIENT_PAYMENT,
        'unknown_client_maximum_usd': settings.BID_AUTO_UNKNOWN_CLIENT_MAX_USD,
        'unknown_client_maximum_hours': settings.BID_AUTO_UNKNOWN_CLIENT_MAX_HOURS})


def validate_local_candidate(project, amount, period):
    """Shared non-network gates; applied before candidate truncation and drafting."""
    from services.approved_bids import validate_terms, risk_review
    metadata = object_value(project.score_metadata) or {}
    if metadata.get('clarification_questions') or metadata.get('candidate_blocked'):
        raise ValueError('自动候选仍有未解决问题或阻断记录')
    if metadata.get('recommendation', 'consider') == 'reject':
        raise ValueError('模型明确建议排除该任务')
    dimensions = metadata.get('model_dimensions') or {}
    if any(isinstance(dimensions.get(key), bool) or not isinstance(dimensions.get(key), (int, float))
           or not math.isfinite(dimensions[key]) or dimensions[key] < value
           for key, value in {'tech':7, 'clarity':7, 'risk':5}.items()):
        raise ValueError('技术匹配、范围清晰度或交付风险未通过')
    if str(project.status or '').lower() not in {'active', 'open', 'open_for_bidding'}:
        raise ValueError('自动候选当前状态不可投标')
    usd, notes = validate_terms(project, amount, period)
    if notes or not project.estimated_hours:
        raise ValueError('自动提交要求明确的完整交付工时')
    unknown, _ = risk_review(project)
    if unknown:
        if settings.BID_AUTO_REQUIRE_VERIFIED_CLIENT_PAYMENT:
            raise ValueError('客户付款验证未知，自动暂缓')
        if usd > settings.BID_AUTO_UNKNOWN_CLIENT_MAX_USD or project.estimated_hours > settings.BID_AUTO_UNKNOWN_CLIENT_MAX_HOURS:
            raise ValueError('未知客户仅允许配置范围内的小额、短工时投标')
    maximum = float(project.budget_maximum or project.budget_minimum or 0)
    if not math.isfinite(maximum) or maximum <= 0 or amount > maximum:
        raise ValueError('自动报价超出客户预算范围')
    return unknown


def validate_candidate(db, project, amount, period, context, review=None):
    from services import workflow_service as workflow
    if settings.BID_APPROVAL_MODE != 'automatic':
        raise ValueError('自动提交模式未开启')
    workflow.require_preparable(db, project)
    if not score_is_current(project, policy_signature(db)) or project.ai_score < settings.BID_MIN_AUTO_SCORE:
        raise ValueError(f'自动提交要求当前有效模型评分至少 {settings.BID_MIN_AUTO_SCORE:g} 分')
    unknown = validate_local_candidate(project, amount, period)
    if context.get('status') != 'ready' or not context.get('complete'):
        raise ValueError('自动提交需要当前完整的公开竞标资料')
    median = context.get('price', {}).get('median')
    usable_prices = context.get('price_count', 0) >= 3
    if usable_prices and (not isinstance(median, (int, float)) or not math.isfinite(median) or median <= 0):
        raise ValueError('竞标报价中位数无效')
    if usable_prices and amount > median * 1.2:
        raise ValueError('报价高于竞标中位数超过 20%，自动暂缓')
    if review is not None:
        if review.get('blocking_issues'):
            raise ValueError('最终标书竞标评估存在硬阻断')
        from services.proposal_competition import required_delivery_issues
        issues = required_delivery_issues(review)
        if issues:
            raise ValueError('；'.join(issues))
    return {'mode': 'automatic', 'source': 'automatic_policy', 'version': VERSION,
            'policy_hash': policy_hash(), 'score_digest': assessment_digest(object_value(project.score_metadata) or {}),
            'client_payment': 'unknown' if unknown else 'verified',
            'market_sample': 'priced' if usable_prices else 'insufficient_sample'}


def resolve_quote(project, proposed, context):
    """Choose a competitive quote only when it still pays for the whole estimated scope."""
    from services.approved_bids import risk_review
    from utils.currency_converter import get_currency_converter
    rate = get_currency_converter().get_rate_sync(project.currency_code)
    if rate is None or not math.isfinite(rate) or rate <= 0 or not project.estimated_hours:
        raise ValueError('报价所需汇率或完整工时未知')
    unknown, _ = risk_review(project)
    cap = min(float(project.budget_maximum or project.budget_minimum or 0), settings.BID_MAX_AMOUNT_USD/rate)
    if unknown and not settings.BID_AUTO_REQUIRE_VERIFIED_CLIENT_PAYMENT:
        cap = min(cap, settings.BID_AUTO_UNKNOWN_CLIENT_MAX_USD/rate)
    target = min(proposed, cap)
    median = context.get('price', {}).get('median')
    if context.get('status') == 'ready' and context.get('price_count', 0) >= 3 and median:
        cap = min(cap, median*1.2)
        target = min(target, median)
    net = settings.BID_MIN_NET_HOURLY_USD * project.estimated_hours
    minimum_usd = net+5 if net+5 <= 50 else net/0.9
    minimum = math.ceil(minimum_usd/rate*100-1e-9)/100
    selected = max(minimum, round(target, 2))
    if cap <= 0 or selected > cap + 1e-9:
        raise ValueError('客户预算/竞标价格无法覆盖完整交付的最低净收益')
    return selected


def validate_account(account, account_id):
    if str(account.get('id')) != account_id:
        raise ValueError('Token 对应账号与配置不一致')
    if any(account.get(key) for key in ('suspended', 'closed', 'limited_account')):
        raise ValueError('账号受限，不能自动投标')
    status = account.get('status') or {}
    for key in ('email_verified', 'phone_verified', 'profile_complete'):
        if status.get(key) is not True:
            raise ValueError(f'账号资格未确认：{key}')
    balances = account.get('account_balances') or {}
    remaining = balances.get('bids_remaining')
    if (isinstance(remaining, bool) or not isinstance(remaining, (int, float))
            or not math.isfinite(remaining) or remaining < 1):
        raise ValueError('平台剩余投标额度不足或未知')
    balance = balances.get('equivalent_amount')
    if ((account.get('primary_currency') or {}).get('code') != 'USD'
            or isinstance(balance, bool) or not isinstance(balance, (int, float))
            or not math.isfinite(balance) or balance < 20):
        raise ValueError('账号可用余额或余额币种未通过自动核验')
