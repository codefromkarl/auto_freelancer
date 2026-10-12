"""
Proposals API endpoints - wrapper around bids for frontend compatibility.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List, Any
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from database.connection import get_db
from services import bid_service
from services.freelancer_client import FreelancerAPIError

router = APIRouter()


class EvaluateProposalRequest(BaseModel):
    project_id: int = Field(gt=0)
    amount: float = Field(gt=0)
    amount_currency: Optional[str] = Field(None, pattern=r'^[A-Z]{3}$')
    period: int = Field(ge=1, le=365)
    description: str = Field(min_length=10, max_length=5000)


@router.post('/evaluate')
async def evaluate_proposal(request: EvaluateProposalRequest, db: Session = Depends(get_db)):
    from database.models import Project
    from services import bid_service
    from services.approved_bids import validate_terms
    from services.proposal_competition import ensure_competitor_context, evaluate_proposal_competition
    project = db.query(Project).filter_by(freelancer_id=request.project_id).first()
    if project is None:
        raise HTTPException(404,'Project not found')
    try:
        amount = bid_service._resolve_submission_amount(project,request.amount,request.amount_currency)
        validate_terms(project,amount,request.period)
        context = await ensure_competitor_context(db,project)
        review = evaluate_proposal_competition(project.to_dict(),request.description,amount,request.period,context)
        valid,reason = bid_service.check_content_risk(request.description,project,amount)
        if not valid:
            review['status'] = 'blocked'
            review['blocking_issues'].append(reason)
        return {'status':'success','data':{**review,'content_validation_passed':valid,
            'content_issues':[] if valid else [reason]}}
    except ValueError as exc:
        raise HTTPException(400,str(exc))


# Pydantic models
class CreateProposalRequest(BaseModel):
    """Request model for creating a proposal (bid)."""
    project_id: int = Field(gt=0)
    amount: float = Field(gt=0)
    amount_currency: Optional[str] = Field(None, pattern=r"^[A-Z]{3}$")
    period: int = Field(default=7, ge=1, le=365)
    description: Optional[str] = Field(None, min_length=10, max_length=5000)
    approval_id: Optional[str] = None


class UpdateProposalRequest(BaseModel):
    """Request model for updating a proposal (bid)."""
    amount: Optional[float] = Field(None, gt=0)
    period: Optional[int] = Field(None, ge=1, le=365)
    description: Optional[str] = Field(None, min_length=10, max_length=5000)


class APIResponse(BaseModel):
    """Standard API response wrapper."""
    status: str
    data: Any
    total: Optional[int] = None
    message: Optional[str] = None


class ProposalStats(BaseModel):
    """Proposal statistics response."""
    total: int
    accepted: int
    rejected: int
    pending: int
    success_rate: float
    avg_amount: float


@router.get("", response_model=APIResponse)
async def get_proposals(
    status: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db)
):
    """
    Get proposals (wraps bids for frontend compatibility).
    """
    # Map proposal status to bid status
    status_mapping = {
        'pending': 'active',
        'accepted': 'completed',
        'rejected': 'withdrawn',
        'withdrawn': 'withdrawn'
    }
    mapped_status = status_mapping.get(status)

    result = bid_service.get_user_bids(db, mapped_status, limit, offset)

    # Transform bid data to proposal format
    proposal_data = []
    for bid in result.get("data", []):
        proposal = {
            "id": bid.get("id"),
            "project_id": bid.get("project_id"),
            "project_title": bid.get("project_title", ""),
            "project_budget": bid.get("project_budget", ""),
            "amount": bid.get("amount"),
            "period": bid.get("period"),
            "description": bid.get("description"),
            "status": map_status_reverse(bid.get("status")),
            "submitdate": bid.get("submitdate"),
            "ai_score": bid.get("ai_score"),
            "competitor_count": bid.get("competitor_count", 0),
            "win_probability": bid.get("win_probability", 0),
        }
        proposal_data.append(proposal)

    return APIResponse(
        status="success",
        data=proposal_data,
        total=result.get("total")
    )


@router.get("/stats", response_model=APIResponse)
async def get_proposal_stats(db: Session = Depends(get_db)):
    """
    Get proposal statistics.
    """
    result = bid_service.get_user_bids(db, None, 1000, 0)
    data = result.get("data", [])

    total = len(data)
    accepted = sum(1 for b in data if b.get("status") == "completed")
    rejected = sum(1 for b in data if b.get("status") == "withdrawn")
    pending = sum(1 for b in data if b.get("status") == "active")

    success_rate = (accepted / total * 100) if total > 0 else 0.0
    avg_amount = sum(b.get("amount", 0) for b in data) / total if total > 0 else 0.0

    return APIResponse(
        status="success",
        data={
            "total": total,
            "accepted": accepted,
            "rejected": rejected,
            "pending": pending,
            "success_rate": success_rate,
            "avg_amount": avg_amount
        }
    )


@router.post("", response_model=APIResponse)
async def create_proposal(
    request: CreateProposalRequest,
    db: Session = Depends(get_db)
):
    """
    Create a new proposal (bid).
    """
    try:
        from services.approved_bids import submit_approved_bid, check_request
        if not request.approval_id:
            raise ValueError('Prepare and approve the final bid snapshot through QQ Bot first')
        check_request(request.approval_id, request.project_id, request.amount, request.period,
                      request.description, request.amount_currency)
        bid_data = await submit_approved_bid(db, request.approval_id)
        return APIResponse(status="success", data=bid_data)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FreelancerAPIError as e:
        raise HTTPException(status_code=e.status_code or 500, detail=e.message)


def map_status_reverse(status: Optional[str]) -> str:
    """Map bid status to proposal status."""
    if status == "completed":
        return "accepted"
    elif status == "active":
        return "pending"
    elif status == "withdrawn":
        return "rejected"
    return status or "pending"
