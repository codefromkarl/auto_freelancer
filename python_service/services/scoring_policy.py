"""Shared, auditable scoring and freshness contracts for API and CLI."""
import hashlib
import json
import math
from datetime import datetime, timezone, timedelta

from config import settings

SCORING_VERSION = "2026-10-14-v6"
DIMENSIONS = ("budget_efficiency", "competition", "clarity", "customer", "tech", "risk")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    default=str, allow_nan=False).encode()).hexdigest()


def object_value(raw):
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw) if raw else None
    except (ValueError, TypeError):
        return None


def finite_number(value, *, positive=False):
    if isinstance(value, bool) or value is None:
        raise ValueError("Expected a finite numeric value")
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        raise ValueError("Expected a finite positive value" if positive else "Expected a finite value")
    return number


def validate_result(result):
    if not isinstance(result, dict):
        raise ValueError("Scoring output must be an object")
    # The model's optional total is never authoritative, but malformed totals fail closed.
    if "score" in result:
        score = finite_number(result["score"])
        if not 0 <= score <= 10:
            raise ValueError("Score must be in 0–10")
    dimensions = result.get("dimension_scores")
    if not isinstance(dimensions, dict) or set(dimensions) != set(DIMENSIONS):
        raise ValueError("All six scoring dimensions are required")
    parsed = {key: finite_number(dimensions[key]) for key in DIMENSIONS}
    if any(not 0 <= score <= 10 for score in parsed.values()):
        raise ValueError("Dimension scores must be in 0–10")
    hours = finite_number(result.get("estimated_hours"), positive=True)
    if not hours.is_integer():
        raise ValueError("Estimated hours must be a positive integer")
    quote = finite_number(result.get("suggested_bid"), positive=True)
    if result.get("hourly_rate") is not None:
        finite_number(result["hourly_rate"], positive=True)
    if not str(result.get("reason") or "").strip():
        raise ValueError("A scoring explanation is required")
    questions = result.get("clarification_questions", [])
    if not isinstance(questions, list) or len(questions) > 5 or any(not isinstance(q, str) or not 1 <= len(q.strip()) <= 500 for q in questions):
        raise ValueError("Clarification questions must be at most five nonempty strings")
    recommendation = result.get('recommendation', 'consider')
    if recommendation not in {'consider', 'reject'}:
        raise ValueError('Recommendation must be consider or reject')
    assumptions = result.get('scope_assumptions', [])
    if (not isinstance(assumptions, list) or len(assumptions)>5
            or any(not isinstance(v,str) or not 1<=len(v.strip())<=500 for v in assumptions)):
        raise ValueError('Scope assumptions must be at most five concise strings')
    return {**result, "clarification_questions": list(dict.fromkeys(q.strip() for q in questions)),
            'recommendation': recommendation, 'scope_assumptions': assumptions,
            "dimension_scores": parsed, "estimated_hours": int(hours),
            "suggested_bid": quote}


def resolve_weights(db=None):
    weights = dict(settings.scoring_rules["weights"])
    if db is not None and hasattr(db, "query"):
        from database.models import ScoringRule
        for rule in db.query(ScoringRule).filter(ScoringRule.is_active.is_(True)).all():
            name = "tech" if rule.name == "tech_match" else rule.name
            if name in DIMENSIONS:
                weights[name] = rule.weight
    if set(weights) != set(DIMENSIONS):
        raise ValueError("Scoring weights must define all six dimensions")
    weights = {key: finite_number(value) for key, value in weights.items()}
    total = sum(weights.values())
    if any(value < 0 for value in weights.values()) or not math.isfinite(total) or total <= 0:
        raise ValueError("Scoring weights must be nonnegative with a positive total")
    return {key: value / total for key, value in weights.items()}


def policy_signature(db=None):
    prompt = None
    if db is not None and hasattr(db, "query"):
        from database.models import PromptTemplate
        template = db.query(PromptTemplate).filter(
            PromptTemplate.category == "scoring", PromptTemplate.is_active.is_(True)
        ).order_by(PromptTemplate.created_at.desc(), PromptTemplate.id.desc()).first()
        prompt = template.content if template else None
    providers = settings.get_enabled_llm_providers()
    mode = settings.LLM_SCORING_MODE.lower()
    if mode == "single":
        providers = providers[:1]
    return digest({
        "version": SCORING_VERSION, "weights": resolve_weights(db), "db_prompt": prompt,
        "models": [{k: p.get(k) for k in ("name", "model", "base_url")} for p in providers],
        "mode": mode, "profile": settings.BID_SELECTION_PROFILE,
        "skills": settings.RESUME_SKILL_MAPPINGS, "default_skills": settings.DEFAULT_SKILLS,
        "minimum_net_hourly": settings.BID_MIN_NET_HOURLY_USD,
        "maximum_hours": settings.BID_MAX_ESTIMATED_HOURS,
    })


def scoring_inputs(project):
    from services.project_service import project_material_fields
    from services.workflow_service import clarification_context
    return {**project_material_fields(project), "clarifications": clarification_context(project),
            "bid_stats": object_value(project.bid_stats),
            "owner_info": object_value(project.owner_info),
            "submitdate": project.submitdate}



def assessment_payload(payload):
    """Only scope/reputation context reaches the model; live metrics are computed."""
    stable = {key: value for key, value in payload.items()
              if key not in {"bid_stats", "bid_stats_currency", "age_hours"}}
    owner = object_value(stable.get("owner_info"))
    if isinstance(owner, dict):
        owner = {key: value for key, value in owner.items() if key != "payment_verified"}
        if isinstance(owner.get("status"), dict):
            owner["status"] = {key: value for key, value in owner["status"].items()
                               if key != "payment_verified"}
        # Missing and payment-only customer records convey the same model context.
        owner = {key: value for key, value in owner.items() if value != {}}
    stable["owner_info"] = owner or None
    return stable


def reusable_assessment(project, payload, prompt_hash, signature, now=None):
    metadata = object_value(getattr(project, "score_metadata", None)) or {}
    saved = metadata.get("model_assessment") or {}
    if (metadata.get("source") != "llm" or metadata.get("version") != SCORING_VERSION
            or metadata.get("policy_hash") != signature or saved.get("input_hash") != digest(assessment_payload(payload))
            or saved.get("prompt_hash") != prompt_hash):
        return None
    try:
        evaluated_at = datetime.fromisoformat(saved["evaluated_at"])
        if evaluated_at.tzinfo is None:
            return None
        age = (now or datetime.now(timezone.utc)) - evaluated_at
        if not timedelta(0) <= age < timedelta(hours=settings.SCORING_TTL_HOURS):
            return None
        result = validate_result(saved["result"])
        return {**result, "_evaluated_at": saved["evaluated_at"]}
    except (KeyError, ValueError, TypeError, OverflowError):
        return None


def bind_assessment(metadata, result, payload, prompt_hash):
    """Persist the actual model result, never reset its clock on program refresh."""
    metadata["model_assessment"] = {
        "input_hash": digest(assessment_payload(payload)), "prompt_hash": prompt_hash,
        "evaluated_at": result.get("_evaluated_at") or datetime.now(timezone.utc).isoformat(),
        "result": {key: value for key, value in validate_result(result).items()
                   if not key.startswith("_") and key not in {"project_id", "metadata"}},
    }


def score_is_current(project, signature=None, now=None):
    metadata = object_value(getattr(project, "score_metadata", None))
    scored_at = getattr(project, "scored_at", None)
    if not isinstance(metadata, dict) or not scored_at or project.ai_score is None:
        return False
    if metadata.get("source") != "llm" or metadata.get("version") != SCORING_VERSION:
        return False
    signature = signature or policy_signature()
    now = now or datetime.now(timezone.utc)
    scored_at = scored_at.replace(tzinfo=timezone.utc) if scored_at.tzinfo is None else scored_at
    if not timedelta(0) <= now - scored_at < timedelta(hours=settings.SCORING_TTL_HOURS):
        return False
    try:
        if metadata.get("model_assessment"):
            evaluated_at = datetime.fromisoformat(metadata["model_assessment"]["evaluated_at"])
            if evaluated_at.tzinfo is None or not timedelta(0) <= now - evaluated_at < timedelta(hours=settings.SCORING_TTL_HOURS):
                return False
        return (metadata.get("policy_hash") == signature
                and metadata.get("input_hash") == digest(scoring_inputs(project))
                and metadata.get("total") == project.ai_score
                and metadata.get("estimated_hours") == project.estimated_hours
                and abs(float(metadata.get("quote_usd")) - float(project.suggested_bid)) < 0.011)
    except (KeyError, ValueError, TypeError):
        return False


def competition_score(bid_stats, age_hours=None):
    """Continuous congestion preference; missing data stays neutral, never zero bids."""
    raw = object_value(bid_stats)
    count = raw.get("bid_count") if isinstance(raw, dict) else None
    if count is None:
        return 5.0
    try:
        count = finite_number(count)
    except (ValueError, TypeError):
        return 5.0
    if count < 0:
        return 5.0
    score = 10.0 / (1.0 + math.log1p(count) / 3.0)
    if age_hours is not None:
        try:
            score *= 1.0 / (1.0 + max(0, finite_number(age_hours)) / 168.0)
        except (ValueError, TypeError):
            pass
    return round(score, 4)


def economic_score(net_hourly):
    return round(min(10.0, max(0.0, net_hourly) / settings.BID_MIN_NET_HOURLY_USD * 8.0), 4)


def evaluate_result(project, result, payload, weights, signature):
    result = validate_result(result)
    if project.type_id not in (1, 2):
        raise ValueError("Billing type must be confirmed before scoring")
    maximum = payload.get("budget_maximum")
    quote = result["suggested_bid"]
    if maximum is None or finite_number(maximum, positive=True) <= 0:
        raise ValueError("Budget and exchange rate must be known")
    if quote > maximum * 1.2:
        raise ValueError("Suggested quote exceeds the project budget limit")
    hours = result["estimated_hours"]
    # Hourly quotes are per-hour; fixed quotes cover the whole scope.
    fee = max(quote * 0.1, 5) if project.type_id == 1 else quote * 0.1
    gross_hourly = quote / hours if project.type_id == 1 else quote
    net_hourly = (quote - fee) / hours if project.type_id == 1 else quote - fee
    dimensions = dict(result["dimension_scores"])
    dimensions["budget_efficiency"] = economic_score(net_hourly)
    dimensions["competition"] = competition_score(project.bid_stats, payload.get("age_hours"))
    unknown = []
    owner = object_value(project.owner_info)
    status = owner.get("status") if isinstance(owner, dict) else None
    status = status if isinstance(status, dict) else {}
    payment = owner.get("payment_verified", status.get("payment_verified")) if isinstance(owner, dict) else None
    if payment is not True and payment is not False:
        unknown.append("customer")
        dimensions["customer"] = 5.0
        dimensions["risk"] = min(5.0, dimensions["risk"])
    elif payment is False:
        dimensions["customer"] = min(3.0, dimensions["customer"])
        dimensions["risk"] = min(3.0, dimensions["risk"])
    if not isinstance(payload.get("bid_stats"), dict) or payload["bid_stats"].get("bid_count") is None:
        unknown.append("competition")
    if payload.get("age_hours") is None:
        unknown.append("publication_time")
    total = round(sum(dimensions[key] * weights[key] for key in DIMENSIONS), 2)
    metadata = {
        "source": "llm", "version": SCORING_VERSION, "policy_hash": signature,
        "input_hash": digest(scoring_inputs(project)), "weights": weights,
        "model_dimensions": result["dimension_scores"], "dimensions": dimensions,
        "total": total, "estimated_hours": hours, "quote_usd": quote,
        "gross_hourly_usd": gross_hourly, "net_hourly_usd": net_hourly,
        "estimated_fee_usd": fee, "unknown": unknown,
        "models": result.get("provider_model"), "model_score": result.get("score"),
        "clarification_questions": result["clarification_questions"],
        'recommendation': result['recommendation'], 'scope_assumptions': result['scope_assumptions'],
        'model_reason': result['reason'],
    }
    explanation = (f"{result['reason']} [计算净时薪 {net_hourly:.2f} USD/h；"
                   f"加权分 {total:.2f}；未知资料：{', '.join(unknown) or '无'}]")
    return {**result, "score": total, "hourly_rate": gross_hourly,
            "reason": explanation, "metadata": metadata}
