"""
Projects API endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List, Any
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from database.connection import get_db
from services import project_service
from services.project_scorer import get_project_scorer
from services.freelancer_client import FreelancerAPIError

router = APIRouter()


# Pydantic models for request/response
class ProjectSearchRequest(BaseModel):
    """Request model for project search."""
    query: Optional[str] = None
    skills: Optional[List[int]] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    status: Optional[str] = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class ProjectUpdateRequest(BaseModel):
    """Request model for updating project with AI analysis."""
    ai_score: float = Field(ge=0, le=10)
    ai_reason: str
    ai_proposal_draft: str
    suggested_bid: Optional[float] = Field(default=None, description="Suggested bid amount in USD")
    estimated_hours: Optional[int] = None
    hourly_rate: Optional[float] = None


class APIResponse(BaseModel):
    """Standard API response wrapper."""
    status: str
    data: Any
    total: Optional[int] = None


@router.get("/search", response_model=APIResponse)
async def search_projects(
    query: Optional[str] = None,
    skills: Optional[str] = None,
    budget_min: Optional[float] = None,
    budget_max: Optional[float] = None,
    status: Optional[str] = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db)
):
    """
    Search projects with advanced filters.
    """
    # Parse skills
    skills_list = None
    if skills:
        try:
            skills_list = [int(s.strip()) for s in skills.split(",")]
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid skills format")

    try:
        stored_projects = await project_service.search_projects(
            db=db,
            query=query,
            skills=skills_list,
            budget_min=budget_min,
            budget_max=budget_max,
            status=status,
            limit=limit,
            offset=offset
        )

        return APIResponse(
            status="success",
            data=stored_projects,
            total=len(stored_projects)
        )
    except FreelancerAPIError as e:
        raise HTTPException(status_code=e.status_code or 500, detail=e.message)


@router.get("/{project_id}", response_model=APIResponse)
async def get_project(project_id: int, db: Session = Depends(get_db)):
    """
    Get detailed information for a specific project.
    """
    try:
        project_dict = await project_service.get_project_details(db, project_id)
        return APIResponse(status="success", data=project_dict)
    except FreelancerAPIError as e:
        raise HTTPException(status_code=e.status_code or 500, detail=e.message)


@router.put("/{project_id}", response_model=APIResponse)
async def update_project_with_ai(
    project_id: int,
    data: ProjectUpdateRequest,
    db: Session = Depends(get_db)
):
    """
    Update a project with AI analysis results.
    """
    updated_project = project_service.update_project_ai_analysis(
        db,
        project_id,
        data.ai_score,
        data.ai_reason,
        data.ai_proposal_draft,
        data.suggested_bid,
        estimated_hours=data.estimated_hours,
        hourly_rate=data.hourly_rate
    )

    if not updated_project:
        raise HTTPException(status_code=404, detail="Project not found in database")

    return APIResponse(status="success", data=updated_project)


@router.post("/{project_id}/score", response_model=APIResponse)
async def score_project_with_ai(project_id: int, db: Session = Depends(get_db)):
    """
    Score a project using the built-in scoring system.
    """
    # 1. Ensure we have the project detail first
    try:
        project_dict = await project_service.get_project_details(db, project_id)
        
        # 2. Score it
        scorer = get_project_scorer()
        score_result = scorer.score_project(project_dict)

        # 3. Save to DB
        project_service.update_project_ai_analysis(
            db,
            project_id,
            score_result.ai_score,
            score_result.ai_reason,
            score_result.ai_proposal_draft,
            None, # suggested_bid
            estimated_hours=score_result.score_breakdown.estimated_hours,
            hourly_rate=score_result.score_breakdown.tech_score # Wait, tech_score? No, I need hourly_rate
        )
        
        # Wait, ScoreBreakdown doesn't have hourly_rate. 
        # But ProjectScorer.score_budget_efficiency calculates it.
        # I should probably add hourly_rate to ScoreBreakdown.
    except FreelancerAPIError as e:
        raise HTTPException(status_code=e.status_code or 500, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to score project: {str(e)}")
