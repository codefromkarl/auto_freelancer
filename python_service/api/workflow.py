from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.exc import IntegrityError

from database.connection import get_db
from database.models import Project, CandidateWorkflow
from services import workflow_service as workflow
from services.project_service import published_since

router = APIRouter()


class SyncRequest(BaseModel):
    since_days: int = Field(default=7, ge=1, le=90)
    threshold: float = Field(default=7, ge=0, le=10, allow_inf_nan=False)


class DecisionRequest(BaseModel):
    revision: int = Field(ge=1)
    action: Literal["defer", "reject", "resume"]
    reason: str = Field(min_length=1, max_length=1000)
    resume_at: datetime | None = None

    @field_validator("resume_at")
    @classmethod
    def require_timezone(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("再次检查时间必须包含时区")
        return value


class Answer(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    answer: str = Field(min_length=1, max_length=2000)


class ResolveRequest(BaseModel):
    revision: int = Field(ge=1)
    answers: list[Answer] = Field(min_length=1, max_length=5)


def response(db, row):
    project = db.query(Project).filter_by(freelancer_id=row.project_freelancer_id).one()
    return {"status": "success", "data": workflow.serialize(row, project)}


@router.get("/stats")
def stats(days: int = Query(default=7, ge=1, le=90), db: Session = Depends(get_db)):
    return {"status": "success", "data": workflow.statistics(db, workflow.now() - timedelta(days=days))}


@router.get("")
def list_queue(state: str | None = None, limit: int = Query(default=50, ge=1, le=100),
               offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
    if state is not None and state not in workflow.STATES:
        raise HTTPException(400, "未知候选状态")
    query = db.query(CandidateWorkflow, Project).join(
        Project, Project.freelancer_id == CandidateWorkflow.project_freelancer_id)
    if state:
        query = query.filter(CandidateWorkflow.state == state)
    total = query.count()
    rows = query.order_by(CandidateWorkflow.updated_at.desc(), CandidateWorkflow.id.desc()).offset(offset).limit(limit).all()
    return {"status": "success", "data": [workflow.serialize(row, p) for row, p in rows], "total": total}


@router.post("/sync")
def sync(request: SyncRequest, db: Session = Depends(get_db)):
    try:
        workflow.reconcile(db)
        cutoff = datetime.now(timezone.utc) - timedelta(days=request.since_days)
        signature = workflow.policy_signature(db)
        for project in db.query(Project).filter(published_since(cutoff)).all():
            workflow.refresh_readiness(db, project, request.threshold, signature)
        db.commit()
        return {"status": "success", "data": {"updated": True}}
    except (StaleDataError, IntegrityError):
        db.rollback()
        raise HTTPException(409, "候选被同时更新，请刷新后重试")


@router.post("/{project_id}/decision")
def decide(project_id: int, request: DecisionRequest, db: Session = Depends(get_db)):
    try:
        row = workflow.decide(db, project_id, request.revision, request.action, request.reason, request.resume_at)
        return response(db, row)
    except LookupError as exc:
        db.rollback()
        raise HTTPException(404, str(exc))
    except (RuntimeError, StaleDataError, IntegrityError) as exc:
        db.rollback()
        raise HTTPException(409, "候选版本已变化，请刷新后重试")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc))


@router.post("/{project_id}/clarifications")
def resolve(project_id: int, request: ResolveRequest, db: Session = Depends(get_db)):
    try:
        row = workflow.resolve_questions(db, project_id, request.revision,
                                         [answer.model_dump() for answer in request.answers])
        return response(db, row)
    except LookupError as exc:
        db.rollback()
        raise HTTPException(404, str(exc))
    except (RuntimeError, StaleDataError, IntegrityError):
        db.rollback()
        raise HTTPException(409, "候选版本已变化，请刷新后重试")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc))
