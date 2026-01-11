"""
评分配置模块 - 权重统一与版本化管理。

提供：
1. 预设权重配置（针对中标率/完成率优化）
2. 配置版本化管理
3. 配置文件加载（YAML/JSON）
4. 配置验证与合并

设计目标：中标/完成率最大化

版本历史：
- v1.0: 初始配置
- v1.1: 针对中标率优化，增加预算效率权重
- v1.2: 针对完成率优化，增加需求清晰度权重
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, field, asdict
from dataclasses_json import dataclass_json
from enum import Enum
import json
import logging
import hashlib

logger = logging.getLogger(__name__)


class ScoringGoal(Enum):
    """评分目标枚举"""

    WIN_RATE = "win_rate"  # 中标率最大化
    COMPLETION_RATE = "completion_rate"  # 完成率最大化
    BALANCED = "balanced"  # 平衡模式
    HIGH_VALUE = "high_value"  # 高价值项目优先


@dataclass
class WeightConfig:
    """
    单个评分维度权重配置。

    Attributes:
        dimension: 维度名称
        weight: 权重值 (0-1)
        min_score: 最小分数阈值
        max_score: 最大分数阈值
        enabled: 是否启用
    """

    dimension: str
    weight: float
    min_score: float = 0.0
    max_score: float = 10.0
    enabled: bool = True


@dataclass
class ScoringPolicy:
    """
    评分策略配置。

    Attributes:
        version: 策略版本
        name: 策略名称
        goal: 评分目标
        description: 策略描述
        weights: 各维度权重列表
        rules: 特殊规则配置
        created_at: 创建时间
        updated_at: 更新时间
    """

    version: str
    name: str
    goal: ScoringGoal
    description: str
    weights: List[WeightConfig]
    rules: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


class ScoringConfigManager:
    """
    评分配置管理器。

    负责：
    1. 管理预设配置
    2. 配置版本控制
    3. 配置验证
    4. 配置导出/导入
    """

    # 预设配置版本库
    PRESETS: Dict[str, ScoringPolicy] = {}

    @classmethod
    def _init_presets(cls):
        """初始化预设配置"""
        if cls.PRESETS:
            return

        # v1.0: 初始配置（平衡模式）
        cls.PRESETS["v1.0"] = ScoringPolicy(
            version="v1.0",
            name="平衡模式",
            goal=ScoringGoal.BALANCED,
            description="平衡考虑各维度，适合一般场景",
            weights=[
                WeightConfig("budget_efficiency", 0.30),
                WeightConfig("competition", 0.10),
                WeightConfig("clarity", 0.25),
                WeightConfig("customer", 0.10),
                WeightConfig("tech", 0.20),
                WeightConfig("risk", 0.05),
            ],
        )

        # v1.1: 中标率优化
        cls.PRESETS["v1.1"] = ScoringPolicy(
            version="v1.1",
            name="中标率优化",
            goal=ScoringGoal.WIN_RATE,
            description="针对中标率最大化，优化预算效率和客户信誉",
            weights=[
                WeightConfig("budget_efficiency", 0.35),  # 提高预算权重
                WeightConfig("competition", 0.05),  # 降低竞争权重
                WeightConfig("clarity", 0.20),
                WeightConfig("customer", 0.15),  # 提高客户权重
                WeightConfig("tech", 0.20),
                WeightConfig("risk", 0.05),
            ],
            rules={
                "hourly_rate_threshold": {
                    "excellent": 50,
                    "good": 30,
                    "fair": 15,
                },
                "competition_preference": "low",  # 偏好低竞争
            },
        )

        # v1.2: 完成率优化
        cls.PRESETS["v1.2"] = ScoringPolicy(
            version="v1.2",
            name="完成率优化",
            goal=ScoringGoal.COMPLETION_RATE,
            description="针对完成率最大化，优化需求清晰度和客户信誉",
            weights=[
                WeightConfig("budget_efficiency", 0.15),  # 降低预算权重
                WeightConfig("competition", 0.05),
                WeightConfig("clarity", 0.30),  # 提高清晰度权重
                WeightConfig("customer", 0.20),  # 提高客户权重
                WeightConfig("tech", 0.25),  # 提高技术匹配权重
                WeightConfig("risk", 0.05),
            ],
            rules={
                "clarity_threshold": {
                    "high": 7.0,
                    "medium": 4.0,
                    "low": 2.0,
                },
                "customer_requirements": {
                    "min_rating": 4.0,
                    "min_jobs_posted": 5,
                },
            },
        )

        # v1.3: 高价值项目优先
        cls.PRESETS["v1.3"] = ScoringPolicy(
            version="v1.3",
            name="高价值优先",
            goal=ScoringGoal.HIGH_VALUE,
            description="专注于高价值项目，忽略小额项目",
            weights=[
                WeightConfig("budget_efficiency", 0.45),  # 极高预算权重
                WeightConfig("competition", 0.05),
                WeightConfig("clarity", 0.15),
                WeightConfig("customer", 0.15),
                WeightConfig("tech", 0.15),
                WeightConfig("risk", 0.05),
            ],
            rules={
                "min_budget_threshold": 500,  # 最低预算 500 USD
                "min_hourly_rate": 30,
            },
        )

    @classmethod
    def get_preset(cls, version: str) -> Optional[ScoringPolicy]:
        """获取预设配置"""
        cls._init_presets()
        return cls.PRESETS.get(version)

    @classmethod
    def get_latest(cls) -> ScoringPolicy:
        """获取最新预设配置"""
        cls._init_presets()
        return cls.PRESETS["v1.2"]  # 完成率优化作为默认

    @classmethod
    def list_versions(cls) -> List[str]:
        """列出所有可用版本"""
        cls._init_presets()
        return list(cls.PRESETS.keys())

    @classmethod
    def get_by_goal(cls, goal: ScoringGoal) -> Optional[ScoringPolicy]:
        """根据目标获取配置"""
        cls._init_presets()
        for policy in cls.PRESETS.values():
            if policy.goal == goal:
                return policy
        return None

    @classmethod
    def validate_policy(cls, policy: ScoringPolicy) -> tuple:
        """
        验证策略配置有效性。

        Returns:
            (is_valid, errors)
        """
        errors = []

        # 检查权重总和
        total_weight = sum(w.weight for w in policy.weights if w.enabled)
        if abs(total_weight - 1.0) > 0.001:
            errors.append(f"Weights sum to {total_weight}, expected 1.0")

        # 检查权重范围
        for w in policy.weights:
            if w.weight < 0 or w.weight > 1:
                errors.append(f"Weight for {w.dimension} out of range: {w.weight}")

        # 检查维度完整性
        required_dimensions = {
            "budget_efficiency",
            "competition",
            "clarity",
            "customer",
            "tech",
            "risk",
        }
        configured_dimensions = {w.dimension for w in policy.weights if w.enabled}
        missing = required_dimensions - configured_dimensions
        if missing:
            errors.append(f"Missing dimensions: {missing}")

        return len(errors) == 0, errors

    @classmethod
    def to_dict(cls, policy: ScoringPolicy) -> Dict[str, Any]:
        """将策略转换为字典"""
        return {
            "version": policy.version,
            "name": policy.name,
            "goal": policy.goal.value,
            "description": policy.description,
            "weights": [
                {
                    "dimension": w.dimension,
                    "weight": w.weight,
                    "min_score": w.min_score,
                    "max_score": w.max_score,
                    "enabled": w.enabled,
                }
                for w in policy.weights
            ],
            "rules": policy.rules,
            "created_at": policy.created_at,
            "updated_at": policy.updated_at,
        }

    @classmethod
    def to_weights_dict(cls, policy: ScoringPolicy) -> Dict[str, float]:
        """将策略转换为权重字典（供 ProjectScorer 使用）"""
        return {w.dimension: w.weight for w in policy.weights if w.enabled}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ScoringPolicy:
        """从字典创建策略"""
        weights = [
            WeightConfig(
                dimension=w.get("dimension", ""),
                weight=w.get("weight", 0.0),
                min_score=w.get("min_score", 0.0),
                max_score=w.get("max_score", 10.0),
                enabled=w.get("enabled", True),
            )
            for w in data.get("weights", [])
        ]

        goal = data.get("goal", "balanced")
        if isinstance(goal, str):
            goal = ScoringGoal(goal)

        return ScoringPolicy(
            version=data.get("version", "custom"),
            name=data.get("name", "Custom"),
            goal=goal,
            description=data.get("description", ""),
            weights=weights,
            rules=data.get("rules", {}),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


# =============================================================================
# 权重预设快捷函数
# =============================================================================


def get_weights_for_win_rate() -> Dict[str, float]:
    """
    获取中标率优化的权重配置。

    Returns:
        权重字典
    """
    policy = ScoringConfigManager.get_by_goal(ScoringGoal.WIN_RATE)
    if policy:
        return ScoringConfigManager.to_weights_dict(policy)
    return ScoringConfigManager.to_weights_dict(ScoringConfigManager.get_latest())


def get_weights_for_completion_rate() -> Dict[str, float]:
    """
    获取完成率优化的权重配置。

    Returns:
        权重字典
    """
    policy = ScoringConfigManager.get_by_goal(ScoringGoal.COMPLETION_RATE)
    if policy:
        return ScoringConfigManager.to_weights_dict(policy)
    return ScoringConfigManager.to_weights_dict(ScoringConfigManager.get_latest())


def get_balanced_weights() -> Dict[str, float]:
    """
    获取平衡模式的权重配置。

    Returns:
        权重字典
    """
    policy = ScoringConfigManager.get_by_goal(ScoringGoal.BALANCED)
    if policy:
        return ScoringConfigManager.to_weights_dict(policy)
    return ScoringConfigManager.to_weights_dict(ScoringConfigManager.get_latest())


def get_high_value_weights() -> Dict[str, float]:
    """
    获取高价值项目优先的权重配置。

    Returns:
        权重字典
    """
    policy = ScoringConfigManager.get_by_goal(ScoringGoal.HIGH_VALUE)
    if policy:
        return ScoringConfigManager.to_weights_dict(policy)
    return ScoringConfigManager.to_weights_dict(ScoringConfigManager.get_latest())


# =============================================================================
# 配置版本信息
# =============================================================================

CONFIG_VERSION = "v1.2"
CONFIG_LAST_UPDATED = "2026-01-11"

# LLM Prompt 使用的一致权重（与 v1.1 中标率优化版本保持一致）
LLM_PROMPT_WEIGHTS = {
    "budget_efficiency": 0.30,  # 预算效率
    "clarity": 0.25,  # 需求清晰度
    "tech": 0.20,  # 技术匹配
    "customer": 0.10,  # 客户信誉
    "competition": 0.10,  # 竞争程度
    "risk": 0.05,  # 项目风险
}


def get_llm_prompt_weights() -> Dict[str, float]:
    """获取 LLM Prompt 使用的权重配置"""
    return LLM_PROMPT_WEIGHTS.copy()


def generate_config_hash(config: Dict[str, Any]) -> str:
    """
    生成配置哈希值（用于缓存和版本校验）。

    Args:
        config: 配置字典

    Returns:
        SHA256 哈希值
    """
    config_str = json.dumps(config, sort_keys=True)
    return hashlib.sha256(config_str.encode()).hexdigest()


# =============================================================================
# 配置文件加载（YAML 支持）
# =============================================================================


def load_config_from_yaml(yaml_content: str) -> Optional[ScoringPolicy]:
    """
    从 YAML 内容加载配置。

    Args:
        yaml_content: YAML 格式的配置内容

    Returns:
        ScoringPolicy 或 None（加载失败）
    """
    try:
        import yaml

        data = yaml.safe_load(yaml_content)
        if data:
            return ScoringConfigManager.from_dict(data)
    except ImportError:
        logger.warning("PyYAML not installed, cannot load YAML config")
    except Exception as e:
        logger.error(f"Failed to load YAML config: {e}")
    return None


def load_config_from_json(json_content: str) -> Optional[ScoringPolicy]:
    """
    从 JSON 内容加载配置。

    Args:
        json_content: JSON 格式的配置内容

    Returns:
        ScoringPolicy 或 None（加载失败）
    """
    try:
        data = json.loads(json_content)
        if data:
            return ScoringConfigManager.from_dict(data)
    except Exception as e:
        logger.error(f"Failed to load JSON config: {e}")
    return None


# =============================================================================
# 默认导出
# =============================================================================

__all__ = [
    "ScoringGoal",
    "WeightConfig",
    "ScoringPolicy",
    "ScoringConfigManager",
    "get_weights_for_win_rate",
    "get_weights_for_completion_rate",
    "get_balanced_weights",
    "get_high_value_weights",
    "get_llm_prompt_weights",
    "CONFIG_VERSION",
    "CONFIG_LAST_UPDATED",
]
