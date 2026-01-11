"""
LLM 客户端封装（遵循现有 FreelancerClient 的模式：统一初始化、错误包装、可注入）。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Protocol

from config import settings
from services.client_risk.llm_analysis import normalize_client_risk_llm_output

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """LLM 调用错误（对齐 FreelancerAPIError 的错误包装思路）。"""

    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class LLMClientProtocol(Protocol):
    """LLM 客户端协议：便于在测试中注入 Fake 实现，避免触网。"""

    async def generate_replies(self, *, thread_id: int, context_messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """生成 3 个语气版本的回复。"""

    async def analyze_client_risk(self, *, user: Dict[str, Any], reviews: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        客户风控软分析：
        - 输入：雇主 user 信息 + 历史评价 reviews
        - 输出：结构化风险信号 JSON（用于和硬规则合并）
        """


class OpenAILLMClient:
    """
    OpenAI LLM 客户端实现（使用 `openai>=1.0.0`）。

    注意：
    - 这里使用延迟导入 openai，避免在未安装依赖时影响单元测试（测试会注入 Fake 客户端）。
    """

    def __init__(self, api_key: str, model: str, base_url: Optional[str] = None):
        if not api_key:
            raise LLMError("Missing LLM_API_KEY", status_code=500)
        if not model:
            raise LLMError("Missing LLM_MODEL", status_code=500)

        self._api_key = api_key
        self._model = model

        try:
            from openai import AsyncOpenAI  # type: ignore
        except Exception as e:
            raise LLMError(f"OpenAI SDK not available: {e}", status_code=500)

        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def generate_replies(self, *, thread_id: int, context_messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """
        调用 OpenAI 生成 3 种语气回复，返回结构化结果：
        - professional / enthusiastic / concise
        """
        system_prompt = (
            "你是一个 Freelancer 客户沟通助手。"
            "请基于给定的对话上下文，为我生成 3 个候选回复："
            "1) professional：正式、专业；"
            "2) enthusiastic：友好、积极；"
            "3) concise：直接、高效。"
            "要求：回复要具体、有行动项；尽量使用与客户最近一条消息相同的语言；不要暴露任何敏感信息。"
            "只输出 JSON，格式严格为："
            '{"replies":[{"tone":"professional","text":"..."},{"tone":"enthusiastic","text":"..."},{"tone":"concise","text":"..."}]}'
        )

        user_payload = {
            "thread_id": thread_id,
            "context_messages": context_messages,
        }

        try:
            # 兼容 OpenAI Chat Completions API（openai>=1.0.0）
            result = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                ],
                temperature=0.6,
            )

            content = (result.choices[0].message.content or "").strip()
            if not content:
                raise LLMError("LLM returned empty content", status_code=502)

            parsed = json.loads(content)
            replies = parsed.get("replies")
            if not isinstance(replies, list):
                raise LLMError("LLM returned invalid JSON schema: missing replies", status_code=502)

            normalized: List[Dict[str, str]] = []
            for item in replies:
                if not isinstance(item, dict):
                    continue
                tone = str(item.get("tone", "")).strip()
                text = str(item.get("text", "")).strip()
                if not tone or not text:
                    continue
                normalized.append({"tone": tone, "text": text})

            # 最少需要 3 个选项
            if len(normalized) < 3:
                raise LLMError("LLM returned insufficient replies", status_code=502)

            return normalized[:3]

        except LLMError:
            raise
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM JSON: {e}")
            raise LLMError("LLM returned non-JSON content", status_code=502)
        except Exception as e:
            logger.exception(f"OpenAI call failed: {e}")
            raise LLMError(f"LLM call failed: {e}", status_code=502)

    async def analyze_client_risk(self, *, user: Dict[str, Any], reviews: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        对客户历史评价进行软分析，输出结构化风险信号。

        注意：
        - 该方法用于“方向四：客户尽职调查与风控盾”
        - 需要严格 JSON 输出，避免模型啰嗦导致解析失败
        """
        system_prompt = (
            "你是一个 Freelancer.com 平台的风控分析助手。"
            "任务：基于雇主（客户）信息与历史评价，识别风险信号，并输出结构化 JSON。"
            "重点关注：差评频率、常见抱怨（例如拖欠付款、需求模糊、频繁变更范围、沟通差）、"
            "Hire Rate 是否异常、争议/仲裁迹象（如有）。"
            "输出要求：只输出 JSON，不要包含任何解释性文字。"
            "严格遵循 schema："
            "{"
            '"summary": "一句话总结（中文）",'
            '"risk_delta": 0,'
            '"reasons": ["原因1", "原因2"],'
            '"signals": {'
            '"negative_review_frequency": 0.0,'
            '"common_complaints": ["..."],'
            '"hire_rate_assessment": "low|medium|high",'
            '"payment_risk": "low|medium|high",'
            '"scope_creep_risk": "low|medium|high",'
            '"communication_risk": "low|medium|high"'
            "}"
            "}"
            "其中 risk_delta 取值范围 [-50, 50]：正值表示更高风险，负值表示更低风险。"
        )

        # 控制输入大小：避免把过多评价直接塞进 prompt
        payload = {
            "user": user,
            "reviews": reviews[:50],  # 最多取前 50 条（可按时间/权重排序后再截断）
        }

        try:
            result = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                temperature=0.2,
            )

            content = (result.choices[0].message.content or "").strip()
            if not content:
                raise LLMError("LLM returned empty content", status_code=502)

            parsed = json.loads(content)
            try:
                normalized = normalize_client_risk_llm_output(parsed)
            except ValueError as e:
                raise LLMError(f"LLM returned invalid JSON schema: {e}", status_code=502)
            return normalized

        except LLMError:
            raise
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse client risk JSON: {e}")
            raise LLMError("LLM returned non-JSON content", status_code=502)
        except Exception as e:
            logger.exception(f"OpenAI call failed: {e}")
            raise LLMError(f"LLM call failed: {e}", status_code=502)


_client: Optional[LLMClientProtocol] = None


def get_llm_client() -> LLMClientProtocol:
    """获取全局 LLM 客户端实例（单例缓存）。"""
    global _client
    if _client is not None:
        return _client

    provider = getattr(settings, "LLM_PROVIDER", "openai")
    
    if provider in ["openai", "zhipu"]:
        api_key = getattr(settings, "LLM_API_KEY", "")
        model = getattr(settings, "LLM_MODEL", "gpt-4o-mini")
        
        base_url = None
        if provider == "zhipu":
            import os
            # Use Zhipu compatible base URL
            base_url = os.getenv("ZHIPU_API_URL")
            if base_url:
                 if "chat/completions" in base_url:
                     base_url = base_url.replace("chat/completions", "")
                 if base_url.endswith("/"):
                     base_url = base_url[:-1]
            
            if not base_url:
                 base_url = "https://open.bigmodel.cn/api/paas/v4"
                 
        _client = OpenAILLMClient(
            api_key=api_key,
            model=model,
            base_url=base_url
        )
        return _client

    raise LLMError(f"Unsupported LLM_PROVIDER: {provider}", status_code=500)
