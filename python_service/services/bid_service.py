from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
import re
import logging

logger = logging.getLogger(__name__)

from database.models import Bid, Project, AuditLog
from services.freelancer_client import get_freelancer_client, FreelancerAPIError
from services.proposal_service import get_proposal_service, ProposalService


def check_content_risk(description: str, project: Project) -> Tuple[bool, str]:
    """
    检查投标内容的风险

    返回: (是否允许, 风险原因)
    """
    reasons = []

    # 1. 长度检查
    if len(description) < 100:
        reasons.append("描述过短（少于100字符）")
        return False, "，".join(reasons)
    if len(description) > 3000:
        reasons.append("描述过长（超过3000字符）")
        return False, "，".join(reasons)

    # 2. AI 模板化内容检测（检测常见AI生成模板）
    common_phrases = [
        "我有丰富的经验",
        "了解您的需求",
        "这正是我的专长领域",
        "我可以提供完整的解决方案",
        "我将仔细分析需求",
        "包括需求分析、开发、测试和部署",
        "基于我的相关经验",
        "作为一名经验丰富的开发者",
        "我的技术栈包括",
        "能够快速交付高质量结果",
    ]
    common_count = sum(1 for phrase in common_phrases if phrase in description)
    if common_count >= 3:
        reasons.append(f"AI 模板化内容过多 ({common_count}处)")
        return False, "，".join(reasons)

    # 3. 关键词堆砌检测
    tech_keywords = [
        "python",
        "fastapi",
        "n8n",
        "api",
        "automation",
        "workflow",
        "django",
        "flask",
    ]
    description_lower = description.lower()
    words = re.findall(r"\b\w+\b", description_lower)

    # 检查关键词密度（关键词数量 / 总词数）
    if len(words) > 20:
        keyword_count = sum(1 for k in tech_keywords if k in description_lower)
        if keyword_count / len(words) > 0.35:  # 超过35%关键词密度
            reasons.append("关键词堆砌过密（缺乏自然表达）")
            return False, "，".join(reasons)

    # 4. 与项目描述的匹配度检查
    project_desc = (project.description or "").lower()
    if project.title:
        title_words = set(project.title.lower().split())
        bid_words = set(description.lower().split())
        common_words = title_words & bid_words
        if len(common_words) < 3 and len(title_words) > 5:  # 引用项目词汇太少
            reasons.append("与项目描述关联度低（缺乏针对性）")
            return False, "，".join(reasons)

    # 5. 预算合理性检查
    if project.budget_minimum and project.budget_maximum:
        avg_budget = (float(project.budget_minimum) + float(project.budget_maximum)) / 2

        # 检查是否提及预算
        if "预算" not in description_lower and "budget" not in description_lower:
            reasons.append(
                f"未提及预算范围 ({project.budget_minimum}-{project.budget_maximum} USD)"
            )
            return False, "，".join(reasons)

        # 检查报价是否合理（上下浮动20-30%）
        suggested = (
            float(project.suggested_bid) if project.suggested_bid else avg_budget * 0.7
        )

        # 注意：这里检查的是"我"句中的数字，不是整体报价
        amount_match = re.search(r"报价\D*(\d+\.?\d*)", description)
        if amount_match:
            quoted_amount = float(amount_match.group(1))
            if quoted_amount < avg_budget * 0.6 or quoted_amount > avg_budget * 1.3:
                reasons.append(f"报价异常（{quoted_amount} vs 预算 {avg_budget:.0f}）")
                return False, "，".join(reasons)

    # 6. 结构化检查（是否包含技术方案、交付计划）
    required_sections = [
        "方案",
        "计划",
        "技术",
        "实现",
        "交付",
        "架构",
        "plan",
        "technical",
        "implementation",
        "delivery",
        "architecture",
        "approach",
        "solution",
    ]
    has_sections = sum(1 for s in required_sections if s.lower() in description.lower())
    if has_sections < 2:
        reasons.append("缺乏结构化表达（技术方案/交付计划）")
        return False, "，".join(reasons)

    # 7. 重复句式检测
    sentences = description.split("。")
    unique_sentences = set()
    duplicate_count = 0
    for s in sentences:
        s_clean = s.strip()
        if s_clean:
            if s_clean in unique_sentences:
                duplicate_count += 1
            unique_sentences.add(s_clean)

    if duplicate_count >= 2 and len(sentences) > 3:
        reasons.append(f"存在重复句式 ({duplicate_count}处)")
        return False, "，".join(reasons)

    return True, "通过"


async def create_bid(
    db: Session,
    project_id: int,
    amount: float,
    period: int,
    description: Optional[str] = None,
    skip_content_check: bool = False,
) -> Dict[str, Any]:
    """
    Submit a bid to Freelancer and record it.
    """
    # 1. Check local project existence
    project = db.query(Project).filter_by(freelancer_id=project_id).first()
    if not project:
        raise ValueError(
            "Project not found in database. Please sync with Freelancer API first."
        )

    # 2. Determine description (use AI draft from ProposalService if not provided)
    bid_description = description
    if not bid_description:
        # 使用新的 ProposalService 生成提案
        try:
            proposal_service = get_proposal_service()
            proposal_result = await proposal_service.generate_proposal(project)
            if proposal_result.get("success"):
                bid_description = proposal_result.get("proposal", "")
                # 保存生成的提案到项目记录
                if bid_description:
                    project.ai_proposal_draft = bid_description
                    db.commit()
        except Exception as e:
            logger.warning(f"Failed to generate proposal using ProposalService: {e}")
            # 回退到数据库中的现有提案
            bid_description = (
                project.ai_proposal_draft if project.ai_proposal_draft else ""
            )

    # 3. 检查投标内容风险（除非跳过检查）
    if not skip_content_check and bid_description:
        content_safe, risk_reason = check_content_risk(bid_description, project)
        if not content_safe:
            # 记录内容风控审计日志
            audit = AuditLog(
                action="content_risk_check",
                entity_type="bid",
                entity_id=project_id,
                request_data=f"description_length={len(bid_description)}",
                response_data=f"BLOCKED: {risk_reason}",
                status="blocked",
                error_message=risk_reason,
            )
            db.add(audit)
            db.commit()

            raise ValueError(f"投标内容未通过风控检查: {risk_reason}")

    if not bid_description:
        raise ValueError("Bid description is required and no AI draft is available.")

    # 4. Call External API
    client = get_freelancer_client()
    try:
        result = await client.create_bid(
            project_id=project_id,
            amount=amount,
            period=period,
            description=bid_description,
        )
    except FreelancerAPIError as e:
        # Log failure
        audit = AuditLog(
            action="create_bid",
            entity_type="bid",
            entity_id=project_id,  # Using project ID as proxy entity ID for failed bid
            request_data=f"amount={amount}, period={period}",
            response_data=e.message,
            status="error",
            error_message=e.message,
        )
        db.add(audit)
        db.commit()
        raise e

    # 5. Save to DB on success
    bid = Bid(
        freelancer_bid_id=result.get("bid_id", {}).get("id") if result else 0,
        project_id=project.id,
        project_freelancer_id=project_id,
        bidder_id=result.get("bidder_id", {}).get("id") if result else 0,
        amount=amount,
        period=period,
        description=bid_description,
        status="active",
        submitdate=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    )
    db.add(bid)

    # Audit log
    audit = AuditLog(
        action="create_bid",
        entity_type="bid",
        entity_id=bid.freelancer_bid_id,
        request_data=f"amount={amount}, period={period}",
        response_data=str(result),
        status="success",
    )
    db.add(audit)
    db.commit()
    db.refresh(bid)

    return {
        "bid_id": bid.freelancer_bid_id,
        "project_id": project_id,
        "amount": amount,
        "period": period,
        "description": bid_description,
        "status": "submitted",
    }


def get_user_bids(
    db: Session, status: Optional[str] = None, limit: int = 50, offset: int = 0
) -> Dict[str, Any]:
    query = db.query(Bid)
    if status:
        query = query.filter(Bid.status == status)

    total = query.count()
    bids = query.order_by(Bid.created_at.desc()).offset(offset).limit(limit).all()

    return {"data": [bid.to_dict() for bid in bids], "total": total}


def get_bid_details(db: Session, bid_id: int) -> Optional[Dict[str, Any]]:
    bid = db.query(Bid).filter_by(freelancer_bid_id=bid_id).first()
    return bid.to_dict() if bid else None


async def update_bid(
    db: Session,
    bid_id: int,
    amount: Optional[float] = None,
    period: Optional[int] = None,
    description: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    client = get_freelancer_client()

    # Check existence first
    bid = db.query(Bid).filter_by(freelancer_bid_id=bid_id).first()
    if not bid:
        return None

    # Call API
    try:
        result = await client.update_bid(
            bid_id=bid_id, amount=amount, period=period, description=description
        )
    except FreelancerAPIError as e:
        audit = AuditLog(
            action="update_bid",
            entity_type="bid",
            entity_id=bid_id,
            request_data=f"update_failed",
            response_data=e.message,
            status="error",
            error_message=e.message,
        )
        db.add(audit)
        db.commit()
        raise e

    # Update DB
    if amount is not None:
        bid.amount = amount
    if period is not None:
        bid.period = period
    if description is not None:
        bid.description = description
    bid.updated_at = datetime.utcnow()

    audit = AuditLog(
        action="update_bid",
        entity_type="bid",
        entity_id=bid_id,
        request_data=f"amount={amount}, period={period}",
        response_data=str(result),
        status="success",
    )
    db.add(audit)
    db.commit()
    db.refresh(bid)

    return bid.to_dict()


async def retract_bid(db: Session, bid_id: int) -> bool:
    client = get_freelancer_client()

    try:
        result = await client.retract_bid(id_id)
    except FreelancerAPIError as e:
        audit = AuditLog(
            action="retract_bid",
            entity_type="bid",
            entity_id=bid_id,
            request_data="",
            response_data=e.message,
            status="error",
            error_message=e.message,
        )
        db.add(audit)
        db.commit()
        raise e

    bid = db.query(Bid).filter_by(freelancer_bid_id=bid_id).first()
    if bid:
        bid.status = "withdrawn"
        bid.updated_at = datetime.utcnow()

        audit = AuditLog(
            action="retract_bid",
            entity_type="bid",
            entity_id=bid_id,
            request_data="",
            response_data=str(result),
            status="success",
        )
        db.add(audit)
        db.commit()
        return True

    return False
