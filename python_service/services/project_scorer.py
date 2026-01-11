"""
Project scoring service for evaluating Freelancer projects (10-point scale).

Each dimension is scored 0-10, then weighted to produce total score 0-10.

Design Principles:
- Dependency Injection: No global singletons for better testability
- Strategy Pattern: Pluggable scoring strategies
- Factory Pattern: Easy scorer creation with custom configurations

IMPORTANT: This module supports both dependency injection and singleton access.
For convenience, use `get_project_scorer()` which maintains a singleton internally.
For testing, use `create_project_scorer()` to create fresh instances
or `reset_singleton()` to clear cached state.
"""

import logging
import time
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from enum import Enum

from config import settings
from utils.currency_converter import get_currency_converter

logger = logging.getLogger(__name__)


DEFAULT_WEIGHTS = {
    "budget_efficiency": 0.15,
    "competition": 0.25,
    "clarity": 0.25,
    "customer": 0.20,
    "tech": 0.10,
    "risk": 0.05,
}


class ProjectComplexity(Enum):
    TRIVIAL = (1, 4)
    SMALL = (4, 20)
    MEDIUM = (20, 80)
    LARGE = (80, 200)


@dataclass
class ScoreBreakdown:
    """Breakdown of scores by category (each 0-10)."""

    budget_efficiency_score: float = 0.0
    estimated_hours: int = 0
    hourly_rate: float = 0.0
    competition_score: float = 0.0
    clarity_score: float = 0.0
    customer_score: float = 0.0
    tech_score: float = 0.0
    risk_score: float = 0.0


@dataclass
class ProjectScore:
    """Complete project score with analysis."""

    project_id: int
    ai_score: float
    ai_grade: str
    ai_reason: str
    ai_proposal_draft: str
    score_breakdown: ScoreBreakdown


@dataclass
class ScoringConfig:
    """
    评分配置（依赖注入友好）。

    设计用于支持：
    1. 不同用户/场景的权重自定义
    2. 技能匹配自定义
    3. 评分参数调整

    Attributes:
        weights: 各维度权重配置，字典形式
        user_skills: 用户技能列表，用于技术匹配评分
        min_hours: 最小工时估算，默认5小时
        max_hours: 最大工时估算，默认500小时
        risk_keywords: 自定义风险关键词（覆盖默认）
        currency_rates: 自定义汇率映射（覆盖默认）
    """

    weights: Dict[str, float] = field(
        default_factory=lambda: {
            "budget_efficiency": 0.15,
            "competition": 0.25,
            "clarity": 0.25,
            "customer": 0.20,
            "tech": 0.10,
            "risk": 0.05,
        }
    )
    user_skills: Optional[List[str]] = None
    min_hours: int = ProjectComplexity.TRIVIAL.value[0]
    max_hours: int = ProjectComplexity.LARGE.value[1]
    risk_keywords: Optional[Dict[str, List[str]]] = None
    currency_rates: Optional[Dict[str, float]] = None

    def __post_init__(self):
        """验证配置有效性"""
        total = sum(self.weights.values())
        if abs(total - 1.0) > 0.001:
            logger.warning(
                f"Weights sum to {total}, expected 1.0. "
                "Scores may not be normalized to 0-10 range."
            )


class RequirementQualityScorer:
    """Helper class for multi-dimensional requirement quality scoring."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        # Use config from settings if available
        clarity_cfg = config.get("clarity", {}) if config else {}
        self.deliverable_kws = clarity_cfg.get("deliverable_keywords", ["deliverable", "output", "result", "complete", "milestone", "step"])
        self.acceptance_kws = clarity_cfg.get("acceptance_keywords", ["acceptance", "criteria", "requirements", "specs", "specification"])
        self.tech_spec_kws = clarity_cfg.get("tech_spec_keywords", ["flask", "selenium", "pandas", "fastapi", "sqlalchemy", "react", "vue", "docker", "kubernetes", "n8n"])
        self.vague_kws = clarity_cfg.get("vague_keywords", ["optimize", "improve", "insights", "better", "best way", "enhancement"])

    def score(self, description: str) -> float:
        if not description:
            return 0.0
        
        desc_lower = description.lower()
        score = 0.0

        # 1. Deliverables (30% -> 3.0 pts)
        if any(kw in desc_lower for kw in self.deliverable_kws):
            score += 3.0
        
        # 2. Acceptance Criteria (25% -> 2.5 pts)
        if any(kw in desc_lower for kw in self.acceptance_kws):
            score += 2.5
        
        # 3. Tech Specs (25% -> 2.5 pts)
        # Use more specific matching for tech stack
        matched_tech = [kw for kw in self.tech_spec_kws if kw in desc_lower]
        if matched_tech:
            score += min(len(matched_tech) * 0.5, 2.5)
        
        # 4. No Vague Terms (15% -> 1.5 pts)
        vague_count = sum(1 for kw in self.vague_kws if kw in desc_lower)
        vague_penalty = min(vague_count * 0.5, 1.5)
        score += (1.5 - vague_penalty)

        # 5. Description Length (5% -> 0.5 pts)
        length = len(description)
        if length < 200:
            score -= 2.0 # Heavy penalty for too short
        elif length > 1000 and not matched_tech:
            score -= 1.0 # Penalty for long but no tech details
        else:
            score += 0.5
        
        return max(0.0, min(score, 10.0))


class ProjectScorer:
    """
    Service for scoring Freelancer projects (10-point scale).

    This class supports both configuration-based initialization and
    dependency injection for flexible usage patterns.

    Attributes:
        config: Scoring configuration
        weights: Effective weights (from config or defaults)
        user_skills: User skills for matching
    """

    # 默认风险关键词配置
    DEFAULT_RISK_KEYWORDS = {
        "vague_requirements": [
            "insights",
            "optimize",
            "optimization",
            "improve",
            "improvement",
            "enhance",
            "enhancement",
            "best way",
            "most relevant",
            "modern",
            "user-friendly",
            "seamless",
            "smooth",
            "robust",
            "cutting-edge",
            "state-of-the-art",
            "next-level",
            "revolutionary",
            "magic",
        ],
        "scope_creep": [
            "and more",
            "etcetera",
            "etc",
            "other features",
            "additional features",
            "flexibility",
            "scalable",
            "future-proof",
            "extensible",
            "modular",
            "easy to add",
            "simple to extend",
            "may need",
            "might require",
        ],
        "unclear_timeline": [
            "asap",
            "urgent",
            "quickly",
            "fast",
            "immediate",
            "priority",
            "when possible",
            "timeline flexible",
            "deadline negotiable",
            "as soon as possible",
            "time is not critical",
        ],
        "payment_risk": [
            "pay after",
            "pay when",
            "payment upon completion",
            "milestone payment only",
            "large milestone",
            "final payment",
            "bonus upon completion",
        ],
        "technical_vagueness": [
            "latest technology",
            "modern tech",
            "current standards",
            "industry best practices",
            "professional quality",
            "high quality",
            "top notch",
            "world-class",
            "enterprise-grade",
        ],
    }

    def __init__(self, config: Optional[ScoringConfig] = None):
        """
        Initialize scorer with optional configuration.

        Args:
            config: Scoring configuration. If None, uses defaults from settings.
        """
        rules = settings.scoring_rules
        self.config = config
        self.weights = config.weights if config else rules.get("weights", DEFAULT_WEIGHTS.copy())
        self.user_skills = config.user_skills if config else settings.DEFAULT_SKILLS
        self.min_hours = config.min_hours if config else 5
        self.max_hours = config.max_hours if config else 500
        
        # Load risk keywords from YAML if available, otherwise use defaults
        if config and config.risk_keywords:
            self.risk_keywords = config.risk_keywords
        else:
            self.risk_keywords = rules.get("risk_keywords", self.DEFAULT_RISK_KEYWORDS)

        logger.debug(
            f"ProjectScorer initialized with weights={self.weights}, "
            f"skills={self.user_skills}"
        )

    @property
    def RISK_KEYWORDS(self) -> Dict[str, List[str]]:
        """获取风险关键词配置（支持覆盖）"""
        return self.risk_keywords

    def _normalize_currency_code(self, currency_code: Optional[str]) -> str:
        """
        Normalize currency code to 3-letter ISO format.
        """
        if not currency_code:
            return "USD"

        code = str(currency_code).strip().upper()

        currency_map = {
            "US": "USD",
            "EU": "EUR",
            "GB": "GBP",
            "CA": "CAD",
            "AU": "AUD",
            "SG": "SGD",
            "NZ": "NZD",
            "HK": "HKD",
            "JP": "JPY",
            "CN": "CNY",
            "MY": "MYR",
            "PH": "PHP",
            "TH": "THB",
            "IN": "INR",
            "$": "USD",
            "€": "EUR",
            "£": "GBP",
            "₹": "INR",
            "¥": "JPY",
            "₱": "PHP",
            "฿": "THB",
            "₩": "KRW",
            "R$": "BRL",
            "₽": "RUB",
        }

        if code in currency_map:
            return currency_map[code]

        if len(code) == 3 and code.isalpha():
            return code

        return "USD"

    def _get_currency_rate(self, currency_code: str) -> Optional[float]:
        """
        Get exchange rate for currency to USD using dynamic converter.
        """
        converter = get_currency_converter()
        return converter.get_rate_sync(currency_code)

    def _convert_to_usd(self, amount: float, currency_code: str) -> Optional[float]:
        """
        Convert amount to USD.
        """
        normalized_code = self._normalize_currency_code(currency_code)
        rate = self._get_currency_rate(normalized_code)
        if rate is None:
            return None
        return amount * rate

    def calculate_grade(self, score: float) -> str:
        """
        Convert numeric score to letter grade (10-point scale).
        """
        if score >= 8.0:
            return "S"
        elif score >= 6.0:
            return "A"
        elif score >= 4.0:
            return "B"
        elif score >= 2.0:
            return "C"
        else:
            return "D"

    def estimate_project_hours(self, project: Dict[str, Any]) -> int:
        """
        Estimate project hours based purely on technical complexity and keywords.

        Returns:
            Estimated hours (clamped to min/max configured)
        """
        hours = 0
        title = project.get("title", "").lower()
        description = (project.get("full_description") or "").lower()
        combined_text = f"{title} {description}"

        # 1. Base hours from platform/type
        if any(kw in title for kw in ["mobile", "app", "ios", "android"]):
            hours += 80
        elif any(kw in combined_text for kw in ["mobile", "app", "ios", "android"]):
            hours += 40

        if "website" in title or "full stack" in title:
            hours += 40
        elif "web" in combined_text:
            hours += 20

        if "api" in title or "integration" in title:
            hours += 20
        if "scraping" in title or "scraper" in title:
            hours += 15
        if "automation" in title or "bot" in title:
            hours += 20

        # 2. AI/ML/Agent complexity
        if "multimodal" in combined_text or "agent" in combined_text:
            hours += 40
        elif any(
            kw in combined_text
            for kw in [
                "machine learning",
                "ml ",
                "deep learning",
                "neural network",
                "nlp",
                "llm",
                "ai ",
                "artificial intelligence",
            ]
        ):
            hours += 30

        # 3. Integration complexity (n8n, make, etc.)
        if "n8n" in combined_text or "workflow" in combined_text:
            hours += 15

        small_task_keywords = ["fix", "bug", "small", "tweak", "script", "update"]
        small_hits = sum(1 for kw in small_task_keywords if kw in combined_text)
        if small_hits:
            multiplier = 0.3
            if small_hits >= 2:
                multiplier = 0.2
            if small_hits >= 3:
                multiplier = 0.1
            hours = hours * multiplier

        min_hours = max(self.min_hours, ProjectComplexity.TRIVIAL.value[0])
        max_hours = min(self.max_hours, ProjectComplexity.LARGE.value[1])
        estimated = int(round(hours)) if hours > 0 else 0
        estimated = max(min_hours, min(estimated, max_hours))
        logger.debug(f"Estimated {estimated} hours for project {project.get('id')}")
        return estimated

    def score_budget_efficiency(
        self, project: Dict[str, Any], estimated_hours: int
    ) -> Tuple[float, float]:
        """
        Score budget efficiency (0-10 points) based on USD hourly rate.
        Returns (score, hourly_rate).
        """
        project_id = project.get("id", "unknown")
        budget_info = project.get("budget", {})
        budget_min = float(budget_info.get("minimum", 0) or 0)
        budget_max = float(budget_info.get("maximum", 0) or 0)

        currency_code = (
            project.get("currency_code")
            or project.get("currency", {}).get("code")
            or "USD"
        )

        avg_budget_usd = self._convert_to_usd(
            (budget_min + budget_max) / 2,
            currency_code,
        )
        if avg_budget_usd is None:
            return 5.0, 0.0
        project_type = project.get("type", project.get("type_id", "fixed"))

        if project_type == "hourly":
            hourly_rate = avg_budget_usd
        else:
            if estimated_hours <= 0:
                return 5.0, 0.0
            hourly_rate = avg_budget_usd / estimated_hours

        logger.debug(
            f"Project {project_id}: Normalized hourly rate {hourly_rate:.2f} USD/h"
        )

        score = 0.0
        if hourly_rate >= 80:
            score = max(4.0, 6.0 - (hourly_rate - 80) / 40 * 2.0)
        elif hourly_rate >= 60:
            score = 6.0 + (80 - hourly_rate) / 20 * 2.0
        elif hourly_rate >= 20:
            score = 8.0 + (hourly_rate - 20) / 40 * 2.0
        elif hourly_rate >= 15:
            score = 6.0 + (hourly_rate - 15) / 5 * 2.0
        else:
            score = max(0.0, hourly_rate / 15 * 6.0)

        return score, hourly_rate

    def score_requirement_quality(self, project: Dict[str, Any]) -> float:
        """
        Score requirement quality with multi-dimensional evaluation (0-10 points).
        """
        description = (
            project.get("full_description")
            or project.get("description")
            or project.get("preview_description", "")
        )
        
        scorer = RequirementQualityScorer(config=settings.scoring_rules)
        return scorer.score(description)

    def score_competition(self, project: Dict[str, Any]) -> float:
        """
        Score competition level (0-10 points).

        评分逻辑：
        - bid_count 0-4: 得分 2.0
        - bid_count 5-20: 得分 10.0
        - bid_count 21-40: 得分 6.0
        - bid_count > 40: 得分 2.0
        - 24小时内发布项目加分
        """
        bid_stats = project.get("bid_stats", {})
        bid_count = bid_stats.get("bid_count", 0)

        if bid_count <= 4:
            score = 2.0
        elif bid_count <= 20:
            score = 10.0
        elif bid_count <= 40:
            score = 6.0
        else:
            score = 2.0

        submitdate = project.get("submitdate")
        if submitdate:
            try:
                submit_ts = float(submitdate)
                if submit_ts > 1_000_000_000_000:
                    submit_ts = submit_ts / 1000.0
                if time.time() - submit_ts <= 24 * 3600:
                    score = min(10.0, score + 1.0)
            except (TypeError, ValueError):
                pass

        return score

    def detect_risk_keywords(self, project: Dict[str, Any]) -> Dict[str, List[str]]:
        """
        Detect risk keywords in project description.
        """
        description = (
            project.get("full_description")
            or project.get("description")
            or project.get("preview_description", "")
        ).lower()
        title = project.get("title", "").lower()
        combined_text = f"{title} {description}"
        detected_risks: Dict[str, List[str]] = {}

        for category, keywords in self.RISK_KEYWORDS.items():
            found_keywords = [kw for kw in keywords if kw in combined_text]
            if found_keywords:
                detected_risks[category] = found_keywords
        return detected_risks

    def score_customer(self, project: Dict[str, Any]) -> float:
        """
        Score customer activity/trust (0-10 points).
        """
        score = 7.0 # Base score for established customers
        owner_info = project.get("owner_info")
        if not owner_info:
            return 3.0 # Penalty for no info

        # 1. Payment Verification (P0)
        if not owner_info.get("payment_verified"):
            score -= 5.0
        
        # 2. Hire Rate
        jobs_posted = int(owner_info.get("jobs_posted", 0))
        jobs_hired = int(owner_info.get("jobs_hired", 0))
        hire_rate = jobs_hired / jobs_posted if jobs_posted > 0 else 0
        
        if jobs_posted > 0 and hire_rate < 0.30:
            score -= 3.0
        
        # 3. New Customer
        if jobs_posted == 0:
            score -= 4.0
        
        # 4. Activity
        if owner_info.get("online_status") == "online":
            score += 2.0
        
        # 5. Reputation
        rating = float(owner_info.get("rating", 0))
        if rating >= 4.5:
            score += 3.0
        elif rating >= 4.0:
            score += 1.5
            
        return max(0.0, min(score, 10.0))

    def score_tech_match(self, project: Dict[str, Any]) -> float:
        """
        Score technical skill matching (0-10 points).
        """
        title = project.get("title", "").lower()
        description = (
            project.get("full_description") or project.get("preview_description") or ""
        ).lower()
        matched_skills = 0
        for skill in self.user_skills:
            if skill.lower() in title or skill.lower() in description:
                matched_skills += 1
        if matched_skills >= 3:
            return 10.0
        elif matched_skills >= 2:
            return 7.0
        elif matched_skills >= 1:
            return 4.0
        return 0.0

    def score_risk(self, project: Dict[str, Any]) -> float:
        """
        Score project risk (0-10 points, higher = less risky).
        """
        score = 7.0
        owner_info = project.get("owner_info")
        if owner_info:
            if owner_info.get("verified"):
                score += 1.5
            if owner_info.get("payment_verified"):
                score += 1.5
            jobs_posted = owner_info.get("jobs_posted", 0)
            if jobs_posted == 0:
                score -= 3.0
            elif jobs_posted < 5:
                score -= 1.0
        return max(0.0, min(score, 10.0))

    def generate_reason(
        self, breakdown: ScoreBreakdown, project: Dict[str, Any]
    ) -> str:
        """Generate human-readable reasoning."""
        reasons = []
        budget_info = project.get("budget", {})
        currency = project.get("currency_code") or "USD"

        if breakdown.budget_efficiency_score >= 8.0:
            reasons.append(f"预算优秀 (${breakdown.hourly_rate:.1f}/h)")
        elif breakdown.budget_efficiency_score >= 6.0:
            reasons.append(f"预算合理 (${breakdown.hourly_rate:.1f}/h)")
        else:
            reasons.append(f"预算偏低 (${breakdown.hourly_rate:.1f}/h)")

        if breakdown.clarity_score >= 7.0:
            reasons.append("需求清晰")
        elif breakdown.clarity_score <= 4.0:
            reasons.append("需求较模糊")

        if breakdown.tech_score >= 7.0:
            reasons.append("技术高度匹配")
        return "，".join(reasons) + "。"

    def generate_proposal_draft(
        self, project: Dict[str, Any], breakdown: ScoreBreakdown
    ) -> str:
        """Generate a proposal draft."""
        return f"Proposal for {project.get('title')}. AI Score: {breakdown.budget_efficiency_score}"

    def score_project(self, project: Dict[str, Any], client_risk_score: Optional[int] = None) -> ProjectScore:
        """
        Calculate complete score for a project (10-point scale).

        Args:
            project: Project data
            client_risk_score: Optional risk score (0-100, higher is riskier) from client_risk service
        """
        estimated_hours = self.estimate_project_hours(project)
        budget_efficiency_score, hourly_rate = self.score_budget_efficiency(
            project, estimated_hours
        )

        # Risk score mapping (REF-006)
        # If client_risk_score is provided (0-100), map it to 0-10 (higher = less risky)
        if client_risk_score is not None:
            # 100 risk -> 0 score, 0 risk -> 10 score
            base_risk_score = (100.0 - float(client_risk_score)) / 10.0
        else:
            base_risk_score = self.score_risk(project)

        breakdown = ScoreBreakdown(
            budget_efficiency_score=budget_efficiency_score,
            estimated_hours=estimated_hours,
            hourly_rate=hourly_rate,
            competition_score=self.score_competition(project),
            clarity_score=self.score_requirement_quality(project),
            customer_score=self.score_customer(project),
            tech_score=self.score_tech_match(project),
            risk_score=base_risk_score,
        )

        # Use weights from settings.scoring_rules or defaults
        rules = settings.scoring_rules
        weights = rules.get("weights", self.weights)

        # 使用配置中的权重计算总分
        total = 0.0
        for dimension, weight in weights.items():
            dimension_score = getattr(breakdown, f"{dimension}_score", None)
            if dimension_score is not None:
                total += dimension_score * weight

        # ARC-001 / REF-006: High risk penalty (>60 risk score)
        if client_risk_score is not None and client_risk_score > 60:
            penalty_multiplier = rules.get("risk", {}).get("penalty_multiplier", 0.5)
            logger.warning(f"Project {project.get('id')} has high risk score {client_risk_score}, applying penalty multiplier {penalty_multiplier}")
            total *= penalty_multiplier

        grade = self.calculate_grade(total)
        reason = self.generate_reason(breakdown, project)
        proposal = self.generate_proposal_draft(project, breakdown)

        return ProjectScore(
            project_id=project.get("id"),
            ai_score=round(total, 2),
            ai_grade=grade,
            ai_reason=reason,
            ai_proposal_draft=proposal,
            score_breakdown=breakdown,
        )


# ============================================================================
# 单例管理（保留便捷访问，但支持依赖注入）
# ============================================================================

_scorer: Optional["ProjectScorer"] = None
_scorer_config: Optional[ScoringConfig] = None


def reset_singleton() -> None:
    """
    重置单例状态（用于测试环境）。

    调用此方法会清除缓存的评分器实例，
    下次调用 get_project_scorer() 时会创建新实例。

    Example:
        # 在单元测试的 setUp 中
        def setUp(self):
            reset_singleton()

        # 或在每个测试用例后
        def tearDown(self):
            reset_singleton()
    """
    global _scorer, _scorer_config
    _scorer = None
    _scorer_config = None
    logger.debug("Project scorer singleton reset")


def create_project_scorer(config: Optional[ScoringConfig] = None) -> "ProjectScorer":
    """
    创建新的 ProjectScorer 实例（依赖注入模式）。

    这是推荐创建评分器的方式，特别是在：
    1. 单元测试中
    2. 需要不同配置的多实例场景
    3. 依赖注入框架集成

    Args:
        config: 评分配置，为 None 时使用默认配置

    Returns:
        新的 ProjectScorer 实例

    Example:
        # 测试中使用自定义配置
        config = ScoringConfig(
            user_skills=["python", "fastapi"],
            weights={"budget_efficiency": 0.50, "tech": 0.30, ...}
        )
        scorer = create_project_scorer(config)

        # 测试中使用默认配置
        scorer = create_project_scorer()
    """
    return ProjectScorer(config=config)


def get_project_scorer() -> "ProjectScorer":
    """
    获取或创建单例评分器（便捷访问）。

    此方法保留是为了向后兼容和简化应用代码使用。
    推荐在应用初始化时调用 configure_scorer() 设置配置，
    然后在整个应用中使用此方法获取评分器。

    注意：在单元测试中请使用 create_project_scorer()。

    Returns:
        单例 ProjectScorer 实例

    Example:
        # 应用代码
        scorer = get_project_scorer()
        score = scorer.score_project(project)
    """
    global _scorer, _scorer_config
    if _scorer is None:
        config = _scorer_config
        _scorer = create_project_scorer(config)
    return _scorer


def configure_scorer(config: ScoringConfig) -> None:
    """
    配置单例评分器（在应用启动时调用）。

    在应用启动时调用此方法可以预设评分器配置，
    后续通过 get_project_scorer() 获取的将是配置后的实例。

    Args:
        config: 评分配置

    Example:
        # 应用启动时
        config = ScoringConfig(
            user_skills=["python", "n8n", "automation"],
            weights={
                "budget_efficiency": 0.35,  # 更重视预算
                "tech": 0.25,               # 技术匹配
                "clarity": 0.20,            # 需求清晰度
                "competition": 0.10,
                "customer": 0.05,
                "risk": 0.05,
            }
        )
        configure_scorer(config)
    """
    global _scorer_config
    _scorer_config = config
    _scorer = None  # 标记需要重建
    logger.info("Project scorer configured with custom settings")
