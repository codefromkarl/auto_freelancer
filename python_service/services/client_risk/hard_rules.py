"""
硬规则过滤引擎（方向四：客户尽职调查与风控盾）。

目标：
1) 对 Freelancer 雇主（client/employer）进行“硬规则”资格审查
2) 输出触发的 flags + 是否通过 gate（gate_passed）

约定：
- 只对“明确为 False/命中 denylist/满足阈值条件”的情况触发规则
- 缺失字段不直接判定失败（避免因 API 字段缺失导致误杀），但上层可结合软分析/默认分做降级处理
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, List, Optional


# 国家/地区 denylist（ISO 3166-1 alpha-2）
# 说明：该集合来自产品策略（硬拦截），可在后续演进为 settings 配置项
COUNTRY_DENYLIST: set[str] = {
    "NG", "PK", "BD", "LK", "ZW", "MM", "CU", "KP", "VE", "IR", "SD", "AF"
}


@dataclass(frozen=True)
class HardRuleResult:
    """
    硬规则检查结果。

    - flags：触发的规则标识（用于 UI 展示、审计落库、策略回溯）
    - gate_passed：是否通过资格审查（True 表示允许进入下一步软分析/投标流程）
    """

    flags: List[str]
    gate_passed: bool


def _as_int(value: Any) -> Optional[int]:
    """尽量把 value 转为 int，失败则返回 None（用于兼容 API 字段格式差异）。"""
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _as_float(value: Any) -> Optional[float]:
    """尽量把 value 转为 float，失败则返回 None。"""
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def evaluate_hard_rules(user: Mapping[str, Any]) -> HardRuleResult:
    """
    执行硬规则过滤。

    输入：
    - user：来自 getUser 的雇主信息（或经过归一化后的 dict）

    输出：
    - HardRuleResult(flags=[...], gate_passed=bool)

    规则（按需求文档）：
    - PAYMENT_NOT_VERIFIED: payment_verified=False
    - DEPOSIT_NOT_MADE: deposit_made=False
    - COUNTRY_BLOCKED: country in denylist
    - ZERO_REVIEWS_AFTER_POSTING: review_count=0 且 jobs_posted>=5
    - LOW_HIRE_RATE: hire_rate < 0.3 且 jobs_posted >= 10
    """
    flags: List[str] = []

    # 1) 付款验证（明确为 False 才触发）
    if user.get("payment_verified") is False:
        flags.append("PAYMENT_NOT_VERIFIED")

    # 2) 保证金/押金（明确为 False 才触发）
    if user.get("deposit_made") is False:
        flags.append("DEPOSIT_NOT_MADE")

    # 3) 国家/地区 denylist
    country = str(user.get("country") or "").upper().strip()
    if country and country in COUNTRY_DENYLIST:
        flags.append("COUNTRY_BLOCKED")

    # 4) 发布过项目但无评价（典型“无信誉但高活跃”风险信号）
    jobs_posted = _as_int(user.get("jobs_posted")) or 0
    review_count = _as_int(user.get("review_count")) or 0
    if jobs_posted >= 5 and review_count == 0:
        flags.append("ZERO_REVIEWS_AFTER_POSTING")

    # 5) Hire rate 过低（且样本量足够大）
    # 注意：如果 hire_rate 缺失，可尝试从 jobs_hired/jobs_posted 推导
    hire_rate = _as_float(user.get("hire_rate"))
    if hire_rate is None:
        jobs_hired = _as_int(user.get("jobs_hired"))
        if jobs_hired is not None and jobs_posted > 0:
            hire_rate = jobs_hired / jobs_posted

    if hire_rate is not None and jobs_posted >= 10 and hire_rate < 0.3:
        flags.append("LOW_HIRE_RATE")

    gate_passed = len(flags) == 0
    return HardRuleResult(flags=flags, gate_passed=gate_passed)

