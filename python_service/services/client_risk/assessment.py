"""
ClientRiskAssessment 统一入口（方向四：客户尽职调查与风控盾）。

该模块负责把：
- FreelancerClient 的用户数据（get_user / get_user_reviews）
- 硬规则过滤引擎（hard_rules）
- LLM 软分析（llm_client.analyze_client_risk）
组合成一次“可落库、可审计、可解释”的风险评估。

重要设计点：
1) 先硬规则 gate：不通过则直接拦截，避免不必要的 LLM 成本
2) 数据持久化：Client / ClientFeatureSnapshot / ClientRiskAssessment 三表齐全，便于复盘与策略迭代
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from config import settings
from database.models import Client, ClientFeatureSnapshot, ClientRiskAssessment, Project
from services.freelancer_client import get_freelancer_client
from services.llm_client import get_llm_client, LLMClientProtocol
from services.client_risk.hard_rules import evaluate_hard_rules
from services.client_risk.llm_analysis import normalize_client_risk_llm_output

logger = logging.getLogger(__name__)


def _clamp_score(score: int) -> int:
    """把分数裁剪到 0-100。"""
    return max(0, min(100, score))


def _flag_to_reason(flag: str) -> str:
    """把硬规则 flag 转换为可读原因（中文）。"""
    mapping = {
        "PAYMENT_NOT_VERIFIED": "客户未完成付款验证（payment_verified=false）。",
        "DEPOSIT_NOT_MADE": "客户未缴纳押金/保证金（deposit_made=false）。",
        "COUNTRY_BLOCKED": "客户国家/地区命中 denylist（高风险区域）。",
        "ZERO_REVIEWS_AFTER_POSTING": "客户发布过多个项目但评价数为 0（异常信誉画像）。",
        "LOW_HIRE_RATE": "客户 Hire Rate 过低且样本量足够（疑似低意向/低质量雇主）。",
    }
    return mapping.get(flag, f"命中硬规则：{flag}")


def _compute_base_risk_from_flags(flags: list[str]) -> int:
    """
    根据硬规则 flags 计算基础风险分（0-100）。

    说明：
    - 这里给出一个“保守可用”的默认策略（可在后续引入 risk_policy_version 做版本化）
    - 该分数会与 LLM risk_delta 叠加，得到最终 Client_Risk_Score
    """
    score = 20  # 默认基础风险（即使硬规则全通过，也不意味着绝对低风险）

    weights = {
        "PAYMENT_NOT_VERIFIED": 30,
        "DEPOSIT_NOT_MADE": 25,
        "COUNTRY_BLOCKED": 60,
        "ZERO_REVIEWS_AFTER_POSTING": 15,
        "LOW_HIRE_RATE": 20,
    }
    for f in flags:
        score += weights.get(f, 0)
    return _clamp_score(score)


def _extract_user_features(user: Dict[str, Any]) -> Dict[str, Any]:
    """
    从 getUser 返回中抽取（并轻量归一化）可用于风控的特征集合。

    说明：
    - 这里不追求穷举字段，优先满足“硬规则 + 软分析 + 落库复盘”所需
    - 不同 API/SDK 返回字段可能差异较大，因此需要容错
    """
    jobs_posted = int(user.get("jobs_posted") or 0)
    jobs_hired = int(user.get("jobs_hired") or 0)

    # hire_rate：若缺失则尝试推导
    hire_rate = user.get("hire_rate")
    if hire_rate is None and jobs_posted > 0:
        hire_rate = jobs_hired / jobs_posted

    try:
        hire_rate_f = float(hire_rate) if hire_rate is not None else None
    except Exception:
        hire_rate_f = None

    try:
        rating_f = float(user.get("rating")) if user.get("rating") is not None else None
    except Exception:
        rating_f = None

    review_count = int(user.get("review_count") or 0)

    features = {
        "id": user.get("id"),
        "username": user.get("username"),
        "payment_verified": user.get("payment_verified"),
        "deposit_made": user.get("deposit_made"),
        "verified": user.get("verified"),
        "country": user.get("country"),
        "country_name": user.get("country_name"),
        "jobs_posted": jobs_posted,
        "jobs_hired": jobs_hired,
        "hire_rate": hire_rate_f,
        "rating": rating_f,
        "review_count": review_count,
    }
    return features


async def assess_client_risk(
    *,
    user_id: int,
    project_id: Optional[int],
    db: Session,
    freelancer_client: Any = None,
    llm_client: Optional[LLMClientProtocol] = None,
) -> ClientRiskAssessment:
    """
    风控评估统一入口。

    输入：
    - user_id：Freelancer 雇主（客户）ID
    - project_id：触发评估的 Freelancer 项目 ID（可空）
    - db：SQLAlchemy Session（由上层传入，便于在同一事务内串联其它动作）

    输出：
    - ClientRiskAssessment ORM 对象（已写入数据库）
    """
    if user_id <= 0:
        raise ValueError("user_id must be positive")

    # 依赖注入：便于单元测试替换为 Fake 客户端
    fln = freelancer_client or get_freelancer_client()
    llm = llm_client or get_llm_client()

    # ---------------------------------------------------------------------
    # 1) 拉取用户信息，并抽取可用特征
    # ---------------------------------------------------------------------
    raw_user = await fln.get_user(user_id)
    features = _extract_user_features(raw_user)

    logger.info(f"[ClientRisk] fetched user={user_id} features={features}")

    # ---------------------------------------------------------------------
    # 2) Upsert Client（客户基础画像）
    # ---------------------------------------------------------------------
    client = db.query(Client).filter_by(freelancer_user_id=user_id).first()
    if not client:
        client = Client(freelancer_user_id=user_id, created_at=datetime.utcnow())
        db.add(client)

    client.username = str(features.get("username") or "") or None
    client.payment_verified = bool(features.get("payment_verified")) if features.get("payment_verified") is not None else False
    client.deposit_made = bool(features.get("deposit_made")) if features.get("deposit_made") is not None else False
    client.verified = bool(features.get("verified")) if features.get("verified") is not None else False
    client.country = str(features.get("country") or "").upper() or None
    client.country_name = str(features.get("country_name") or "") or None
    client.jobs_posted = int(features.get("jobs_posted") or 0)
    client.jobs_hired = int(features.get("jobs_hired") or 0)
    client.hire_rate = features.get("hire_rate")
    client.rating = features.get("rating")
    client.review_count = int(features.get("review_count") or 0)
    client.profile_raw_json = json.dumps(raw_user, ensure_ascii=False)
    client.last_seen_at = datetime.utcnow()
    client.updated_at = datetime.utcnow()

    db.flush()  # 需要 client.id 供后续快照/评估记录引用

    # ---------------------------------------------------------------------
    # 3) 硬规则 gate
    # ---------------------------------------------------------------------
    hard = evaluate_hard_rules(features)

    # 先创建 FeatureSnapshot：即使硬拦截，也要把画像落库便于复盘
    snapshot = ClientFeatureSnapshot(
        client_id=client.id,
        source="api",
        features_json=json.dumps(features, ensure_ascii=False),
        reviews_raw_json=None,  # gate 通过后再补（避免多一次 API 调用）
        collected_at=datetime.utcnow(),
        created_at=datetime.utcnow(),
    )
    db.add(snapshot)
    db.flush()

    # ---------------------------------------------------------------------
    # 4) gate 未通过：直接生成评估结果（不调用 LLM）
    # ---------------------------------------------------------------------
    if not hard.gate_passed:
        base_score = _compute_base_risk_from_flags(hard.flags)
        reasons = [_flag_to_reason(f) for f in hard.flags]

        assessment = ClientRiskAssessment(
            client_id=client.id,
            project_id=_map_project_id(db, project_id),
            risk_score=base_score,
            hard_flags_json=json.dumps(hard.flags, ensure_ascii=False),
            hard_gate_passed=False,
            llm_summary=None,
            llm_evidence_json=None,
            reasons_json=json.dumps(reasons, ensure_ascii=False),
            risk_policy_version="v1",
            model_provider=getattr(settings, "LLM_PROVIDER", "openai"),
            model_name=getattr(settings, "LLM_MODEL", None),
            created_at=datetime.utcnow(),
        )
        db.add(assessment)
        db.commit()
        db.refresh(assessment)
        return assessment

    # ---------------------------------------------------------------------
    # 5) gate 通过：拉取评价并进行 LLM 软分析
    # ---------------------------------------------------------------------
    reviews = await fln.get_user_reviews(user_id)
    snapshot.reviews_raw_json = json.dumps(reviews, ensure_ascii=False)
    db.flush()

    llm_raw = await llm.analyze_client_risk(user=features, reviews=reviews)
    llm_norm = normalize_client_risk_llm_output(llm_raw)

    base_score = _compute_base_risk_from_flags(hard.flags)
    final_score = _clamp_score(int(base_score + int(llm_norm.get("risk_delta", 0))))

    reasons = []
    reasons.extend([_flag_to_reason(f) for f in hard.flags])
    reasons.extend(llm_norm.get("reasons") or [])

    assessment = ClientRiskAssessment(
        client_id=client.id,
        project_id=_map_project_id(db, project_id),
        risk_score=final_score,
        hard_flags_json=json.dumps(hard.flags, ensure_ascii=False),
        hard_gate_passed=True,
        llm_summary=str(llm_norm.get("summary") or "").strip() or None,
        llm_evidence_json=json.dumps(llm_norm, ensure_ascii=False),
        reasons_json=json.dumps(reasons, ensure_ascii=False),
        risk_policy_version="v1",
        model_provider=getattr(settings, "LLM_PROVIDER", "openai"),
        model_name=getattr(settings, "LLM_MODEL", None),
        created_at=datetime.utcnow(),
    )
    db.add(assessment)
    db.commit()
    db.refresh(assessment)
    return assessment


def _map_project_id(db: Session, freelancer_project_id: Optional[int]) -> Optional[int]:
    """
    将传入的 Freelancer 项目 ID 映射为本地 projects 表的主键 ID。

    说明：
    - ClientRiskAssessment.project_id 外键指向 projects.id（本地主键）
    - 外部调用方更常传入 Freelancer 的项目 ID（projects.freelancer_id）
    - 若未找到对应 Project，则返回 None（避免外键约束风险）
    """
    if freelancer_project_id is None:
        return None

    try:
        pid = int(freelancer_project_id)
    except Exception:
        return None

    project = db.query(Project).filter_by(freelancer_id=pid).first()
    if project:
        return int(project.id)
    return None

