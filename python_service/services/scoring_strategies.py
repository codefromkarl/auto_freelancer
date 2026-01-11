"""
评分策略模块 - Strategy Pattern 实现。

提供可插拔的评分策略，支持：
1. 规则基础评分 (RuleBasedScoringStrategy)
2. LLM 基础评分 (LLMBasedScoringStrategy)
3. 混合评分 (HybridScoringStrategy) - 结合规则和 LLM

设计目标：中标/完成率最大化
- 高预算效率权重
- 适中的竞争度偏好
- 客户信誉评估
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
import logging

from services.project_scorer import (
    ProjectScorer,
    ScoringConfig,
    ScoreBreakdown,
    ProjectScore,
)

logger = logging.getLogger(__name__)


# =============================================================================
# 策略接口与数据结构
# =============================================================================


@dataclass
class ScoringContext:
    """
    评分上下文 - 策略执行时共享的数据。

    Attributes:
        project: 项目数据字典
        user_skills: 用户技能列表
        preferences: 用户偏好设置
        metadata: 额外元数据
    """

    project: Dict[str, Any]
    user_skills: List[str] = field(default_factory=list)
    preferences: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScoringResult:
    """
    评分结果 - 策略执行的输出。

    Attributes:
        score: 综合评分 (0-10)
        grade: 等级 (S/A/B/C/D)
        breakdown: 各维度评分明细
        confidence: 结果置信度 (0-1)
        strategy_used: 使用的策略名称
        metadata: 额外信息
    """

    score: float
    grade: str
    breakdown: Dict[str, float]
    confidence: float = 0.9
    strategy_used: str = "unknown"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "score": self.score,
            "grade": self.grade,
            "breakdown": self.breakdown,
            "confidence": self.confidence,
            "strategy_used": self.strategy_used,
            "metadata": self.metadata,
        }


class ScoringStrategy(ABC):
    """
    评分策略抽象基类。

    所有评分策略必须实现此接口。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """策略名称"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """策略描述"""
        pass

    @abstractmethod
    def score(
        self, context: ScoringContext, scorer: Optional[ProjectScorer] = None
    ) -> ScoringResult:
        """
        执行评分。

        Args:
            context: 评分上下文
            scorer: 可选的评分器实例

        Returns:
            评分结果
        """
        pass

    @abstractmethod
    def is_applicable(self, context: ScoringContext) -> bool:
        """
        检查策略是否适用于给定上下文。

        Args:
            context: 评分上下文

        Returns:
            是否适用
        """
        pass


# =============================================================================
# 具体策略实现
# =============================================================================


class RuleBasedScoringStrategy(ScoringStrategy):
    """
    基于规则的评分策略。

    使用预定义的规则和权重进行评分，
    适合快速筛选和大规模处理场景。
    """

    def __init__(self, config: Optional[ScoringConfig] = None):
        """
        初始化策略。

        Args:
            config: 评分配置，为 None 时使用默认配置
        """
        self.config = config
        self._scorer: Optional[ProjectScorer] = None

    @property
    def name(self) -> str:
        return "rule_based"

    @property
    def description(self) -> str:
        return "基于预定义规则和权重的快速评分策略"

    def _get_scorer(self) -> ProjectScorer:
        """获取评分器实例"""
        if self._scorer is None:
            self._scorer = ProjectScorer(config=self.config)
        return self._scorer

    def is_applicable(self, context: ScoringContext) -> bool:
        """始终适用"""
        return True

    def score(
        self, context: ScoringContext, scorer: Optional[ProjectScorer] = None
    ) -> ScoringResult:
        """执行规则评分"""
        effective_scorer = scorer or self._get_scorer()

        # 如果提供了自定义配置，更新 scorer
        if self.config and scorer is None:
            effective_scorer = ProjectScorer(config=self.config)

        project_result = effective_scorer.score_project(context.project)

        breakdown = {
            "budget_efficiency": project_result.score_breakdown.budget_efficiency_score,
            "competition": project_result.score_breakdown.competition_score,
            "clarity": project_result.score_breakdown.clarity_score,
            "customer": project_result.score_breakdown.customer_score,
            "tech": project_result.score_breakdown.tech_score,
            "risk": project_result.score_breakdown.risk_score,
        }

        return ScoringResult(
            score=project_result.ai_score,
            grade=project_result.ai_grade,
            breakdown=breakdown,
            confidence=0.85,  # 规则评分置信度
            strategy_used=self.name,
            metadata={
                "estimated_hours": project_result.score_breakdown.estimated_hours,
                "hourly_rate": project_result.score_breakdown.hourly_rate,
                "reason": project_result.ai_reason,
            },
        )


class LLMBasedScoringStrategy(ScoringStrategy):
    """
    基于 LLM 的评分策略。

    使用大语言模型进行更智能的评分，
    能够理解项目描述的深层含义。
    """

    def __init__(self, scoring_service=None, system_prompt: Optional[str] = None):
        """
        初始化策略。

        Args:
            scoring_service: LLM 评分服务，为 None 时使用单例
            system_prompt: 自定义系统提示词
        """
        self.scoring_service = scoring_service
        self.system_prompt = system_prompt

    @property
    def name(self) -> str:
        return "llm_based"

    @property
    def description(self) -> str:
        return "基于大语言模型的智能评分策略"

    def is_applicable(self, context: ScoringContext) -> bool:
        """需要 LLM 服务可用"""
        return self.scoring_service is not None or self._get_service() is not None

    def _get_service(self):
        """获取 LLM 评分服务"""
        if self.scoring_service is None:
            from services.llm_scoring_service import get_scoring_service

            return get_scoring_service()
        return self.scoring_service

    async def score_async(
        self,
        context: ScoringContext,
    ) -> ScoringResult:
        """
        异步执行 LLM 评分。

        Args:
            context: 评分上下文

        Returns:
            评分结果
        """
        from services.llm_scoring_service import LLMScoringService
        from database.models import Project

        service = self._get_service()
        if service is None:
            raise ValueError("LLM scoring service not available")

        # 创建临时 Project 对象
        project_data = context.project
        project = Project(
            freelancer_id=project_data.get("id", 0),
            title=project_data.get("title", ""),
            description=project_data.get("description"),
            preview_description=project_data.get("preview_description"),
            budget_minimum=project_data.get("budget_minimum"),
            budget_maximum=project_data.get("budget_maximum"),
            currency_code=project_data.get("currency_code", "USD"),
            bid_stats=str(project_data.get("bid_stats", {})),
            owner_info=str(project_data.get("owner_info", {})),
        )

        result = await service.score_single_project(
            project,
            system_prompt=self.system_prompt,
        )

        if result is None:
            return ScoringResult(
                score=0.0,
                grade="D",
                breakdown={},
                confidence=0.0,
                strategy_used=self.name,
                metadata={"error": "LLM scoring failed"},
            )

        return ScoringResult(
            score=result.get("score", 0.0),
            grade=self._calculate_grade(result.get("score", 0.0)),
            breakdown={},
            confidence=0.9,  # LLM 评分置信度较高
            strategy_used=self.name,
            metadata={
                "reason": result.get("reason"),
                "proposal": result.get("proposal"),
                "suggested_bid": result.get("suggested_bid"),
                "estimated_hours": result.get("estimated_hours"),
                "hourly_rate": result.get("hourly_rate"),
            },
        )

    def score(
        self, context: ScoringContext, scorer: Optional[ProjectScorer] = None
    ) -> ScoringResult:
        """
        同步执行 LLM 评分（包装异步调用）。

        注意：建议使用 score_async() 进行异步调用。
        """
        import asyncio

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(self.score_async(context))

    def _calculate_grade(self, score: float) -> str:
        """计算等级"""
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


class HybridScoringStrategy(ScoringStrategy):
    """
    混合评分策略 - 结合规则和 LLM。

    策略：
    1. 首先使用规则评分进行快速筛选
    2. 高分项目使用 LLM 进行深度分析
    3. 综合两者结果得出最终评分

    优势：
    - 平衡速度和质量
    - 高分项目获得更准确的评估
    - 降低 LLM API 调用成本
    """

    def __init__(
        self,
        rule_config: Optional[ScoringConfig] = None,
        llm_service=None,
        llm_threshold: float = 6.0,  # 超过此分数才使用 LLM
        llm_prompt: Optional[str] = None,
    ):
        """
        初始化策略。

        Args:
            rule_config: 规则评分配置
            llm_service: LLM 评分服务
            llm_threshold: 使用 LLM 的分数阈值
            llm_prompt: LLM 系统提示词
        """
        self.rule_strategy = RuleBasedScoringStrategy(config=rule_config)
        self.llm_strategy = LLMBasedScoringStrategy(
            scoring_service=llm_service,
            system_prompt=llm_prompt,
        )
        self.llm_threshold = llm_threshold

    @property
    def name(self) -> str:
        return "hybrid"

    @property
    def description(self) -> str:
        return "规则+LLM混合评分，高分项目使用LLM深度分析"

    def is_applicable(self, context: ScoringContext) -> bool:
        """规则策略始终适用"""
        return self.rule_strategy.is_applicable(context)

    def score(
        self, context: ScoringContext, scorer: Optional[ProjectScorer] = None
    ) -> ScoringResult:
        """执行混合评分"""
        import asyncio

        # 首先执行规则评分
        rule_result = self.rule_strategy.score(context, scorer)

        # 如果规则评分超过阈值，使用 LLM 进行深度分析
        if rule_result.score >= self.llm_threshold and self.llm_strategy.is_applicable(
            context
        ):
            try:
                llm_result = self.llm_strategy.score(context, scorer)

                # 综合评分：规则 40% + LLM 60%
                final_score = rule_result.score * 0.4 + llm_result.score * 0.6

                return ScoringResult(
                    score=round(final_score, 2),
                    grade=self._calculate_grade(final_score),
                    breakdown=rule_result.breakdown,  # 使用规则的维度评分
                    confidence=0.92,  # 混合策略置信度更高
                    strategy_used=self.name,
                    metadata={
                        "rule_score": rule_result.score,
                        "llm_score": llm_result.score,
                        "rule_metadata": rule_result.metadata,
                        "llm_metadata": llm_result.metadata,
                    },
                )
            except Exception as e:
                logger.warning(f"LLM scoring failed, using rule result: {e}")
                return rule_result

        return rule_result

    def _calculate_grade(self, score: float) -> str:
        """计算等级"""
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


class WinRateOptimizedStrategy(ScoringStrategy):
    """
    中标率优化策略 - 针对中标/完成率最大化目标。

    评分特点：
    1. 提高预算效率权重（35%）
    2. 降低竞争度权重（5%），避免高竞争项目
    3. 提高客户信誉权重（15%）
    4. 保持技术匹配权重（20%）
    5. 保持需求清晰度权重（20%）
    6. 降低风险权重（5%）
    """

    def __init__(self):
        # 中标率优化配置
        self.config = ScoringConfig(
            weights={
                "budget_efficiency": 0.35,  # 提高：预算是核心
                "competition": 0.05,  # 降低：避免高竞争
                "clarity": 0.20,  # 保持：清晰需求
                "customer": 0.15,  # 提高：客户信誉重要
                "tech": 0.20,  # 保持：技术匹配
                "risk": 0.05,  # 保持：风险控制
            }
        )
        self.rule_strategy = RuleBasedScoringStrategy(config=self.config)

    @property
    def name(self) -> str:
        return "win_rate_optimized"

    @property
    def description(self) -> str:
        return "中标率优化策略，针对预算效率和客户信誉"

    def is_applicable(self, context: ScoringContext) -> bool:
        return True

    def score(
        self, context: ScoringContext, scorer: Optional[ProjectScorer] = None
    ) -> ScoringResult:
        """执行中标率优化评分"""
        result = self.rule_strategy.score(context, scorer)

        # 添加额外的元数据
        result.metadata["optimization_target"] = "win_rate"
        result.metadata["budget_weight"] = 0.35
        result.metadata["customer_weight"] = 0.15

        return result


class CompletionRateOptimizedStrategy(ScoringStrategy):
    """
    完成率优化策略 - 针对项目成功完成率最大化目标。

    评分特点：
    1. 需求清晰度权重最高（30%）
    2. 客户信誉权重高（20%）
    3. 技术匹配权重高（25%）
    4. 预算效率权重适中（15%）
    5. 竞争度权重低（5%）
    6. 风险权重高（5%）
    """

    def __init__(self):
        # 完成率优化配置
        self.config = ScoringConfig(
            weights={
                "budget_efficiency": 0.15,  # 降低：完成更重要
                "competition": 0.05,  # 降低
                "clarity": 0.30,  # 提高：清晰需求是完成前提
                "customer": 0.20,  # 提高：好客户更容易完成
                "tech": 0.25,  # 提高：技术匹配影响完成
                "risk": 0.05,  # 保持
            }
        )
        self.rule_strategy = RuleBasedScoringStrategy(config=self.config)

    @property
    def name(self) -> str:
        return "completion_rate_optimized"

    @property
    def description(self) -> str:
        return "完成率优化策略，针对需求清晰度和客户信誉"

    def is_applicable(self, context: ScoringContext) -> bool:
        return True

    def score(
        self, context: ScoringContext, scorer: Optional[ProjectScorer] = None
    ) -> ScoringResult:
        """执行完成率优化评分"""
        result = self.rule_strategy.score(context, scorer)

        # 添加额外的元数据
        result.metadata["optimization_target"] = "completion_rate"
        result.metadata["clarity_weight"] = 0.30
        result.metadata["customer_weight"] = 0.20

        return result


# =============================================================================
# 策略工厂
# =============================================================================


class ScoringStrategyFactory:
    """
    评分策略工厂。

    提供预设策略的快捷创建方式。
    """

    # 预设策略映射
    PRESETS = {
        "rule_based": RuleBasedScoringStrategy,
        "llm_based": LLMBasedScoringStrategy,
        "hybrid": HybridScoringStrategy,
        "win_rate": WinRateOptimizedStrategy,
        "completion_rate": CompletionRateOptimizedStrategy,
    }

    @classmethod
    def create(cls, strategy_name: str, **kwargs) -> ScoringStrategy:
        """
        创建指定名称的策略。

        Args:
            strategy_name: 策略名称
            **kwargs: 策略初始化参数

        Returns:
            策略实例

        Raises:
            ValueError: 未知策略名称
        """
        strategy_class = cls.PRESETS.get(strategy_name)
        if strategy_class is None:
            raise ValueError(
                f"Unknown strategy: {strategy_name}. "
                f"Available: {list(cls.PRESETS.keys())}"
            )
        return strategy_class(**kwargs)

    @classmethod
    def get_available_strategies(cls) -> List[str]:
        """获取可用策略列表"""
        return list(cls.PRESETS.keys())

    @classmethod
    def get_strategy_info(cls, name: str) -> Dict[str, str]:
        """获取策略信息"""
        strategy = cls.create(name)
        return {
            "name": strategy.name,
            "description": strategy.description,
        }


# =============================================================================
# 便捷函数
# =============================================================================


def create_win_rate_strategy() -> ScoringStrategy:
    """创建中标率优化策略（便捷函数）"""
    return WinRateOptimizedStrategy()


def create_completion_rate_strategy() -> ScoringStrategy:
    """创建完成率优化策略（便捷函数）"""
    return CompletionRateOptimizedStrategy()


def create_hybrid_strategy(
    rule_config: Optional[ScoringConfig] = None,
    llm_service=None,
    llm_threshold: float = 6.0,
) -> ScoringStrategy:
    """创建混合策略（便捷函数）"""
    return HybridScoringStrategy(
        rule_config=rule_config,
        llm_service=llm_service,
        llm_threshold=llm_threshold,
    )
