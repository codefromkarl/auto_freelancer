from sqlalchemy.orm import Session
from sqlalchemy import or_, func, case, cast, Float
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, timezone
import logging
import json
import asyncio
import math
import re

from database.models import Project
from services.freelancer_client import get_freelancer_client, FreelancerAPIError
from freelancersdk.resources.projects.helpers import (
    create_get_projects_project_details_object,
    create_get_projects_user_details_object
)
from config import settings
from utils.currency_converter import get_currency_converter

logger = logging.getLogger(__name__)
_BIDDABLE_STATUSES = {"open", "active", "open_for_bidding"}
_STICKY_LOCAL_STATUSES = {
    "bid_submitted",
    "skills_blocked",
    "preferred_only",
    "escrow_required",
}


def _check_skill_match(project_dict: Dict[str, Any]) -> bool:
    """
    检查项目是否与简历核心技能匹配

    Args:
        project_dict: 项目数据字典

    Returns:
        bool: 是否匹配简历技能
    """
    # 获取项目的标题、描述和技能列表
    title = (project_dict.get('title') or '').lower()
    description = (
        project_dict.get('full_description') or project_dict.get('description')
        or project_dict.get('preview_description') or ''
    ).lower()
    project_jobs = project_dict.get('jobs', [])

    # 收集所有简历技能关键词
    all_keywords = []
    for keywords in settings.RESUME_SKILL_MAPPINGS.values():
        all_keywords.extend(keywords)

    # 检查标题和描述中是否包含简历关键词
    text_content = f"{title} {description}"
    def matches(text: str) -> bool:
        return any(re.search(r"(?<!\w)" + re.escape(keyword.lower()) + r"(?!\w)", text)
                   for keyword in all_keywords)

    # Broad media/AI words alone do not establish a software deliverable.
    broad = {"ai", "video", "audio", "media", "streaming", "security", "vector", "container"}
    strong_keywords = [kw for kw in all_keywords if kw.lower() not in broad]
    def strong_matches(text):
        return any(re.search(r"(?<!\w)" + re.escape(kw.lower()) + r"(?!\w)", text)
                   for kw in strong_keywords)

    text_match = strong_matches(text_content)
    if not text_match and matches(text_content):
        text_match = bool(re.search(r"\b(implement|develop|integrate|build|debug)\b", text_content)
                          and re.search(r"\b(software|application|workflow|model|chatbot|agent|pipeline|system)\b", text_content))

    # 如果文本匹配成功，直接返回
    if text_match:
        return True

    # 检查技能ID匹配（如果有技能ID数据）
    # 注意：Freelancer API返回的jobs可能是技能ID或技能名称
    if project_jobs:
        for job in project_jobs:
            job_name = job.get('name', '') if isinstance(job, dict) else (job if isinstance(job, str) else '')
            if strong_matches(job_name.lower()):
                return True

    return False


def _pre_filter_projects(
    projects_data: List[Dict[str, Any]],
    budget_min_threshold: float = None,
    min_desc_length: int = None,
    allowed_statuses: List[str] = None,
    enable_skill_match: bool = True,
    min_submit_ts: Optional[int] = None,
    fixed_price_only: bool = True,
) -> tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    初筛项目数据

    Args:
        projects_data: 原始项目列表
        budget_min_threshold: 最低预算阈值（USD）
        min_desc_length: 最小描述长度
        allowed_statuses: 允许的状态列表
        enable_skill_match: 是否启用技能匹配

    Returns:
        (筛选后的项目列表, 过滤统计)
    """
    filtered = []
    stats = {
        'total': len(projects_data),
        'filtered_budget': 0,
        'filtered_desc': 0,
        'filtered_status': 0,
        'filtered_skill': 0,
        'filtered_time': 0,
        'filtered_billing_type': 0,
        'filtered_data': 0,
        'kept': 0
    }

    for project in projects_data:
        # 0.5 计费类型筛选（默认只保留 fixed 一次性项目）
        if fixed_price_only:
            project_type = str(project.get("type") or "").lower()
            if project_type != "fixed":
                stats['filtered_billing_type'] += 1
                logger.debug("Filtered by billing type: %s (type=%s)", project.get("title"), project_type)
                continue

        # 0. 发布时间筛选（只保留最近项目）
        if min_submit_ts is not None:
            submit_ts = _parse_submit_timestamp(project.get("submitdate"))
            if submit_ts is None or submit_ts < min_submit_ts:
                stats['filtered_time'] += 1
                logger.debug("Filtered by submitdate: %s", project.get('title'))
                continue

        # 1. 预算筛选
        if budget_min_threshold is not None:
            budget_info = project.get('budget') or {}
            budget_max = budget_info.get('maximum') or budget_info.get('minimum', 0)
            currency_code = (project.get('currency') or {}).get('code')
            if not currency_code or not isinstance(budget_max, (int, float)) or not math.isfinite(budget_max) or budget_max <= 0:
                stats['filtered_data'] += 1
                continue
            
            # 使用动态汇率转换
            converter = get_currency_converter()
            currency_rate = converter.get_rate_sync(currency_code)
            if currency_rate is None or not math.isfinite(currency_rate) or currency_rate <= 0:
                logger.warning(
                    "Currency rate missing for %s; deferring project until budget can be validated",
                    currency_code,
                )
                stats['filtered_data'] += 1
                continue
            else:
                budget_usd = budget_max * currency_rate

            if budget_usd is not None and budget_usd < budget_min_threshold:
                stats['filtered_budget'] += 1
                logger.debug(f"Filtered by budget: {project.get('title')} (budget: {budget_usd:.2f} USD < {budget_min_threshold})")
                continue

        # 2. 描述长度筛选
        if min_desc_length is not None:
            description = (project.get('full_description') or project.get('description')
                           or project.get('preview_description') or '')
            if len(description) < min_desc_length:
                stats['filtered_desc'] += 1
                logger.debug(f"Filtered by description length: {project.get('title')} (length: {len(description)} < {min_desc_length})")
                continue

        # 3. 状态筛选
        if allowed_statuses is not None:
            status = str(project.get('status') or '').lower()
            if status not in [s.lower() for s in allowed_statuses]:
                stats['filtered_status'] += 1
                logger.debug(f"Filtered by status: {project.get('title')} (status: {status})")
                continue

        # 4. 技能匹配筛选
        if enable_skill_match:
            if not _check_skill_match(project):
                stats['filtered_skill'] += 1
                logger.debug(f"Filtered by skill mismatch: {project.get('title')}")
                continue

        # 通过所有筛选条件
        filtered.append(project)
        stats['kept'] += 1

    logger.info(f"Pre-filter results: {stats}")
    return filtered, stats


def project_material_fields(project: Project) -> dict:
    """Scope and pricing fields shared by score invalidation and bid approval."""
    try:
        skills = sorted(json.loads(project.skills or '[]'), key=str)
    except (ValueError, TypeError):
        skills = project.skills
    return {
        'id': project.freelancer_id, 'title': project.title,
        'description': project.full_description or project.description or project.preview_description or '',
        'budget_min': float(project.budget_minimum) if project.budget_minimum is not None else None,
        'budget_max': float(project.budget_maximum) if project.budget_maximum is not None else None,
        'currency': project.currency_code, 'type': project.type_id, 'skills': skills,
        'owner_id': project.owner_id,
    }


def _apply_project_fields(project: Project, project_dict: Dict[str, Any]) -> None:
    """
    Apply mutable fields from API payload to local Project row.
    """
    from services.scoring_policy import scoring_inputs
    previous = project_material_fields(project)
    previous_scoring = scoring_inputs(project)
    budget = project_dict.get("budget", {}) or {}
    currency = project_dict.get("currency", {}) or {}

    project.title = project_dict.get("title", project.title or "")
    project.preview_description = project_dict.get(
        "preview_description", project.preview_description
    )
    project.description = project_dict.get("description", project.description)
    if project_dict.get("full_description"):
        project.full_description = project_dict["full_description"]
    elif project_dict.get("description"):
        project.full_description = project_dict["description"]
    jobs = project_dict.get("jobs")
    if isinstance(jobs, list):
        project.skills = json.dumps([
            job.get("name") if isinstance(job, dict) else job
            for job in jobs if not isinstance(job, dict) or job.get("name")
        ], ensure_ascii=False)
    for key in ("bid_stats", "owner_info"):
        if isinstance(project_dict.get(key), dict):
            setattr(project, key, json.dumps(project_dict[key], ensure_ascii=False))
    project.budget_minimum = budget.get("minimum", project.budget_minimum)
    project.budget_maximum = budget.get("maximum", project.budget_maximum)
    project.currency_code = currency.get("code", project.currency_code or "USD")
    remote_status = str(project_dict.get("status", project.status or "open")).lower()
    current_status = str(project.status or "").lower()
    if current_status in _STICKY_LOCAL_STATUSES and remote_status in _BIDDABLE_STATUSES:
        # Keep local terminal/blocked marker to avoid repeated attempts after periodic sync.
        project.status = current_status
    else:
        project.status = remote_status or "open"
    project_type = str(project_dict.get("type") or "").lower()
    if project_type == "fixed":
        project.type_id = 1
    elif project_type == "hourly":
        project.type_id = 2
    owner = project_dict.get("owner")
    owner_id = owner.get("id") if isinstance(owner, dict) else owner
    project.owner_id = project_dict.get("owner_id") or owner_id or project.owner_id
    submitdate = project_dict.get("submitdate")
    if submitdate is not None:
        project.submitdate = str(submitdate)
    if previous != project_material_fields(project):
        # Changed requirements must return to scoring, never retain an old quote.
        for field in ('ai_score', 'ai_reason', 'ai_proposal_draft', 'suggested_bid',
                      'estimated_hours', 'hourly_rate'):
            setattr(project, field, None)
    if previous_scoring != scoring_inputs(project):
        project.ai_score = None
        project.ai_reason = None
        project.score_metadata = None
        project.scored_at = None
    from sqlalchemy.orm import object_session
    session = object_session(project)
    if session is not None:
        from services import workflow_service as workflow
        from database.models import CandidateWorkflow
        row = session.query(CandidateWorkflow).filter_by(project_freelancer_id=project.freelancer_id).first()
        if row is not None:
            row = workflow.ensure(session, project)
            if row.state == "ready" and project.ai_score is None:
                workflow.transition(session, row, "needs_evaluation", "score_stale", "项目资料已变化，等待重新评估")
    project.updated_at = datetime.utcnow()


def publication_timestamp():
    numeric = cast(Project.submitdate, Float)
    return case(
        (numeric > 10_000_000_000, numeric / 1000),
        (numeric > 1_000_000_000, numeric),
        else_=cast(func.strftime("%s", Project.submitdate), Float),
    )


def published_since(cutoff: datetime):
    """Filter actual publication time (seconds, milliseconds or ISO), never ingestion time."""
    timestamp = publication_timestamp()
    cutoff_utc = cutoff.replace(tzinfo=timezone.utc) if cutoff.tzinfo is None else cutoff
    return timestamp >= cutoff_utc.timestamp()


def _parse_submit_timestamp(raw_submitdate: Any) -> Optional[int]:
    """Parse project submitdate from multiple possible formats into unix timestamp(seconds)."""
    if raw_submitdate is None or isinstance(raw_submitdate, bool):
        return None

    # int/float unix timestamp
    if isinstance(raw_submitdate, (int, float)):
        if not math.isfinite(raw_submitdate):
            return None
        ts = int(raw_submitdate)
        if ts > 10_000_000_000:  # milliseconds
            ts //= 1000
        return ts if ts > 0 else None

    # string forms
    raw = str(raw_submitdate).strip()
    if not raw:
        return None

    if raw.isdigit():
        ts = int(raw)
        if ts > 10_000_000_000:  # milliseconds
            ts //= 1000
        return ts if ts > 0 else None

    # ISO datetime fallback
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    except Exception:
        return None

# Async lock to serialize sync operations; _is_syncing kept for status queries.
_sync_lock = asyncio.Lock()
_is_syncing = False

def is_currently_syncing() -> bool:
    """获取当前同步状态"""
    return _is_syncing

async def search_projects(
    db: Session,
    query: Optional[str] = None,
    skills: Optional[List[int]] = None,
    budget_min: Optional[float] = None,
    budget_max: Optional[float] = None,
    status: Optional[str] = None,
    min_score: Optional[float] = None,
    max_score: Optional[float] = None,
    limit: int = 20,
    offset: int = 0,
    sync_from_api: bool = False,  # 只有明确要求时才同步
    allowed_statuses: Optional[List[str]] = None,
    since_days: Optional[int] = None,
    fixed_price_only: bool = False,
) -> List[Dict[str, Any]]:
    """
    Search projects in local database.
    If sync_from_api is True, fetch from Freelancer API first.
    """
    normalized_allowed_statuses = [s.lower() for s in (allowed_statuses or settings.ALLOWED_STATUSES)]
    min_submit_ts = None
    if since_days is not None and since_days > 0:
        min_submit_ts = int((datetime.now(timezone.utc) - timedelta(days=since_days)).timestamp())
    
    synced_ids = None
    # 1. 如果明确要求同步，先执行抓取同步逻辑
    if sync_from_api:
        if _sync_lock.locked():
            logger.info("Sync already in progress, skipping duplicate request")
            return []

        from database.connection import get_db_session

        async with _sync_lock:
            global _is_syncing
            _is_syncing = True
            try:
                client = get_freelancer_client()
                p_data = await client.search_projects(
                    query=query,
                    skills=skills,
                    budget_min=budget_min,
                    budget_max=budget_max,
                    status=status,
                    limit=limit,
                    offset=0
                )

                synced_ids = []
                if p_data:
                    filtered_projects, filter_stats = _pre_filter_projects(
                        projects_data=p_data,
                        budget_min_threshold=settings.MIN_BUDGET_THRESHOLD,
                        min_desc_length=settings.MIN_DESCRIPTION_LENGTH,
                        allowed_statuses=normalized_allowed_statuses,
                        enable_skill_match=True,
                        min_submit_ts=min_submit_ts,
                        fixed_price_only=fixed_price_only,
                    )

                    with get_db_session() as background_db:
                        from services import workflow_service as workflow
                        workflow.event(background_db, "fetch", "observed", count=len(p_data))
                        for reason, count in filter_stats.items():
                            if reason.startswith("filtered_") and count:
                                workflow.event(background_db, "filter", "excluded", reason=reason, count=count)
                        workflow.event(background_db, "filter", "kept", count=filter_stats["kept"])
                        for project_dict in filtered_projects:
                            pid = project_dict.get('id')
                            if not pid: continue
                            synced_ids.append(pid)

                            existing = background_db.query(Project).filter_by(freelancer_id=pid).first()
                            if existing:
                                _apply_project_fields(existing, project_dict)
                            else:
                                new_proj = Project(
                                    freelancer_id=pid,
                                    created_at=datetime.utcnow()
                                )
                                _apply_project_fields(new_proj, project_dict)
                                background_db.add(new_proj)
                                existing = new_proj
                            background_db.flush()
                            workflow.ensure(background_db, existing)
                        background_db.commit()
                else:
                    from services import workflow_service as workflow
                    with get_db_session() as background_db:
                        workflow.event(background_db, "fetch", "observed", count=0)
                        background_db.commit()
                logger.info(f"Background sync completed successfully for query: {query}")
            except Exception as e:
                logger.error(f"Background sync failed: {e}")
                raise
            finally:
                _is_syncing = False
                logger.info("Background sync lock released")

    # 2. 构建本地数据库查询
    db_query = db.query(Project)
    if synced_ids is not None:
        db_query = db_query.filter(Project.freelancer_id.in_(synced_ids))

    if query:
        db_query = db_query.filter(or_(
            Project.title.ilike(f"%{query}%"),
            Project.description.ilike(f"%{query}%")
        ))
    
    if status:
        db_query = db_query.filter(Project.status == status)
    elif normalized_allowed_statuses:
        db_query = db_query.filter(func.lower(Project.status).in_(normalized_allowed_statuses))

    if fixed_price_only:
        db_query = db_query.filter(Project.type_id == 1)

    if min_submit_ts is not None:
        cutoff_dt = datetime.utcfromtimestamp(min_submit_ts)
        db_query = db_query.filter(published_since(cutoff_dt))
    
    if min_score is not None and min_score > 0:
        db_query = db_query.filter(Project.ai_score >= min_score)
    # 如果 min_score 为 0，我们不加过滤条件，这样 ai_score 为 None 的新项目也能显示出来

    if max_score is not None and max_score > 0:
        # 使用 OR 条件包含 NULL 值，避免排除未评分的项目
        db_query = db_query.filter(
            or_(
                (Project.ai_score <= max_score),
                (Project.ai_score.is_(None))
            )
        )

    if budget_min is not None:
        db_query = db_query.filter(Project.budget_maximum >= budget_min)

    # 排序和分页
    db_query = db_query.order_by(Project.created_at.desc())
    db_projects = db_query.offset(offset).limit(limit).all()

    return [p.to_dict() for p in db_projects]

async def get_project_details(db: Session, project_id: int) -> Dict[str, Any]:
    """
    Get project details from API and sync to DB.
    """
    client = get_freelancer_client()

    # Use full_description and user_details parameters
    project_details = create_get_projects_project_details_object(full_description=True, jobs=True)
    user_details = create_get_projects_user_details_object(
        basic=True,
        reputation=True,
        employer_reputation=True
    )

    project_data = await client.get_project(
        project_id,
        project_details=project_details,
        user_details=user_details
    )

    project = db.query(Project).filter_by(freelancer_id=project_id).first()

    if project is None:
        project = Project(freelancer_id=project_id)
        db.add(project)
    _apply_project_fields(project, project_data)

    db.commit()
    db.refresh(project)
    return project.to_dict()

def update_project_ai_analysis(

    db: Session,

    project_id: int,

    ai_score: float,

    ai_reason: str,

    ai_proposal_draft: str,

    suggested_bid: Optional[float] = None,

    estimated_hours: Optional[int] = None,

    hourly_rate: Optional[float] = None,
    score_metadata: Optional[Dict[str, Any]] = None

) -> Optional[Dict[str, Any]]:

    """

    Update local project with AI analysis data.

    """

    project = db.query(Project).filter_by(freelancer_id=project_id).first()

    if not project:

        return None



    project.ai_score = ai_score

    project.ai_reason = ai_reason

    project.ai_proposal_draft = ai_proposal_draft

    project.suggested_bid = suggested_bid

    project.estimated_hours = estimated_hours

    project.hourly_rate = hourly_rate
    metadata = score_metadata or {"source": "manual", "total": ai_score}
    project.score_metadata = json.dumps(metadata, ensure_ascii=False, allow_nan=False)
    project.scored_at = datetime.now(timezone.utc).replace(tzinfo=None)

    project.updated_at = datetime.utcnow()



    if metadata.get("source") == "llm":
        from services import workflow_service as workflow
        workflow.apply_score(db, project)
    db.commit()

    db.refresh(project)

    return project.to_dict()
