from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
import re
import logging

logger = logging.getLogger(__name__)

from database.models import Bid, Project, AuditLog
from services.freelancer_client import get_freelancer_client, FreelancerAPIError
from services.proposal_service import get_proposal_service, ProposalService
from utils.currency_converter import get_currency_converter

BIDDABLE_REMOTE_STATUSES = {"open", "active", "open_for_bidding"}


def _coerce_int(value: Any) -> Optional[int]:
    """Best-effort int coercion for API fields."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        raw = value.strip()
        if raw.isdigit():
            return int(raw)
    return None


def _extract_nested(data: Any, path: Tuple[str, ...]) -> Any:
    current = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _extract_bid_ids(
    result: Dict[str, Any],
    fallback_bidder_id: Optional[int] = None,
) -> Tuple[Optional[int], Optional[int]]:
    """Extract bid_id and bidder_id from multiple API response shapes."""
    bid_id_paths = [
        ("bid_id", "id"),
        ("bid_id",),
        ("id",),
        ("bid", "id"),
        ("result", "id"),
        ("result", "bid_id"),
        ("result", "bid", "id"),
        ("result", "bid_id", "id"),
    ]
    bidder_id_paths = [
        ("bidder_id", "id"),
        ("bidder_id",),
        ("bidder", "id"),
        ("result", "bidder_id"),
        ("result", "bidder_id", "id"),
        ("result", "bidder", "id"),
        ("result", "bid", "bidder_id"),
        ("result", "bid", "bidder_id", "id"),
    ]

    bid_id = None
    for path in bid_id_paths:
        value = _coerce_int(_extract_nested(result, path))
        if value is not None and value > 0:
            bid_id = value
            break

    bidder_id = None
    for path in bidder_id_paths:
        value = _coerce_int(_extract_nested(result, path))
        if value is not None and value > 0:
            bidder_id = value
            break

    if bidder_id is None and fallback_bidder_id and fallback_bidder_id > 0:
        bidder_id = fallback_bidder_id

    return bid_id, bidder_id


def _is_same_amount(value_a: float, value_b: float, epsilon: float = 0.01) -> bool:
    return abs(float(value_a) - float(value_b)) <= epsilon


def _resolve_submission_amount(project: Project, amount: float) -> float:
    """Resolve outgoing bid amount in project's native currency.

    `project.suggested_bid` is stored in USD. When callers pass that value directly
    for non-USD projects, convert it back to project currency before submission.
    """
    project_currency = (project.currency_code or "USD").upper()
    if project_currency == "USD":
        return float(amount)

    suggested_bid_usd = float(project.suggested_bid) if project.suggested_bid is not None else None
    if suggested_bid_usd is None or not _is_same_amount(float(amount), suggested_bid_usd):
        return float(amount)

    converter = get_currency_converter()
    rate_to_usd = converter.get_rate_sync(project_currency)
    if rate_to_usd is None or rate_to_usd <= 0:
        raise ValueError(
            f"Cannot convert USD suggested bid to {project_currency}: missing exchange rate."
        )

    converted = round(float(amount) / rate_to_usd, 2)
    logger.info(
        "Converted suggested_bid from USD to project currency. project_id=%s amount_usd=%.2f %s=%.2f rate_to_usd=%s",
        project.freelancer_id,
        float(amount),
        project_currency,
        converted,
        rate_to_usd,
    )
    return converted


def check_content_risk(description: str, project: Project) -> Tuple[bool, str]:
    """
    检查投标内容的风险

    Delegates to DefaultProposalValidator for DRY compliance.
    Signature preserved for backward compatibility.

    返回: (是否允许, 风险原因)
    """
    from services.proposal_service import DefaultProposalValidator

    validator = DefaultProposalValidator(min_length=100, max_length=3000)
    project_dict = project.to_dict() if hasattr(project, "to_dict") else {
        "title": project.title,
        "description": project.description,
        "preview_description": getattr(project, "preview_description", ""),
        "budget_minimum": float(project.budget_minimum) if project.budget_minimum else None,
        "budget_maximum": float(project.budget_maximum) if project.budget_maximum else None,
        "currency_code": project.currency_code,
    }
    is_valid, issues = validator.validate(description, project_dict)
    if is_valid:
        return True, "通过"
    return False, "，".join(issues)


def _extract_remote_project_status(
    remote_project: Dict[str, Any],
) -> Tuple[str, Optional[str]]:
    """Extract normalized status/sub_status from different project payload shapes."""
    payload = remote_project
    if isinstance(payload, dict) and isinstance(payload.get("result"), dict):
        payload = payload["result"]
    if not isinstance(payload, dict):
        return "", None

    status = str(payload.get("status") or "").strip().lower()
    sub_status = payload.get("sub_status")
    sub_status_str = str(sub_status).strip().lower() if sub_status is not None else None
    return status, sub_status_str


async def validate_project_biddable_now(
    db: Session, project: Project
) -> Tuple[bool, str]:
    """
    Validate project status against live Freelancer API and sync local status.

    Fail-closed: if remote check fails, bidding should be blocked.
    """
    client = get_freelancer_client()
    try:
        remote = await client.get_project(project.freelancer_id)
    except Exception as exc:
        logger.error(
            "Remote project status check failed. project_id=%s error=%s",
            project.freelancer_id,
            exc,
        )
        return False, f"remote_status_check_failed: {exc}"

    status, sub_status = _extract_remote_project_status(remote if isinstance(remote, dict) else {})
    if status:
        project.status = status
    if isinstance(remote, dict):
        submitdate = remote.get("submitdate")
        if submitdate is not None:
            project.submitdate = str(submitdate)
    project.updated_at = datetime.utcnow()
    db.flush()  # Let the caller control commit/rollback boundary

    if status not in BIDDABLE_REMOTE_STATUSES:
        return False, f"remote_status={status or 'unknown'}, sub_status={sub_status or 'none'}"

    return True, "ok"


def _beautify_amount(amount: float, currency: str) -> float:
    """Make the bid amount look more 'human' by rounding to natural increments."""
    val = float(amount)
    currency = (currency or "USD").upper()
    
    # Large currencies like INR, JPY, IDR
    if val > 1000:
        # Round to nearest 50 or 100
        if val > 5000:
            return float(round(val / 100) * 100)
        return float(round(val / 50) * 50)
    
    # Medium currencies like USD, EUR, GBP
    if val > 100:
        return float(round(val / 10) * 10)
    
    # Small amounts
    if val > 20:
        return float(round(val / 5) * 5)
    
    return float(round(val))


async def create_bid(
    db: Session,
    project_id: int,
    amount: float,
    period: int,
    description: Optional[str] = None,
    skip_content_check: bool = False,
    validate_remote_status: bool = True,
) -> Dict[str, Any]:
    """
    Submit a bid to Freelancer and record it.
    """
    # 1. Check local project existence
    project = db.query(Project).filter_by(freelancer_id=project_id).first()
    if not project:
        raise ValueError(
            "Project not found in database. Please sync with Freelancer API first."
        )

    # 1b. Idempotency: reject duplicate bids for the same project
    existing_bid = db.query(Bid).filter_by(
        project_freelancer_id=project_id
    ).filter(
        Bid.status.in_(["active", "submitted", "submitted_remote_only"])
    ).first()
    if existing_bid:
        raise ValueError(
            f"Duplicate bid rejected: an active bid (id={existing_bid.freelancer_bid_id}) "
            f"already exists for project {project_id}."
        )

    if validate_remote_status:
        is_biddable_now, reason = await validate_project_biddable_now(db, project)
        if not is_biddable_now:
            raise ValueError(
                f"Project is not biddable now. {reason}"
            )

    resolved_amount = _resolve_submission_amount(project, amount)
    # Beautify the amount after conversion
    resolved_amount = _beautify_amount(resolved_amount, project.currency_code)

    # 1c. Bid amount range validation (convert to USD equivalent for non-USD currencies)
    ABS_MIN_AMOUNT_USD = 5.0
    ABS_MAX_AMOUNT_USD = 50000.0
    project_currency = (project.currency_code or "USD").upper()
    amount_for_validation = resolved_amount
    if project_currency != "USD":
        converter = get_currency_converter()
        rate_to_usd = converter.get_rate_sync(project_currency)
        if rate_to_usd and rate_to_usd > 0:
            amount_for_validation = resolved_amount * rate_to_usd
    if amount_for_validation < ABS_MIN_AMOUNT_USD or amount_for_validation > ABS_MAX_AMOUNT_USD:
        raise ValueError(
            f"Bid amount {resolved_amount:.2f} {project_currency} "
            f"(~${amount_for_validation:.2f} USD) is outside the absolute allowed range "
            f"(${ABS_MIN_AMOUNT_USD:.0f} - ${ABS_MAX_AMOUNT_USD:.0f} USD)."
        )
    if project.budget_minimum is not None and project.budget_maximum is not None:
        budget_min = float(project.budget_minimum)
        budget_max = float(project.budget_maximum)
        if budget_min > 0 and budget_max > 0:
            lower_bound = budget_min * 0.5
            upper_bound = budget_max * 1.5
            if resolved_amount < lower_bound or resolved_amount > upper_bound:
                raise ValueError(
                    f"Bid amount ${resolved_amount:.2f} is outside the acceptable range "
                    f"(${lower_bound:.2f} - ${upper_bound:.2f}) based on project budget "
                    f"${budget_min:.0f} - ${budget_max:.0f}."
                )

    # 2. Determine description (use AI draft from ProposalService if not provided)
    bid_description = description
    if not bid_description:
        # Check if project already has a draft from the scoring step
        if project.ai_proposal_draft:
            logger.info(f"Using pre-generated draft for project {project_id}")
            bid_description = project.ai_proposal_draft
        else:
            # Fallback: Generate now if missing
            try:
                proposal_service = get_proposal_service()
                # Pass the ALREADY RESOLVED and BEAUTIFIED amount to the proposal generator
                # Note: resolve_submission_amount returns project currency, but ProposalService expects USD or clarified currency.
                # However, for consistency, we pass the final numeric value.
                p_score_data = {
                    "suggested_bid": resolved_amount,
                    "estimated_hours": getattr(project, "estimated_hours", None)
                }
                proposal_result = await proposal_service.generate_proposal(project, score_data=p_score_data, db=db)
                if proposal_result.get("success"):
                    bid_description = proposal_result.get("proposal", "")
            except Exception as e:
                logger.warning(f"Failed to generate real-time proposal: {e}")
                bid_description = ""

    # 3. 检查投标内容风险（执行验证但不再阻塞投标）
    if not skip_content_check and bid_description:
        content_safe, risk_reason = check_content_risk(bid_description, project)
        if not content_safe:
            # 记录内容验证问题到审计日志，但【不再报错退出】
            audit = AuditLog(
                action="content_validation_warning",
                entity_type="bid",
                entity_id=project_id,
                request_data=f"description_length={len(bid_description)}",
                response_data=f"ISSUES: {risk_reason}",
                status="warning",
                error_message=risk_reason,
            )
            db.add(audit)
            db.commit()
            logger.warning(f"Project {project_id}: Bid proceeding with validation issues: {risk_reason}")

    if not bid_description:
        raise ValueError("Bid description is required and no AI draft is available.")

    # 4. Call External API
    client = get_freelancer_client()
    try:
        result = await client.create_bid(
            project_id=project_id,
            amount=resolved_amount,
            period=period,
            description=bid_description,
        )
    except FreelancerAPIError as e:
        # Log failure
        audit = AuditLog(
            action="create_bid",
            entity_type="bid",
            entity_id=project_id,  # Using project ID as proxy entity ID for failed bid
            request_data=f"amount={resolved_amount}, period={period}",
            response_data=e.message,
            status="error",
            error_message=e.message,
        )
        db.add(audit)
        db.commit()
        raise e

    fallback_bidder_id = _coerce_int(getattr(client, "user_id", None))
    bid_id, bidder_id = _extract_bid_ids(result or {}, fallback_bidder_id=fallback_bidder_id)

    # 5. Save to DB on success
    if bid_id is None:
        logger.warning(
            "Bid submitted remotely but bid_id missing in response; skip bid row insert. "
            "project_id=%s response=%s",
            project_id,
            result,
        )
        audit = AuditLog(
            action="create_bid",
            entity_type="bid",
            entity_id=project_id,
            request_data=f"amount={resolved_amount}, period={period}",
            response_data=str(result),
            status="success_without_local_bid_id",
        )
        db.add(audit)
        db.commit()
        return {
            "bid_id": None,
            "project_id": project_id,
            "amount": resolved_amount,
            "period": period,
            "description": bid_description,
            "status": "submitted_remote_only",
        }

    if bidder_id is None:
        raise ValueError(
            "Bid submitted but bidder_id missing in API response and no fallback user_id available."
        )

    bid = Bid(
        freelancer_bid_id=bid_id,
        project_id=project.id,
        project_freelancer_id=project_id,
        bidder_id=bidder_id,
        amount=resolved_amount,
        period=period,
        description=bid_description,
        status="active",
        submitdate=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    )
    db.add(bid)

    # Audit log
    audit = AuditLog(
        action="create_bid",
        entity_type="bid",
        entity_id=bid.freelancer_bid_id,
        request_data=f"amount={resolved_amount}, period={period}",
        response_data=str(result),
        status="success",
    )
    db.add(audit)
    db.commit()
    db.refresh(bid)

    return {
        "bid_id": bid.freelancer_bid_id,
        "project_id": project_id,
        "amount": resolved_amount,
        "period": period,
        "description": bid_description,
        "status": "submitted",
    }


def get_user_bids(
    db: Session, status: Optional[str] = None, limit: int = 50, offset: int = 0
) -> Dict[str, Any]:
    query = db.query(Bid)
    if status:
        query = query.filter(Bid.status == status)

    total = query.count()
    bids = query.order_by(Bid.created_at.desc()).offset(offset).limit(limit).all()

    return {"data": [bid.to_dict() for bid in bids], "total": total}


def get_bid_details(db: Session, bid_id: int) -> Optional[Dict[str, Any]]:
    bid = db.query(Bid).filter_by(freelancer_bid_id=bid_id).first()
    return bid.to_dict() if bid else None


async def update_bid(
    db: Session,
    bid_id: int,
    amount: Optional[float] = None,
    period: Optional[int] = None,
    description: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    client = get_freelancer_client()

    # Check existence first
    bid = db.query(Bid).filter_by(freelancer_bid_id=bid_id).first()
    if not bid:
        return None

    # Call API
    try:
        result = await client.update_bid(
            bid_id=bid_id, amount=amount, period=period, description=description
        )
    except FreelancerAPIError as e:
        audit = AuditLog(
            action="update_bid",
            entity_type="bid",
            entity_id=bid_id,
            request_data=f"update_failed",
            response_data=e.message,
            status="error",
            error_message=e.message,
        )
        db.add(audit)
        db.commit()
        raise e

    # Update DB
    if amount is not None:
        bid.amount = amount
    if period is not None:
        bid.period = period
    if description is not None:
        bid.description = description
    bid.updated_at = datetime.utcnow()

    audit = AuditLog(
        action="update_bid",
        entity_type="bid",
        entity_id=bid_id,
        request_data=f"amount={amount}, period={period}",
        response_data=str(result),
        status="success",
    )
    db.add(audit)
    db.commit()
    db.refresh(bid)

    return bid.to_dict()


async def retract_bid(db: Session, bid_id: int) -> bool:
    client = get_freelancer_client()

    try:
        result = await client.retract_bid(bid_id)
    except FreelancerAPIError as e:
        audit = AuditLog(
            action="retract_bid",
            entity_type="bid",
            entity_id=bid_id,
            request_data="",
            response_data=e.message,
            status="error",
            error_message=e.message,
        )
        db.add(audit)
        db.commit()
        raise e

    bid = db.query(Bid).filter_by(freelancer_bid_id=bid_id).first()
    if bid:
        bid.status = "withdrawn"
        bid.updated_at = datetime.utcnow()

        audit = AuditLog(
            action="retract_bid",
            entity_type="bid",
            entity_id=bid_id,
            request_data="",
            response_data=str(result),
            status="success",
        )
        db.add(audit)
        db.commit()
        return True

    return False
