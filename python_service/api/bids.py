"""
Bids API endpoints.
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
class CreateBidRequest(BaseModel):
    """Request model for creating a bid."""
    project_id: int = Field(gt=0)
    amount: float = Field(gt=0)
    period: int = Field(default=7, ge=1, le=365)
    description: Optional[str] = Field(None, min_length=10, max_length=5000)


class UpdateBidRequest(BaseModel):
    """Request model for updating a bid."""
    amount: Optional[float] = Field(None, gt=0)
    period: Optional[int] = Field(None, ge=1, le=365)
    description: Optional[str] = Field(None, min_length=10, max_length=5000)


class APIResponse(BaseModel):
    """Standard API response wrapper."""
    status: str
    data: Any
    total: Optional[int] = None


@router.post("", response_model=APIResponse)
async def create_bid(request: CreateBidRequest, db: Session = Depends(get_db)):
    """
    Create a new bid for a project.
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


@router.get("/user", response_model=APIResponse)
async def get_user_bids(
    status: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db)
):
    """
    Get the authenticated user's bids.
    """
    result = bid_service.get_user_bids(db, status, limit, offset)
    return APIResponse(
        status="success",
        data=result["data"],
        total=result["total"]
    )


@router.get("/{bid_id}", response_model=APIResponse)
async def get_bid(bid_id: int, db: Session = Depends(get_db)):
    """
    Get details of a specific bid.
    """
    bid_data = bid_service.get_bid_details(db, bid_id)
    if not bid_data:
        raise HTTPException(status_code=404, detail="Bid not found")
        
    return APIResponse(status="success", data=bid_data)


@router.put("/{bid_id}", response_model=APIResponse)
async def update_bid(
    bid_id: int, 
    request: UpdateBidRequest,
    db: Session = Depends(get_db)
):
    """
    Update an existing bid.
    """
    try:
        updated_bid = await bid_service.update_bid(
            db,
            bid_id,
            request.amount,
            request.period,
            request.description
        )
        if not updated_bid:
            raise HTTPException(status_code=404, detail="Bid not found")
            
        return APIResponse(status="success", data=updated_bid)
        
    except FreelancerAPIError as e:
        raise HTTPException(status_code=e.status_code or 500, detail=e.message)


@router.delete("/{bid_id}", response_model=APIResponse)
async def retract_bid(bid_id: int, db: Session = Depends(get_db)):
    """
    Retract (withdraw) an existing bid.
    """
    try:
        success = await bid_service.retract_bid(db, bid_id)
        if not success:
            raise HTTPException(status_code=404, detail="Bid not found or already retracted")
            
        return APIResponse(
            status="success",
            data={"message": "Bid successfully retracted"}
        )
        
    except FreelancerAPIError as e:
        raise HTTPException(status_code=e.status_code or 500, detail=e.message)
