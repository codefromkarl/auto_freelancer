"""
Project Kick-off API endpoints.

Handles automatic project initialization after winning a bid.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional, List
import logging

from database.connection import get_db_session, verify_api_key
from database.models import ProjectKickoff
from services.kickoff_service import KickoffService

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================

class KickoffTriggerRequest(BaseModel):
    """Request model for triggering project kick-off."""
    project_freelancer_id: int = Field(..., description="Freelancer project ID")
    bid_id: int = Field(..., description="Winning bid ID")


class KickoffResponse(BaseModel):
    """Response model for kick-off operation."""
    success: bool
    project_id: Optional[int] = None
    kickoff_id: Optional[int] = None
    template_type: Optional[str] = None
    results: Optional[dict] = None
    error: Optional[str] = None
    existing_kickoff: Optional[dict] = None


class KickoffStatusResponse(BaseModel):
    """Response model for kick-off status."""
    id: Optional[int] = None
    project_id: Optional[int] = None
    repo_url: Optional[str] = None
    repo_status: Optional[str] = None
    collab_space_url: Optional[str] = None
    collab_status: Optional[str] = None
    template_type: Optional[str] = None
    notification_sent: bool = False
    triggered_at: Optional[str] = None
    completed_at: Optional[str] = None


# ============================================================================
# API Endpoints
# ============================================================================

@router.post("/trigger", response_model=KickoffResponse, status_code=status.HTTP_200_OK)
async def trigger_kickoff(
    request: KickoffTriggerRequest,
    api_key: str = Depends(verify_api_key)
):
    """
    Trigger project kick-off automation.

    This endpoint automatically:
    1. Creates a Git repository (GitHub/GitLab)
    2. Sets up a collaboration space (Notion/Trello)
    3. Generates project scaffolding files

    The kick-off is triggered only once per project.
    """
    logger.info(f"Kick-off triggered for project {request.project_freelancer_id}")

    try:
        result = KickoffService.trigger_kickoff(
            project_freelancer_id=request.project_freelancer_id,
            bid_id=request.bid_id
        )

        return KickoffResponse(**result)

    except Exception as e:
        logger.error(f"Kick-off failed for project {request.project_freelancer_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Kick-off failed: {str(e)}"
        )


@router.get("/{project_freelancer_id}", response_model=KickoffStatusResponse)
async def get_kickoff_status(
    project_freelancer_id: int,
    api_key: str = Depends(verify_api_key)
):
    """
    Get kick-off status for a project.

    Returns details about the automatic initialization if it has been performed.
    """
    status_data = KickoffService.get_kickoff_status(project_freelancer_id)

    if not status_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No kick-off record found for this project"
        )

    return KickoffStatusResponse(**status_data)


@router.get("/list/recent", response_model=List[KickoffStatusResponse])
async def list_recent_kickoffs(
    limit: int = 10,
    api_key: str = Depends(verify_api_key)
):
    """
    List recent project kick-off records.

    Returns the most recent kick-off operations.
    """
    if limit > 100:
        limit = 100

    return KickoffService.list_recent_kickoffs(limit)


@router.post("/check/{project_freelancer_id}")
async def check_and_trigger_kickoff(
    project_freelancer_id: int,
    bid_id: Optional[int] = None,
    api_key: str = Depends(verify_api_key)
):
    """
    Check project status and trigger kick-off if bid was accepted.

    This endpoint is designed for n8n workflow integration.
    It queries the Freelancer API to check if the project status is 'awarded'
    and automatically triggers the kick-off if so.
    """
    from services.freelancer_client import get_freelancer_client

    try:
        client = get_freelancer_client()

        # Get project details
        project_info = client.get_project(project_freelancer_id)

        # Check if project is awarded
        if project_info.get("status") != "awarded":
            return {
                "success": True,
                "action": "none",
                "message": f"Project status is '{project_info.get('status')}'. Not awarded yet.",
                "project_status": project_info.get("status")
            }

        # Get winning bid
        if not bid_id:
            # Try to get the winning bid ID
            from database.connection import get_db_session
            from database.models import Bid, Project

            with get_db_session() as db:
                project = db.query(Project).filter_by(freelancer_id=project_freelancer_id).first()
                if project:
                    winning_bid = db.query(Bid).filter_by(
                        project_freelancer_id=project_freelancer_id,
                        status="active"
                    ).first()
                    if winning_bid:
                        bid_id = winning_bid.id

        if not bid_id:
            return {
                "success": False,
                "error": "No winning bid found for this project"
            }

        # Trigger kick-off
        result = KickoffService.trigger_kickoff(project_freelancer_id, bid_id)
        return result

    except Exception as e:
        logger.error(f"Failed to check and trigger kick-off: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error: {str(e)}"
        )


@router.get("/templates", status_code=status.HTTP_200_OK)
async def list_templates(api_key: str = Depends(verify_api_key)):
    """
    List available project templates for scaffolding.

    Returns information about available project types and their descriptions.
    """
    from services.kickoff_service import PROJECT_TEMPLATES

    return {
        "templates": [
            {
                "id": key,
                "description": value["description"],
                "files": list(value["files"].keys())
            }
            for key, value in PROJECT_TEMPLATES.items()
        ]
    }


@router.delete("/{project_freelancer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_kickoff_record(
    project_freelancer_id: int,
    api_key: str = Depends(verify_api_key)
):
    """
    Delete a kick-off record (for retry purposes).

    This allows re-triggering kick-off if the previous attempt failed.
    """
    with get_db_session() as db:
        kickoff = db.query(ProjectKickoff).filter_by(
            project_freelancer_id=project_freelancer_id
        ).first()

        if not kickoff:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Kick-off record not found"
            )

        db.delete(kickoff)
        db.commit()

    return None
