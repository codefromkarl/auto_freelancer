"""
Client Risk API endpoints (方向四：客户尽职调查与风控盾).

提供以下功能：
- 客户风控评估入口 (POST /assess)
- 查询客户风控历史 (GET /{user_id})
- 格式化 Telegram 报告 (GET /telegram-report/{assessment_id})
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List, Any
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import Client, ClientRiskAssessment
from services.client_risk.assessment import assess_client_risk

router = APIRouter()


# =============================================================================
# Pydantic Models for Request/Response
# =============================================================================

class ClientRiskAssessRequest(BaseModel):
    """客户风控评估请求."""
    user_id: int = Field(..., description="Freelancer 雇主用户 ID", ge=1)
    project_id: Optional[int] = Field(None, description="触发评估的项目 ID（可选）")


class ClientRiskAssessResponse(BaseModel):
    """客户风控评估响应."""
    id: int
    client_id: int
    project_id: Optional[int]
    freelancer_user_id: int
    username: Optional[str]

    # 风控结果
    risk_score: int = Field(..., description="风险评分 0-100（越高越风险）")
    hard_gate_passed: bool = Field(..., description="是否通过硬规则门禁")
    hard_flags: List[str] = Field(default_factory=list, description="触发的硬规则标识")

    # LLM 分析
    llm_summary: Optional[str] = Field(None, description="LLM 风控摘要")
    llm_evidence: Optional[dict] = Field(None, description="LLM 分析证据")

    # 客户基本信息（用于快速查看）
    country: Optional[str]
    payment_verified: bool
    deposit_made: bool
    hire_rate: Optional[float]
    rating: Optional[float]
    review_count: int

    # 元数据
    risk_policy_version: str
    model_provider: str
    model_name: Optional[str]
    created_at: str


class ClientRiskHistoryResponse(BaseModel):
    """客户风控历史响应."""
    user_id: int
    username: Optional[str]
    assessments: List[dict]


class APIResponse(BaseModel):
    """标准 API 响应包装."""
    status: str
    data: Any
    message: Optional[str] = None


# =============================================================================
# API Endpoints
# =============================================================================

@router.post("/assess", response_model=APIResponse)
async def assess_client_risk_endpoint(
    request: ClientRiskAssessRequest,
    db: Session = Depends(get_db)
):
    """
    客户风控评估入口。

    调用 assess_client_risk 进行完整的风控评估：
    1. 硬规则过滤 (Hard Gate)
    2. LLM 软分析 (Soft Analysis)
    3. 数据持久化

    返回 ClientRiskAssessment 对象（包含评分、flags、LLM 分析等）。
    """
    try:
        assessment = await assess_client_risk(
            user_id=request.user_id,
            project_id=request.project_id,
            db=db
        )

        # 获取客户信息用于响应
        client = db.query(Client).filter_by(id=assessment.client_id).first()
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")

        response_data = ClientRiskAssessResponse(
            id=assessment.id,
            client_id=assessment.client_id,
            project_id=assessment.project_id,
            freelancer_user_id=client.freelancer_user_id,
            username=client.username,
            risk_score=assessment.risk_score,
            hard_gate_passed=assessment.hard_gate_passed,
            hard_flags=[],
            llm_summary=assessment.llm_summary,
            llm_evidence=None,
            country=client.country,
            payment_verified=client.payment_verified,
            deposit_made=client.deposit_made,
            hire_rate=client.hire_rate,
            rating=client.rating,
            review_count=client.review_count,
            risk_policy_version=assessment.risk_policy_version,
            model_provider=assessment.model_provider,
            model_name=assessment.model_name,
            created_at=assessment.created_at.isoformat() if assessment.created_at else None,
        )

        # 解析 hard_flags 和 llm_evidence
        import json
        if assessment.hard_flags_json:
            try:
                response_data.hard_flags = json.loads(assessment.hard_flags_json)
            except:
                pass
        if assessment.llm_evidence_json:
            try:
                response_data.llm_evidence = json.loads(assessment.llm_evidence_json)
            except:
                pass

        return APIResponse(status="success", data=response_data.dict())

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Risk assessment failed: {str(e)}")


@router.get("/{user_id}", response_model=APIResponse)
async def get_client_risk_history(
    user_id: int,
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db)
):
    """
    查询客户风控历史。

    返回指定用户的最近风控评估记录（按时间倒序）。
    """
    try:
        # 查找客户记录
        client = db.query(Client).filter_by(freelancer_user_id=user_id).first()
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")

        # 查询风控评估历史
        assessments = db.query(ClientRiskAssessment).filter_by(
            client_id=client.id
        ).order_by(
            ClientRiskAssessment.created_at.desc()
        ).limit(limit).all()

        assessments_data = [assessment.to_dict() for assessment in assessments]

        response_data = ClientRiskHistoryResponse(
            user_id=user_id,
            username=client.username,
            assessments=assessments_data
        )

        return APIResponse(status="success", data=response_data.dict())

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch risk history: {str(e)}")


@router.get("/telegram-report/{assessment_id}")
async def get_telegram_risk_report(
    assessment_id: int,
    db: Session = Depends(get_db)
):
    """
    生成 Telegram 格式的风控报告。

    返回格式化的文本，可直接发送到 Telegram Bot。
    """
    try:
        # 查询风控评估记录
        assessment = db.query(ClientRiskAssessment).filter_by(id=assessment_id).first()
        if not assessment:
            raise HTTPException(status_code=404, detail="Assessment not found")

        # 获取客户信息
        client = db.query(Client).filter_by(id=assessment.client_id).first()
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")

        # 解析 flags
        import json
        hard_flags = []
        if assessment.hard_flags_json:
            try:
                hard_flags = json.loads(assessment.hard_flags_json)
            except:
                pass

        # 解析 LLM evidence
        llm_evidence = {}
        if assessment.llm_evidence_json:
            try:
                llm_evidence = json.loads(assessment.llm_evidence_json)
            except:
                pass

        # 解析 reasons
        reasons = []
        if assessment.reasons_json:
            try:
                reasons = json.loads(assessment.reasons_json)
            except:
                pass

        # 构建报告
        # 国家名称映射
        country_names = {
            "US": "🇺🇸 美国", "GB": "🇬🇧 英国", "CA": "🇨🇦 加拿大",
            "AU": "🇦🇺 澳洲", "DE": "🇩🇪 德国", "FR": "🇫🇷 法国",
        }
        country_display = country_names.get(client.country, client.country or "未知")

        # 支付验证状态
        payment_status = "✅ 已验证" if client.payment_verified else "❌ 未验证"
        deposit_status = "✅ 已托管" if client.deposit_made else "❌ 未托管"

        # Hire Rate 显示
        hire_rate_display = f"{int((client.hire_rate or 0) * 100)}%" if client.hire_rate else "N/A"

        # 评分显示
        rating_display = f"{client.rating:.1f}/5.0" if client.rating else "N/A"

        # 风险等级判断
        risk_level = "🔴 高风险" if assessment.risk_score >= 80 else \
                   "🟡 中风险" if assessment.risk_score >= 50 else "🟢 低风险"

        # 建议操作
        if not assessment.hard_gate_passed or assessment.risk_score >= 80:
            recommendation = "⛔ 建议跳过"
        elif assessment.risk_score >= 50:
            recommendation = "⚠️ 需人工确认"
        else:
            recommendation = "✅ 可投标"

        # 构建 Telegram 消息
        report_lines = [
            "🛡️ <b>客户风控报告</b>",
            "",
            f"👤 <b>客户</b>: @{client.username or 'N/A'} (ID: {client.freelancer_user_id})",
            f"🌍 <b>国家</b>: {country_display}",
            f"💳 <b>支付验证</b>: {payment_status}",
            f"💰 <b>资金托管</b>: {deposit_status}",
            f"📊 <b>Hire Rate</b>: {hire_rate_display}",
            f"⭐ <b>评分</b>: {rating_display} ({client.review_count} 条评价)",
            f"🔥 <b>风险评分</b>: {assessment.risk_score}/100 - {risk_level}",
            "",
        ]

        # 硬规则
        if hard_flags:
            report_lines.append(f"⚠️ <b>硬规则触发</b>: {', '.join(hard_flags)}")
        else:
            report_lines.append("✅ <b>硬规则</b>: 无触发")

        # LLM 分析
        if assessment.llm_summary:
            report_lines.append(f"📝 <b>LLM 分析</b>: {assessment.llm_summary}")

        # 推荐操作
        report_lines.extend([
            "",
            f"🎯 <b>建议操作</b>: {recommendation}",
            "",
            f"<i>评估时间: {assessment.created_at.strftime('%Y-%m-%d %H:%M:%S') if assessment.created_at else 'N/A'}</i>"
        ])

        return {
            "status": "success",
            "data": {
                "text": "\n".join(report_lines),
                "parse_mode": "HTML",
                "risk_score": assessment.risk_score,
                "hard_gate_passed": assessment.hard_gate_passed,
                "recommendation": "skip" if not assessment.hard_gate_passed or assessment.risk_score >= 80 else \
                               "review" if assessment.risk_score >= 50 else "bid"
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate report: {str(e)}")
