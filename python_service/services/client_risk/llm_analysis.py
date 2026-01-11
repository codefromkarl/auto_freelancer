"""
LLM 软分析模块（方向四：客户尽职调查与风控盾）。

职责：
- 定义“客户风控软分析”的 JSON schema 约定
- 提供归一化函数，把不稳定的模型输出转换为稳定结构

注意：
- 本文件不直接调用 OpenAI/Claude 等外部服务（避免循环依赖/便于单测）
- 具体的 LLM 调用由 `services.llm_client` 负责
"""

from __future__ import annotations

from typing import Any, Dict, List


def normalize_client_risk_llm_output(data: Any) -> Dict[str, Any]:
    """
    归一化/校验 LLM 输出，保证上层能够稳定消费。

    目标：
    - 强制输出包含：summary / risk_delta / reasons / signals
    - 对 risk_delta 做边界裁剪（[-50, 50]）
    - 对缺失/类型错误字段做“保底默认值”，避免风控流程崩溃

    返回结构：
    {
      "summary": str,
      "risk_delta": int,   # [-50, 50]
      "reasons": [str],
      "signals": dict
    }
    """
    if not isinstance(data, dict):
        raise ValueError("LLM output must be a JSON object")

    # summary：允许缺失，但最终必须给一个可读的默认值
    summary = str(data.get("summary", "")).strip()

    # risk_delta：尽量转 int，失败则降级为 0
    risk_delta_raw = data.get("risk_delta", 0)
    try:
        risk_delta = int(risk_delta_raw)
    except Exception:
        risk_delta = 0
    risk_delta = max(-50, min(50, risk_delta))

    # reasons：非 list 则降级为空
    reasons_raw = data.get("reasons")
    reasons: List[str] = []
    if isinstance(reasons_raw, list):
        reasons = [str(r).strip() for r in reasons_raw if str(r).strip()]

    # signals：非 dict 则降级为空 dict
    signals_raw = data.get("signals")
    signals = signals_raw if isinstance(signals_raw, dict) else {}

    return {
        "summary": summary or "未能从评价中提取明确风险结论（已降级处理）。",
        "risk_delta": risk_delta,
        "reasons": reasons,
        "signals": signals,
    }

