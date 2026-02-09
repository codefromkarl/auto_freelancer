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


# Pydantic models
class CreateProposalRequest(BaseModel):
    """Request model for creating a proposal (bid)."""
    project_id: int = Field(gt=0)
    amount: float = Field(gt=0)
    period: int = Field(default=7, ge=1, le=365)
    description: Optional[str] = Field(None, min_length=10, max_length=5000)


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
        proposal_data = {
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
        proposal_data.append(proposal_data)

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
        bid_data = await bid_service.create_bid(
            db,
            request.project_id,
            request.amount,
            request.period,
            request.description
        )
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
