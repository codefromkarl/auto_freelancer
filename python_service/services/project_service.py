from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging
import json

from database.models import Project
from services.freelancer_client import get_freelancer_client, FreelancerAPIError
from freelancersdk.resources.projects.helpers import (
    create_get_projects_project_details_object,
    create_get_projects_user_details_object
)
from config import settings
from utils.currency_converter import get_currency_converter

logger = logging.getLogger(__name__)


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
    enable_skill_match: bool = True
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
        'kept': 0
    }

    for project in projects_data:
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

async def search_projects(
    db: Session,
    query: Optional[str] = None,
    skills: Optional[List[int]] = None,
    budget_min: Optional[float] = None,
    budget_max: Optional[float] = None,
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    enable_pre_filter: bool = True  # 是否启用初筛
) -> List[Dict[str, Any]]:
    """
    Search projects via Freelancer API and store/update them in local DB.

    初筛流程：
    1. 调用搜索API获取项目列表
    2. 应用初筛规则（预算、描述长度、状态、技能匹配）
    3. 对筛选后的项目调用详情API
    4. 将详情数据入库

    Args:
        enable_pre_filter: 是否启用初筛，默认True
    """
    client = get_freelancer_client()

    # 1. Fetch from API (搜索结果)
    projects_data = await client.search_projects(
        query=query,
        skills=skills,
        budget_min=budget_min,
        budget_max=budget_max,
        status=status,
        limit=limit,
        offset=offset
    )

    stored_projects = []

    if projects_data:
        # 2. Pre-filter projects based on criteria
        if enable_pre_filter:
            filtered_projects, filter_stats = _pre_filter_projects(
                projects_data=projects_data,
                budget_min_threshold=settings.MIN_BUDGET_THRESHOLD,
                min_desc_length=settings.MIN_DESCRIPTION_LENGTH,
                allowed_statuses=settings.ALLOWED_STATUSES,
                enable_skill_match=True
            )

            logger.info(f"Pre-filter applied: {filter_stats['total']} -> {filter_stats['kept']} projects kept")

            # 3. 对筛选后的项目调用详情API，获取完整数据
            projects_to_store = []
            
            # 准备 SDK 详情请求参数
            proj_details_obj = create_get_projects_project_details_object(
                full_description=True,
                bid_stats=True
            )
            user_details_obj = create_get_projects_user_details_object(
                basic=True,
                details=True,
                reputation=True,
                employer_reputation=True
            )

            for project in filtered_projects:
                project_id = project.get('id')
                if project_id:
                    try:
                        # 获取完整的项目详情（包含bid_stats、owner_info）
                        # 使用 SDK 获取基础详情
                        detail = await client.get_project(
                            project_id,
                            project_details=proj_details_obj,
                            user_details=user_details_obj
                        )
                        
                        if detail:
                            # 强化：如果 SDK 返回的描述仍然不全（可能受限），尝试通过 HTTP 直接拉取全文
                            if len(detail.get('description', '')) < 200:
                                full_desc = await client._fetch_full_description(project_id)
                                if full_desc and len(full_desc) > len(detail.get('description', '')):
                                    detail['description'] = full_desc
                                    logger.info(f"  Enriched project {project_id} with full HTTP description")

                            detail['pre_filtered'] = True
                            projects_to_store.append(detail)
                            logger.info(f"  Fetched full details for project {project_id}")
                        else:
                            logger.warning(f"  Empty details for project {project_id}, skipping")
                    except Exception as e:
                        logger.warning(f"  Failed to fetch details for project {project_id}: {e}, skipping")
        else:
            # 不使用初筛，直接使用搜索结果
            projects_to_store = projects_data

        # 4. Extract IDs to check existence
        project_ids = [p.get('id') for p in projects_to_store if p.get('id')]

        # Batch query existing projects to avoid duplicates
        existing_ids = set()
        if project_ids:
            results = db.query(Project.freelancer_id).filter(Project.freelancer_id.in_(project_ids)).all()
            existing_ids = {r[0] for r in results}

        new_projects = []
        for project_dict in projects_to_store:
            project_id = project_dict.get('id')

            if project_id and project_id not in existing_ids:
                # Prepare JSON fields
                bid_stats = json.dumps(project_dict.get('bid_stats', {})) if project_dict.get('bid_stats') else None
                owner_info = json.dumps(project_dict.get('owner_info', {})) if project_dict.get('owner_info') else None

                # Create new project record
                project = Project(
                    freelancer_id=project_id,
                    title=project_dict.get('title', ''),
                    description=project_dict.get('full_description') or project_dict.get('description'),
                    preview_description=project_dict.get('preview_description'),
                    budget_minimum=project_dict.get('budget', {}).get('minimum'),
                    budget_maximum=project_dict.get('budget', {}).get('maximum'),
                    currency_code=project_dict.get('currency', {}).get('code', 'USD'),
                    submitdate=project_dict.get('submitdate'),
                    status=project_dict.get('status', 'open'),
                    type_id=project_dict.get('type_id'),
                    skills=str(project_dict.get('jobs', [])),
                    owner_id=project_dict.get('owner_id'),
                    country=project_dict.get('country', {}).get('name'),
                    deadline=project_dict.get('deadline'),
                    bid_stats=bid_stats,
                    owner_info=owner_info,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )

                new_projects.append(project)
                stored_projects.append(project.to_dict())
            elif project_id in existing_ids:
                # Optionally return existing projects if they match search
                pass

        if new_projects:
            db.add_all(new_projects)
            db.commit()

    return stored_projects

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
