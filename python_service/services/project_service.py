from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import logging
import json
import asyncio

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
_STICKY_LOCAL_STATUSES = {"bid_submitted", "skills_blocked"}


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
    description = (project_dict.get('preview_description') or project_dict.get('description') or '').lower()
    project_jobs = project_dict.get('jobs', [])

    # 收集所有简历技能关键词
    all_keywords = []
    for keywords in settings.RESUME_SKILL_MAPPINGS.values():
        all_keywords.extend(keywords)

    # 检查标题和描述中是否包含简历关键词
    text_content = f"{title} {description}"
    text_match = any(keyword in text_content for keyword in all_keywords)

    # 如果文本匹配成功，直接返回
    if text_match:
        return True

    # 检查技能ID匹配（如果有技能ID数据）
    # 注意：Freelancer API返回的jobs可能是技能ID或技能名称
    if project_jobs:
        for job in project_jobs:
            job_str = str(job).lower()
            if any(keyword in job_str for keyword in all_keywords):
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
        'kept': 0
    }

    for project in projects_data:
        # 0.5 计费类型筛选（默认只保留 fixed 一次性项目）
        if fixed_price_only:
            project_type = str(project.get("type") or "").lower()
            if project_type and project_type != "fixed":
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
            budget_info = project.get('budget', {})
            budget_max = budget_info.get('maximum') or budget_info.get('minimum', 0)
            currency_code = project.get('currency', {}).get('code', 'USD')
            
            # 使用动态汇率转换
            converter = get_currency_converter()
            currency_rate = converter.get_rate_sync(currency_code)
            if currency_rate is None:
                logger.warning(
                    "Currency rate missing for %s; skipping budget filter",
                    currency_code,
                )
                budget_usd = None
            else:
                budget_usd = budget_max * currency_rate

            if budget_usd is not None and budget_usd < budget_min_threshold:
                stats['filtered_budget'] += 1
                logger.debug(f"Filtered by budget: {project.get('title')} (budget: {budget_usd:.2f} USD < {budget_min_threshold})")
                continue

        # 2. 描述长度筛选
        if min_desc_length is not None:
            description = project.get('preview_description') or project.get('description') or ''
            if len(description) < min_desc_length:
                stats['filtered_desc'] += 1
                logger.debug(f"Filtered by description length: {project.get('title')} (length: {len(description)} < {min_desc_length})")
                continue

        # 3. 状态筛选
        if allowed_statuses is not None:
            status = project.get('status', '').lower()
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


def _apply_project_fields(project: Project, project_dict: Dict[str, Any]) -> None:
    """
    Apply mutable fields from API payload to local Project row.
    """
    budget = project_dict.get("budget", {}) or {}
    currency = project_dict.get("currency", {}) or {}

    project.title = project_dict.get("title", project.title or "")
    project.preview_description = project_dict.get(
        "preview_description", project.preview_description
    )
    project.description = project_dict.get("description", project.description)
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
    project.owner_id = project_dict.get("owner_id", project.owner_id)
    submitdate = project_dict.get("submitdate")
    if submitdate is not None:
        project.submitdate = str(submitdate)
    project.updated_at = datetime.utcnow()


def _parse_submit_timestamp(raw_submitdate: Any) -> Optional[int]:
    """Parse project submitdate from multiple possible formats into unix timestamp(seconds)."""
    if raw_submitdate is None:
        return None

    # int/float unix timestamp
    if isinstance(raw_submitdate, (int, float)):
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
        min_submit_ts = int((datetime.utcnow() - timedelta(days=since_days)).timestamp())
    
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

                if p_data:
                    filtered_projects, _ = _pre_filter_projects(
                        projects_data=p_data,
                        budget_min_threshold=settings.MIN_BUDGET_THRESHOLD,
                        min_desc_length=settings.MIN_DESCRIPTION_LENGTH,
                        allowed_statuses=normalized_allowed_statuses,
                        enable_skill_match=True,
                        min_submit_ts=min_submit_ts,
                        fixed_price_only=fixed_price_only,
                    )

                    with get_db_session() as background_db:
                        for project_dict in filtered_projects:
                            pid = project_dict.get('id')
                            if not pid: continue

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
                        background_db.commit()
                logger.info(f"Background sync completed successfully for query: {query}")
            except Exception as e:
                logger.error(f"Background sync failed: {e}")
            finally:
                _is_syncing = False
                logger.info("Background sync lock released")

    # 2. 构建本地数据库查询
    db_query = db.query(Project)

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
        db_query = db_query.filter(Project.created_at >= cutoff_dt)
    
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
    project_details = create_get_projects_project_details_object(full_description=True)
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

    if project:
        # Update existing record
        project.title = project_data.get('title', project.title)
        project.description = project_data.get('description', project.description)
        project.status = project_data.get('status', project.status)
        project.updated_at = datetime.utcnow()

        if 'full_description' in project_data:
            project.full_description = project_data['full_description']
    else:
        # Create new record
        project = Project(
            freelancer_id=project_id,
            title=project_data.get('title', ''),
            description=project_data.get('description'),
            preview_description=project_data.get('preview_description'),
            budget_minimum=project_data.get('budget', {}).get('minimum'),
            budget_maximum=project_data.get('budget', {}).get('maximum'),
            currency_code=project_data.get('currency', {}).get('code', 'USD'),
            submitdate=project_data.get('submitdate'),
            status=project_data.get('status', 'open'),
            type_id=project_data.get('type_id'),
            owner_id=project_data.get('owner_id'),
            country=project_data.get('country', {}).get('name')
        )

        if 'full_description' in project_data:
            project.full_description = project_data['full_description']

        db.add(project)

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

    hourly_rate: Optional[float] = None

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

    project.updated_at = datetime.utcnow()



    db.commit()

    db.refresh(project)

    return project.to_dict()
