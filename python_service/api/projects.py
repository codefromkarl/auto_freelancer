"""
Projects API endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from typing import Optional, List, Any
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from database.connection import get_db
from services import project_service
from services.llm_scoring_service import get_scoring_service
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
    message: Optional[str] = None
    is_syncing: bool = False


@router.get("/search", response_model=APIResponse)
async def search_projects(
    background_tasks: BackgroundTasks,
    query: Optional[str] = None,
    skills: Optional[str] = None,
    budget_min: Optional[float] = None,
    budget_max: Optional[float] = None,
    status: Optional[str] = None,
    # 同时支持 min_score 和 score_min 参数
    min_score: Optional[float] = Query(default=None, alias="score_min"),
    max_score: Optional[float] = Query(default=None, alias="score_max"),
    refresh: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db)
):
    """
    Search projects.
    If refresh=true, trigger sync in background and return local results immediately.
    """
    # Parse skills
    skills_list = None
    if skills:
        try:
            skills_list = [int(s.strip()) for s in skills.split(",")]
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid skills format")

    # 如果需要刷新，将其作为后台任务启动
    if refresh:
        background_tasks.add_task(
            project_service.search_projects,
            db=db,
            query=query,
            skills=skills_list,
            budget_min=budget_min,
            budget_max=budget_max,
            status=status,
            min_score=min_score,
            max_score=max_score,
            limit=limit,
            offset=offset,
            sync_from_api=True
        )
        # 立即返回，不等待同步完成
        # 注意：这里我们返回本地已有的数据，或者一个正在同步的标识

    try:
        stored_projects = await project_service.search_projects(
            db=db,
            query=query,
            skills=skills_list,
            budget_min=budget_min,
            budget_max=budget_max,
            status=status,
            min_score=min_score,
            max_score=max_score,
            limit=limit,
            offset=offset,
            sync_from_api=False # 此次请求仅查询本地
        )

        return APIResponse(
            status="success",
            data=stored_projects,
            total=len(stored_projects),
            message="Sync started in background" if refresh else None,
            is_syncing=project_service.is_currently_syncing()
        )
    except FreelancerAPIError as e:
        raise HTTPException(status_code=e.status_code or 500, detail=e.message)


@router.get("/{project_id}", response_model=APIResponse)
async def get_project(
    project_id: int,
    refresh: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    """
    Read cached details; explicitly refresh or fetch an uncached project remotely.
    """
    try:
        from database.models import Project
        project = db.query(Project).filter_by(freelancer_id=project_id).first()
        if project is not None and not refresh:
            project_dict = project.to_dict()
        else:
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
    Score a project using the AI scoring system.
    """
    try:
        # 1. 从数据库获取项目 (如果数据库没有，则尝试从 API 获取)
        from database.models import Project
        project = db.query(Project).filter_by(freelancer_id=project_id).first()
        if not project:
            # 尝试从 API 抓取详情并入库
            await project_service.get_project_details(db, project_id)

        project = db.query(Project).filter_by(freelancer_id=project_id).first()
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        service = get_scoring_service()
        total, errors, _, _ = await service.score_projects_concurrent([project], db, max_retries=0)
        if errors or total != 1:
            raise HTTPException(status_code=422, detail="模型评分未通过结构化校验，原评分不能作为本次结果")
        updated_data = project.to_dict()

        return APIResponse(status="success", data=updated_data)
    except FreelancerAPIError as e:
        raise HTTPException(status_code=e.status_code or 500, detail=e.message)
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.error(f"Scoring error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to score project: {str(e)}")
