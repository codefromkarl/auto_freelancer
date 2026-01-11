"""
Milestones API endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, Any
from pydantic import BaseModel, Field
from datetime import datetime

from database.connection import get_db, get_db_session
from database.models import Milestone, Project, AuditLog
from services.freelancer_client import get_freelancer_client, FreelancerAPIError

router = APIRouter()


# Pydantic models
class CreateMilestoneRequest(BaseModel):
    """Request model for creating a milestone."""
    project_id: int = Field(gt=0)
    bidder_id: int = Field(gt=0)
    amount: float = Field(gt=0)
    description: str = Field(min_length=10, max_length=2000)
    due_date: Optional[str] = None


class APIResponse(BaseModel):
    """Standard API response wrapper."""
    status: str
    data: Any


@router.post("", response_model=APIResponse)
async def create_milestone(request: CreateMilestoneRequest):
    """
    Create a milestone payment for a project.

    Request Body:
    - project_id: Project ID
    - bidder_id: Freelancer User ID
    - amount: Milestone amount
    - description: Milestone description
    - due_date: Due date (optional, ISO format)
    """
    try:
        client = get_freelancer_client()

        # Submit to Freelancer API
        result = await client.create_milestone(
            project_id=request.project_id,
            bidder_id=request.bidder_id,
            amount=request.amount,
            description=request.description,
            due_date=request.due_date
        )

        # Store in database
        with get_db_session() as db:
            # Get internal project ID
            project = db.query(Project).filter_by(
                freelancer_id=request.project_id
            ).first()

            milestone = Milestone(
                freelancer_milestone_id=result.get('milestone_id', {}).get('id') if result else 0,
                project_id=project.id if project else 0,
                project_freelancer_id=request.project_id,
                amount=request.amount,
                description=request.description,
                due_date=request.due_date,
                status="created",
                bid_id=result.get('bid_id')
            )
            db.add(milestone)

            # Audit log
            audit = AuditLog(
                action="create_milestone",
                entity_type="milestone",
                entity_id=milestone.freelancer_milestone_id,
                request_data=str(request.dict()),
                response_data=str(result),
                status="success"
            )
            db.add(audit)

            db.commit()
            db.refresh(milestone)

        return APIResponse(
            status="success",
            data={
                "milestone_id": milestone.freelancer_milestone_id,
                "project_id": request.project_id,
                "amount": request.amount,
                "status": "created"
            }
        )

    except FreelancerAPIError as e:
        with get_db_session() as db:
            audit = AuditLog(
                action="create_milestone",
                entity_type="milestone",
                entity_id=0,
                request_data=str(request.dict()),
                response_data=str(e.message),
                status="error",
                error_message=e.message
            )
            db.add(audit)
            db.commit()

        raise HTTPException(status_code=e.status_code or 500, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create milestone: {str(e)}")


@router.get("/{project_id}", response_model=APIResponse)
async def get_project_milestones(project_id: int):
    """
    Get all milestones for a project.

    Path Parameters:
    - project_id: Freelancer project ID
    """
    try:
        with get_db_session() as db:
            project = db.query(Project).filter_by(
                freelancer_id=project_id
            ).first()

            if not project:
                raise HTTPException(status_code=404, detail="Project not found in database")

            milestones = db.query(Milestone).filter_by(
                project_id=project.id
            ).order_by(Milestone.created_at.desc()).all()

        return APIResponse(
            status="success",
            data=[m.to_dict() for m in milestones]
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get milestones: {str(e)}")


@router.post("/{milestone_id}/accept", response_model=APIResponse)
async def accept_milestone(milestone_id: int):
    """
    Accept a milestone payment request.

    Path Parameters:
    - milestone_id: Freelancer milestone ID
    """
    try:
        client = get_freelancer_client()

        # Accept via Freelancer API
        result = await client.accept_milestone(milestone_id)

        # Update in database
        with get_db_session() as db:
            milestone = db.query(Milestone).filter_by(
                freelancer_milestone_id=milestone_id
            ).first()

            if milestone:
                milestone.status = "accepted"
                milestone.updated_at = datetime.utcnow()

                # Audit log
                audit = AuditLog(
                    action="accept_milestone",
                    entity_type="milestone",
                    entity_id=milestone_id,
                    request_data="",
                    response_data=str(result),
                    status="success"
                )
                db.add(audit)

                db.commit()

        return APIResponse(
            status="success",
            data={"message": "Milestone accepted", "status": "accepted"}
        )

    except FreelancerAPIError as e:
        with get_db_session() as db:
            audit = AuditLog(
                action="accept_milestone",
                entity_type="milestone",
                entity_id=milestone_id,
                request_data="",
                response_data=str(e.message),
                status="error",
                error_message=e.message
            )
            db.add(audit)
            db.commit()

        raise HTTPException(status_code=e.status_code or 500, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to accept milestone: {str(e)}")


@router.post("/{milestone_id}/release", response_model=APIResponse)
async def release_milestone(milestone_id: int):
    """
    Release payment for a completed milestone.

    Path Parameters:
    - milestone_id: Freelancer milestone ID
    """
    try:
        client = get_freelancer_client()

        # Release via Freelancer API
        result = await client.release_milestone(milestone_id)

        # Update in database
        with get_db_session() as db:
            milestone = db.query(Milestone).filter_by(
                freelancer_milestone_id=milestone_id
            ).first()

            if milestone:
                milestone.status = "paid"
                milestone.updated_at = datetime.utcnow()

                # Audit log
                audit = AuditLog(
                    action="release_milestone",
                    entity_type="milestone",
                    entity_id=milestone_id,
                    request_data="",
                    response_data=str(result),
                    status="success"
                )
                db.add(audit)

                db.commit()

        return APIResponse(
            status="success",
            data={"message": "Payment released", "status": "paid"}
        )

    except FreelancerAPIError as e:
        with get_db_session() as db:
            audit = AuditLog(
                action="release_milestone",
                entity_type="milestone",
                entity_id=milestone_id,
                request_data="",
                response_data=str(e.message),
                status="error",
                error_message=e.message
            )
            db.add(audit)
            db.commit()

        raise HTTPException(status_code=e.status_code or 500, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to release milestone: {str(e)}")
