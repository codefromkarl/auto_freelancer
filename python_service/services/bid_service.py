from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
import re
import logging
import math
from sqlalchemy.exc import IntegrityError
from config import settings

logger = logging.getLogger(__name__)

from database.models import Bid, BidSubmission, Project, AuditLog
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
        return int(value) if math.isfinite(value) and value.is_integer() else None
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


def _resolve_submission_amount(
    project: Project, amount: float, amount_currency: Optional[str] = None,
) -> float:
    """Amounts default to native currency; USD suggestions must be explicit."""
    project_currency = (project.currency_code or "USD").upper()
    source_currency = (amount_currency or project_currency).upper()
    if not math.isfinite(amount) or amount <= 0:
        raise ValueError("Bid amount must be finite and positive.")
    if source_currency == project_currency:
        return round(float(amount), 2)
    if source_currency != "USD":
        raise ValueError("Bid amount currency must be USD or the project's currency.")

    converter = get_currency_converter()
    rate_to_usd = converter.get_rate_sync(project_currency)
    if rate_to_usd is None or not math.isfinite(rate_to_usd) or rate_to_usd <= 0:
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


def check_content_risk(
    description: str, project: Project, expected_amount: Optional[float] = None,
) -> Tuple[bool, str]:
    """
    检查投标内容的风险

    Delegates to DefaultProposalValidator for DRY compliance.
    Signature preserved for backward compatibility.

    返回: (是否允许, 风险原因)
    """
    from services.proposal_service import DefaultProposalValidator

    validator = DefaultProposalValidator(
        min_length=settings.PROPOSAL_MIN_LENGTH,
        max_length=settings.PROPOSAL_MAX_LENGTH,
    )
    project_dict = project.to_dict() if hasattr(project, "to_dict") else {
        "title": project.title,
        "description": project.description,
        "preview_description": getattr(project, "preview_description", ""),
        "budget_minimum": float(project.budget_minimum) if project.budget_minimum else None,
        "budget_maximum": float(project.budget_maximum) if project.budget_maximum else None,
        "currency_code": project.currency_code,
    }
    if expected_amount is not None:
        project_dict["expected_bid_amount"] = expected_amount
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


async def create_bid(
    db: Session,
    project_id: int,
    amount: float,
    period: int,
    description: Optional[str] = None,
    amount_currency: Optional[str] = None,
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
    if not isinstance(period, int) or isinstance(period, bool) or not 1 <= period <= 365:
        raise ValueError("Bid period must be between 1 and 365 days.")
    submission = db.query(BidSubmission).filter_by(project_freelancer_id=project_id).first()
    if submission:
        raise ValueError(
            f"Submission already reserved for project {project_id} ({submission.status}); "
            "reconcile the remote outcome before retrying."
        )
    if project.status == "bid_submitted" or db.query(AuditLog).filter_by(
        action="create_bid", entity_id=project_id, status="success_without_local_bid_id",
    ).first():
        raise ValueError("Previous submission requires remote reconciliation before retrying.")

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

    resolved_amount = _resolve_submission_amount(project, amount, amount_currency)

    # 1c. Bid amount range validation (convert to USD equivalent for non-USD currencies)
    ABS_MIN_AMOUNT_USD = 5.0
    ABS_MAX_AMOUNT_USD = 50000.0
    project_currency = (project.currency_code or "USD").upper()
    amount_for_validation = resolved_amount
    if project_currency != "USD":
        converter = get_currency_converter()
        rate_to_usd = converter.get_rate_sync(project_currency)
        if rate_to_usd is None or not math.isfinite(rate_to_usd) or rate_to_usd <= 0:
            raise ValueError(f"Cannot validate amount: missing exchange rate for {project_currency}.")
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

    # 2. Generate a validated final proposal, rather than submitting an untyped cache draft.
    bid_description = description
    if not bid_description:
        proposal_result = await get_proposal_service().generate_proposal(
            project,
            score_data={"suggested_bid": resolved_amount, "estimated_hours": project.estimated_hours},
            db=db,
        )
        if not proposal_result.get("success") or proposal_result.get("validation_passed") is not True:
            raise ValueError("Final proposal generation/validation failed; submission blocked.")
        bid_description = proposal_result.get("proposal", "")
    if not bid_description:
        raise ValueError("Bid description is required and no AI draft is available.")
    content_safe, risk_reason = check_content_risk(bid_description, project, resolved_amount)
    if not content_safe:
        raise ValueError(f"Bid content validation failed: {risk_reason}")

    # Refresh after generation/approval, immediately before the submission reservation.
    is_biddable_now, reason = await validate_project_biddable_now(db, project)
    if not is_biddable_now:
        raise ValueError(f"Project is not biddable now. {reason}")

    # Commit the reservation BEFORE the external side effect. The unique key handles
    # multiple API workers and CLI processes; crashes leave a durable blocked row.
    submission = BidSubmission(
        project_freelancer_id=project_id, status="submitting", amount=resolved_amount,
        currency_code=project_currency, period=period,
    )
    db.add(submission)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("Concurrent/duplicate submission rejected; reconcile before retrying.") from exc

    # 4. Call External API
    client = get_freelancer_client()
    try:
        result = await client.create_bid(
            project_id=project_id,
            amount=resolved_amount,
            period=period,
            description=bid_description,
        )
    except Exception as exc:
        _mark_submission_unknown(db, project_id, str(exc))
        raise FreelancerAPIError(
            "Submission outcome unknown; remote reconciliation required before retrying.",
            status_code=409,
        ) from exc

    fallback_bidder_id = _coerce_int(getattr(client, "user_id", None))
    bid_id, bidder_id = _extract_bid_ids(result or {}, fallback_bidder_id=fallback_bidder_id)

    # 5. Save to DB on success
    if bid_id is None or bidder_id is None:
        _mark_submission_unknown(db, project_id, "Remote response missing bid/bidder ID")
        raise FreelancerAPIError(
            "Submission response incomplete; remote reconciliation required before retrying.",
            status_code=409,
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
    submission.status = "submitted"
    submission.freelancer_bid_id = bid_id
    project.status = "bid_submitted"
    try:
        db.commit()
    except Exception as exc:
        _mark_submission_unknown(db, project_id, f"Local persistence failed: {exc}")
        raise FreelancerAPIError(
            "Remote submission may have succeeded; local persistence failed. Reconcile before retrying.",
            status_code=409,
        ) from exc

    return {
        "bid_id": bid.freelancer_bid_id,
        "project_id": project_id,
        "amount": resolved_amount,
        "period": period,
        "description": bid_description,
        "status": "submitted",
    }


def _mark_submission_unknown(db: Session, project_id: int, reason: str) -> None:
    """Best effort detail update; the already committed reservation always blocks."""
    db.rollback()
    try:
        submission = db.query(BidSubmission).filter_by(project_freelancer_id=project_id).one()
        submission.status = "outcome_unknown"
        submission.error_message = reason
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Unable to record uncertain outcome for project %s; reservation retained", project_id)


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

    project = db.query(Project).filter_by(freelancer_id=bid.project_freelancer_id).first()
    if not project:
        raise ValueError("Cannot update bid without its local project.")
    if description is not None:
        content_safe, reason = check_content_risk(
            description, project, float(amount if amount is not None else bid.amount),
        )
        if not content_safe:
            raise ValueError(f"Bid content validation failed: {reason}")

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
