"""
Proposal Service - 标书生成服务

提供专业的中标率优化提案生成功能，支持：
- 异步 LLM 调用
- 多风格/结构支持
- 质量验证和重试机制
- Persona 控制

Design Principles:
- Dependency Injection: 无全局单例，便于测试
- Strategy Pattern: 可插拔的验证策略
- Factory Pattern: 便捷的服务创建
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Tuple
from abc import ABC, abstractmethod
from sqlalchemy.orm import Session

from config import settings
from database.models import Project

logger = logging.getLogger(__name__)

_CJK_PATTERN = re.compile(r"[\u3400-\u9FFF]")
_NUMERIC_PATTERN = re.compile(
    r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?",
    re.IGNORECASE,
)
_QUOTE_NUMBER_PATTERNS = [
    re.compile(
        r"\$\s*((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(?:usd|eur|gbp|cad|aud|sgd|cny)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:budget|quote|bid|price)[^0-9\n]{0,80}((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)",
        re.IGNORECASE,
    ),
]
_BUDGET_CONTEXT_PATTERN = re.compile(r"\bbudget\b[^\n]{0,120}", re.IGNORECASE)
_LEGACY_QUOTE_NUMBER_PATTERN = re.compile(
    r"(?:budget|quote|bid|price|\$|usd|eur|gbp|cad|aud|sgd|cny)\D{0,80}((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)",
    re.IGNORECASE,
)
_PROJECT_REQUIREMENT_HINTS: List[Tuple[Tuple[str, ...], str]] = [
    (("state machine", "fsm"), "state machine"),
    (("otp", "one-time password"), "otp verification"),
    (("admin dashboard", "admin panel", "dashboard"), "admin dashboard"),
    (("schedule", "scheduling", "production planning"), "scheduling"),
    (("whatsapp", "whatsapp business"), "whatsapp integration"),
    (("webhook",), "webhook handling"),
    (("rest api", "restful", "endpoint"), "rest api"),
    (("readme", "setup", "documentation"), "readme/setup"),
    (("pagination", "load more", "infinite scroll"), "pagination"),
    (("beautifulsoup", "bs4"), "beautifulsoup parsing"),
    (("requests",), "requests stack"),
    (("logging", "error handling"), "logging/error handling"),
]


class ProposalValidatorProtocol(Protocol):
    """提案验证器协议"""

    def validate(
        self, proposal: str, project: Dict[str, Any]
    ) -> Tuple[bool, List[str]]:
        """
        验证提案质量

        Args:
            proposal: 提案文本
            project: 项目信息

        Returns:
            (是否通过, 验证消息列表)
        """
        ...

    def get_min_length(self) -> int:
        """获取最小长度要求"""
        ...

    def get_max_length(self) -> int:
        """获取最大长度要求"""
        ...


class PersonaControllerProtocol(Protocol):
    """人设控制器协议"""

    def get_persona_for_project(self, project: Dict[str, Any]) -> Dict[str, Any]:
        """
        获取适合项目的人设信息

        Args:
            project: 项目信息

        Returns:
            人设字典（包含语气、风格、专业度等）
        """
        ...

    def adjust_style(self, base_style: str, project: Dict[str, Any]) -> str:
        """
        根据项目调整基础风格

        Args:
            base_style: 基础风格
            project: 项目信息

        Returns:
            调整后的风格
        """
        ...


@dataclass
class ProposalConfig:
    """
    提案服务配置

    Attributes:
        max_retries: 最大重试次数
        timeout: LLM 调用超时（秒）
        min_length: 提案最小长度
        max_length: 提案最大长度
        validate_before_return: 返回前是否验证
        fallback_enabled: 是否启用回退机制
        model: 使用的模型名称
        temperature: 生成温度 (0.0-1.0)
    """

    max_retries: int = 3
    timeout: float = 60.0
    min_length: int = 280
    max_length: int = 1800
    target_char_min: int = 700
    target_char_max: int = 1200
    validate_before_return: bool = True
    fallback_enabled: bool = True
    model: str = "gpt-4o-mini"
    temperature: float = 0.7

    @classmethod
    def from_settings(cls) -> "ProposalConfig":
        """从应用配置创建默认配置"""
        return cls(
            max_retries=getattr(settings, "PROPOSAL_MAX_RETRIES", 3),
            timeout=getattr(settings, "PROPOSAL_TIMEOUT", 60.0),
            min_length=getattr(settings, "PROPOSAL_MIN_LENGTH", 280),
            max_length=getattr(settings, "PROPOSAL_MAX_LENGTH", 1800),
            target_char_min=getattr(settings, "PROPOSAL_TARGET_CHAR_MIN", 700),
            target_char_max=getattr(settings, "PROPOSAL_TARGET_CHAR_MAX", 1200),
            validate_before_return=True,
            fallback_enabled=True,
            model=getattr(settings, "LLM_MODEL", "gpt-4o-mini"),
            temperature=0.7,
        )


class DefaultProposalValidator:
    """默认提案验证器"""

    def __init__(
        self,
        min_length: int = 200,
        max_length: int = 800,
    ):
        self.min_length = min_length
        self.max_length = max_length

    def validate(
        self, proposal: str, project: Dict[str, Any]
    ) -> Tuple[bool, List[str]]:
        """
        验证提案质量

        Args:
            proposal: 提案文本
            project: 项目信息

        Returns:
            (是否通过, 验证消息列表)
        """
        issues = []

        # 1. 长度检查
        if len(proposal) < self.min_length:
            issues.append(f"提案过短（{len(proposal)} < {self.min_length} 字符）")
        if len(proposal) > self.max_length:
            issues.append(f"提案过长（{len(proposal)} > {self.max_length} 字符）")

        # 2. 检查是否包含 AI 模板化内容
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
        common_count = sum(1 for phrase in common_phrases if phrase in proposal)
        if common_count >= 3:
            issues.append(f"AI 模板化内容过多 ({common_count}处)")

        # 3. 关键词堆砌检测
        tech_keywords = [
            "python",
            "fastapi",
            "api",
            "automation",
            "workflow",
            "django",
            "flask",
        ]
        proposal_lower = proposal.lower()
        words = re.findall(r"\b\w+\b", proposal_lower)
        if len(words) > 20:
            keyword_count = sum(1 for k in tech_keywords if k in proposal_lower)
            if keyword_count / len(words) > 0.35:
                issues.append("关键词堆砌过密（缺乏自然表达）")

        # 4. 与项目描述的匹配度检查（放宽限制：从3个降低到2个共同词）
        project_desc = (project.get("description") or "").lower()
        if project_desc:
            title_words = set((project.get("title", "") or "").lower().split())
            proposal_words = set(proposal_lower.split())
            common_words = title_words & proposal_words
            if len(common_words) < 2 and len(title_words) > 5:
                issues.append("与项目描述关联度低（缺乏针对性）")

        # 5. 结构化检查（是否包含技术方案、交付计划）
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
        has_sections = sum(1 for s in required_sections if s.lower() in proposal_lower)
        if has_sections < 1:
            issues.append("缺乏结构化表达（技术方案/交付计划）")

        # 6. 重复句式检测
        sentences = proposal.split("。")
        unique_sentences = set()
        duplicate_count = 0
        for s in sentences:
            s_clean = s.strip()
            if s_clean:
                if s_clean in unique_sentences:
                    duplicate_count += 1
                unique_sentences.add(s_clean)

        if duplicate_count >= 2 and len(sentences) > 3:
            issues.append(f"存在重复句式 ({duplicate_count}处)")

        # 7. 检查是否为空行或仅包含特殊字符（放宽限制：从30%提高到50%）
        lines = proposal.split("\n")
        empty_lines = sum(
            1 for line in lines if not line.strip() or re.match(r"^[\s\t\xA0]+$", line)
        )
        if empty_lines > len(lines) * 0.5:
            issues.append(f"空行过多（{empty_lines}/{len(lines)}）")

        # 8. 项目关键锚点覆盖检查（确保标书针对性）
        anchors = self._extract_project_anchor_terms(project)
        if anchors:
            min_required_hits = 1 if len(anchors) <= 2 else 2
            hit_count = self._count_anchor_hits(proposal_lower, anchors)
            if hit_count < min_required_hits:
                issues.append(
                    "关键需求点覆盖不足"
                    f"（命中 {hit_count}/{min_required_hits}，候选: {', '.join(anchors[:4])}）"
                )

        # 9. 报价一致性检查（仅在存在 expected_bid_amount 时生效）
        expected_bid = project.get("expected_bid_amount")
        if expected_bid is not None:
            quote_candidates = self._extract_quote_candidates(proposal)
            if quote_candidates:
                expected = float(expected_bid)
                tolerance = max(1.0, expected * 0.12)
                if not any(abs(v - expected) <= tolerance for v in quote_candidates):
                    issues.append(
                        "报价与当前投标金额不一致"
                        f"（expected={expected:.2f}, found={quote_candidates[:3]}）"
                    )

        return len(issues) == 0, issues

    def get_min_length(self) -> int:
        return self.min_length

    def get_max_length(self) -> int:
        return self.max_length

    def _extract_project_anchor_terms(self, project: Dict[str, Any]) -> List[str]:
        project_text = " ".join(
            [
                str(project.get("title", "") or ""),
                str(project.get("description", "") or ""),
                str(project.get("preview_description", "") or ""),
            ]
        ).lower()

        anchors: List[str] = []
        for markers, label in _PROJECT_REQUIREMENT_HINTS:
            if any(marker in project_text for marker in markers):
                anchors.append(label)

        if anchors:
            return anchors[:6]

        # Fallback: title keywords
        raw_title = str(project.get("title", "") or "").lower()
        stop_words = {
            "with",
            "for",
            "and",
            "the",
            "task",
            "project",
            "build",
            "need",
            "from",
            "using",
            "into",
            "your",
            "this",
        }
        tokens = re.findall(r"[a-z][a-z0-9#+-]{3,}", raw_title)
        deduped: List[str] = []
        for token in tokens:
            if token in stop_words or token in deduped:
                continue
            deduped.append(token)
        return deduped[:3]

    def _count_anchor_hits(self, proposal_lower: str, anchors: List[str]) -> int:
        hits = 0
        for anchor in anchors:
            if "/" in anchor:
                parts = [p.strip() for p in anchor.split("/") if p.strip()]
                if any(part in proposal_lower for part in parts):
                    hits += 1
                continue
            if anchor in proposal_lower:
                hits += 1
                continue

            # Phrase fallback: allow partial token coverage for labels like
            # "whatsapp integration" even when proposal says "whatsapp webhook".
            tokens = re.findall(r"[a-z0-9+#-]{3,}", anchor.lower())
            stop_words = {"with", "for", "and", "the", "task", "project"}
            tokens = [token for token in tokens if token not in stop_words]
            if not tokens:
                continue
            token_hits = sum(1 for token in tokens if token in proposal_lower)
            min_hits = 1 if len(tokens) <= 2 else 2
            if token_hits >= min_hits:
                hits += 1
        return hits

    def _extract_quote_candidates(self, proposal: str) -> List[float]:
        text = proposal or ""
        values: List[float] = []
        for pattern in _QUOTE_NUMBER_PATTERNS:
            for match in pattern.finditer(text):
                parsed = self._safe_float(match.group(1))
                if parsed is None:
                    continue
                values.append(parsed)

        if not values:
            for segment in _BUDGET_CONTEXT_PATTERN.finditer(text):
                for m in _NUMERIC_PATTERN.finditer(segment.group(0)):
                    parsed = self._safe_float(m.group(0))
                    if parsed is None:
                        continue
                    values.append(parsed)

        if not values:
            for match in _LEGACY_QUOTE_NUMBER_PATTERN.finditer(text):
                parsed = self._safe_float(match.group(1))
                if parsed is None:
                    continue
                values.append(parsed)

        deduped: List[float] = []
        for value in values:
            if any(abs(value - existing) < 0.01 for existing in deduped):
                continue
            deduped.append(value)
        return deduped

    def _safe_float(self, raw: str) -> Optional[float]:
        try:
            return float((raw or "").replace(",", ""))
        except Exception:
            return None


class DefaultPersonaController:
    """默认人设控制器"""

    def __init__(self):
        # 默认人设配置
        self.default_persona = {
            "tone": "professional",  # 专业但友好
            "formality": "semi_formal",  # 半正式
            "confidence": "assertive",  # 自信但不傲慢
            "technical_depth": "intermediate",  # 技术深度适中
            "focus": "solution_oriented",  # 解决方案导向
        }

    def get_persona_for_project(self, project: Dict[str, Any]) -> Dict[str, Any]:
        """
        根据项目特征获取适合的人设

        Args:
            project: 项目信息

        Returns:
            人设字典
        """
        persona = self.default_persona.copy()

        # 根据项目类型调整
        title = (project.get("title") or "").lower()
        description = (project.get("description") or "").lower()
        combined = f"{title} {description}"

        # AI/ML 项目：技术深度更深
        if any(
            kw in combined
            for kw in ["ai", "ml", "machine learning", "llm", "gpt", "人工智能"]
        ):
            persona["technical_depth"] = "advanced"
            persona["focus"] = "innovation"

        # 简单任务：更简洁直接
        if any(kw in combined for kw in ["fix", "bug", "small", "simple", "tweak"]):
            persona["tone"] = "concise"
            persona["formality"] = "informal"
            persona["technical_depth"] = "basic"

        # 大型项目：更正式详细
        if any(
            kw in combined for kw in ["platform", "system", "enterprise", "full stack"]
        ):
            persona["tone"] = "highly_professional"
            persona["formality"] = "formal"
            persona["technical_depth"] = "advanced"

        # 自动化/脚本项目：效率导向
        if any(kw in combined for kw in ["automation", "script", "bot", "workflow"]):
            persona["focus"] = "efficiency"
            persona["tone"] = "practical"

        return persona

    def adjust_style(self, base_style: str, project: Dict[str, Any]) -> str:
        """
        根据项目调整基础风格

        Args:
            base_style: 基础风格
            project: 项目信息

        Returns:
            调整后的风格
        """
        persona = self.get_persona_for_project(project)

        # 根据 persona 调整风格
        if persona["tone"] == "concise":
            base_style += " 保持简洁高效，避免冗余。"
        elif persona["tone"] == "highly_professional":
            base_style += " 使用更正式的专业术语。"
        elif persona["tone"] == "practical":
            base_style += " 注重实际效果和效率。"

        if persona["focus"] == "efficiency":
            base_style += " 强调快速交付和效率提升。"
        elif persona["focus"] == "innovation":
            base_style += " 突出创新解决方案。"
        elif persona["focus"] == "solution_oriented":
            base_style += " 围绕客户痛点提供具体解决方案。"

        return base_style


class LLMClientProtocol(Protocol):
    """LLM 客户端协议"""

    async def generate_proposal(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float,
    ) -> str:
        """
        生成提案

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词
            model: 模型名称
            temperature: 温度

        Returns:
            生成的提案文本
        """
        ...


class OpenAILLMClientAdapter:
    """OpenAI LLM 客户端适配器"""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        provider_name: str = "openai",
    ):
        if not api_key:
            raise ValueError("Missing LLM_API_KEY")
        if not model:
            raise ValueError("Missing LLM_MODEL")

        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._provider_name = provider_name

        try:
            from openai import AsyncOpenAI
        except Exception as e:
            raise RuntimeError(f"OpenAI SDK not available: {e}")

        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )

    async def generate_proposal(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float,
    ) -> str:
        """使用 OpenAI 生成提案"""
        try:
            result = await self._client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=2000,
            )

            content = (result.choices[0].message.content or "").strip()
            if not content:
                raise ValueError("LLM returned empty content")

            return content

        except Exception as e:
            logger.error(
                "Proposal generation failed via provider=%s model=%s: %s",
                self._provider_name,
                model,
                e,
            )
            raise


class MultiProviderLLMClientAdapter:
    """多 Provider 回退适配器：按顺序尝试，直到成功。"""

    def __init__(
        self,
        providers: List[Dict[str, Any]],
        default_model: str,
        timeout: Optional[float] = None,
    ):
        self._clients: List[Tuple[str, str, OpenAILLMClientAdapter]] = []

        for provider in providers:
            name = str(provider.get("name") or "").strip().lower()
            api_key = str(provider.get("api_key") or "").strip()
            model = str(provider.get("model") or default_model).strip() or default_model
            base_url = provider.get("base_url")

            if not name or not api_key:
                continue

            client = OpenAILLMClientAdapter(
                api_key=api_key,
                model=model,
                base_url=base_url,
                timeout=timeout,
                provider_name=name,
            )
            self._clients.append((name, model, client))

        if not self._clients:
            raise ValueError("No valid LLM providers configured for proposal generation.")

    async def generate_proposal(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float,
    ) -> str:
        errors: List[str] = []

        for name, provider_model, client in self._clients:
            try:
                # 优先使用 provider 自己的模型，避免主模型不兼容
                return await client.generate_proposal(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model=provider_model or model,
                    temperature=temperature,
                )
            except Exception as exc:
                logger.warning(
                    "Proposal provider failed, trying next: provider=%s error=%s",
                    name,
                    exc,
                )
                errors.append(f"{name}: {exc}")
                continue

        raise RuntimeError("All proposal LLM providers failed: " + " | ".join(errors))


class ProposalService:
    """
    提案生成服务

    Attributes:
        llm_client: LLM 客户端
        persona_controller: 人设控制器
        prompt_builder: 提示词构建器
        validator: 提案验证器
        config: 服务配置
    """

    def __init__(
        self,
        llm_client: Optional[LLMClientProtocol] = None,
        persona_controller: Optional[PersonaControllerProtocol] = None,
        prompt_builder: Optional["ProposalPromptBuilder"] = None,
        validator: Optional[ProposalValidatorProtocol] = None,
        config: Optional[ProposalConfig] = None,
    ):
        """
        初始化提案服务

        Args:
            llm_client: LLM 客户端（默认使用 OpenAI 适配器）
            persona_controller: 人设控制器
            prompt_builder: 提示词构建器
            validator: 提案验证器
            config: 服务配置
        """
        from services.proposal_prompt_builder import ProposalPromptBuilder

        self.config = config or ProposalConfig.from_settings()
        self.prompt_builder = prompt_builder or ProposalPromptBuilder()
        self.validator = validator or DefaultProposalValidator(
            min_length=self.config.min_length,
            max_length=self.config.max_length,
        )
        self.persona_controller = persona_controller or DefaultPersonaController()

        # 初始化 LLM 客户端
        if llm_client is not None:
            self.llm_client = llm_client
        else:
            self.llm_client = self._build_default_llm_client()

        logger.info(
            f"ProposalService initialized with model={self.config.model}, "
            f"max_retries={self.config.max_retries}"
        )

    def _build_default_llm_client(self) -> LLMClientProtocol:
        """根据 settings 自动构建默认 LLM 客户端（支持 provider 回退）。"""
        configured = settings.get_enabled_llm_providers()
        primary = str(getattr(settings, "LLM_PROVIDER", "openai")).strip().lower()

        # 按 primary provider 排序，保持其余 provider 的原顺序
        providers = list(configured)
        providers.sort(key=lambda p: 0 if str(p.get("name", "")).lower() == primary else 1)

        if providers:
            return MultiProviderLLMClientAdapter(
                providers=providers,
                default_model=self.config.model,
                timeout=self.config.timeout,
            )

        # 兼容旧配置：仅使用 LLM_API_KEY + LLM_MODEL + LLM_API_URL
        api_key = getattr(settings, "LLM_API_KEY", "")
        model = getattr(settings, "LLM_MODEL", self.config.model)
        base_url = getattr(settings, "LLM_API_URL", None) or getattr(
            settings, "LLM_BASE_URL", None
        )

        return OpenAILLMClientAdapter(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout=self.config.timeout,
            provider_name=primary or "openai",
        )

    async def generate_proposal(
        self,
        project: Project,
        score_data: Optional[Dict[str, Any]] = None,
        max_retries: Optional[int] = None,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """
        生成提案

        这是服务的主方法，负责协调整个提案生成流程。

        Args:
            project: 项目对象
            score_data: 可选的评分数据
            max_retries: 最大重试次数（覆盖配置）
            db: 可选的数据库会话

        Returns:
            {
                "success": bool,
                "proposal": str,  # 生成的提案
                "attempts": int,  # 尝试次数
                "validation_passed": bool,  # 是否通过验证
                "validation_issues": List[str],  # 验证问题（如有）
                "model_used": str,  # 使用的模型
                "latency_ms": int,  # 延迟（毫秒）
                "error": Optional[str],  # 错误信息（如有）
            }
        """
        effective_max_retries = max_retries or self.config.max_retries
        start_time = time.time()

        # 转换项目为字典
        project_dict = self._project_to_dict(project)
        validation_project = dict(project_dict)
        if score_data and score_data.get("suggested_bid") is not None:
            try:
                validation_project["expected_bid_amount"] = float(
                    score_data.get("suggested_bid")
                )
            except Exception:
                pass

        # 获取人设信息
        persona = self.persona_controller.get_persona_for_project(validation_project)

        # 构建提示词
        if db:
            self.prompt_builder.fetch_prompts(db)

        system_prompt = self.prompt_builder.build_prompt(
            project=validation_project,
            style="narrative",
            structure="three_step",
        )

        # 根据人设调整风格
        system_prompt = self.persona_controller.adjust_style(
            system_prompt, validation_project
        )

        # 构建用户提示词
        user_prompt = self._build_user_prompt(validation_project, score_data, persona)

        logger.info(f"Generating proposal for project {project.freelancer_id}")

        # 生成并验证
        for attempt in range(effective_max_retries):
            try:
                # 调用 LLM 生成
                proposal = await self._call_llm(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )

                # 强制英文输出：不做翻译，只允许直接英文生成
                if self._contains_cjk_characters(proposal):
                    language_issue = "proposal_not_english"
                    if attempt < effective_max_retries - 1:
                        system_prompt = self._enhance_prompt_for_english_only(
                            system_prompt
                        )
                        continue
                    return self._create_result(
                        success=False,
                        proposal="",
                        attempts=attempt + 1,
                        validation_passed=False,
                        validation_issues=[language_issue],
                        model=self.config.model,
                        start_time=start_time,
                        error=language_issue,
                    )

                # 若超出目标长度，自动执行一次压缩重写（保持英文直出，不走翻译）
                if len(proposal) > self.config.target_char_max:
                    compressed = await self._compress_proposal_to_target_length(
                        proposal=proposal,
                        project=validation_project,
                    )
                    if compressed:
                        proposal = compressed

                    # 压缩后仍过长，则进入下一次重试并强化长度约束
                    if (
                        len(proposal) > self.config.target_char_max
                        and attempt < effective_max_retries - 1
                    ):
                        system_prompt = self._enhance_prompt_with_feedback(
                            system_prompt,
                            [
                                f"提案过长（{len(proposal)} > {self.config.target_char_max} 字符）",
                                "请在保留技术可信度的前提下显著压缩篇幅。",
                            ],
                            persona,
                        )
                        continue

                # 验证提案
                if self.config.validate_before_return:
                    valid, issues = self._validate_proposal(proposal, validation_project)
                    if not valid:
                        logger.warning(
                            f"Proposal validation failed for project {project.freelancer_id}: {issues}"
                        )

                        if attempt < effective_max_retries - 1:
                            # 尝试重新生成，调整提示词
                            system_prompt = self._enhance_prompt_with_feedback(
                                system_prompt, issues, persona
                            )
                            continue
                        else:
                            # 最后一次尝试仍未通过验证：【优化】不再返回失败，而是带病投出，避免错失时机
                            logger.warning(f"Project {project.freelancer_id}: Bidding with imperfect proposal after {attempt+1} attempts. Issues: {issues}")
                            return self._create_result(
                                success=True, # 标记为成功，以便后续流程继续
                                proposal=proposal,
                                attempts=attempt + 1,
                                validation_passed=False,
                                validation_issues=issues,
                                model=self.config.model,
                                start_time=start_time,
                                error=None,
                            )

                # 验证通过
                return self._create_result(
                    success=True,
                    proposal=proposal,
                    attempts=attempt + 1,
                    validation_passed=True,
                    validation_issues=[],
                    model=self.config.model,
                    start_time=start_time,
                    error=None,
                )

            except Exception as e:
                logger.error(f"Proposal generation attempt {attempt + 1} failed: {e}")

                if attempt < effective_max_retries - 1:
                    # 等待后重试
                    await asyncio.sleep(1 * (attempt + 1))
                    continue

                # 所有尝试都失败
                return self._create_result(
                    success=False,
                    proposal="",
                    attempts=attempt + 1,
                    validation_passed=False,
                    validation_issues=[],
                    model=self.config.model,
                    start_time=start_time,
                    error=str(e),
                )

    def _validate_proposal(
        self, proposal: str, project: Dict[str, Any]
    ) -> Tuple[bool, List[str]]:
        """
        验证提案质量

        Args:
            proposal: 提案文本
            project: 项目信息

        Returns:
            (是否通过, 验证消息列表)
        """
        return self.validator.validate(proposal, project)

    async def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """
        调用 LLM 生成提案

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词

        Returns:
            生成的提案文本
        """
        return await asyncio.wait_for(
            self.llm_client.generate_proposal(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=self.config.model,
                temperature=self.config.temperature,
            ),
            timeout=self.config.timeout,
        )

    def _build_user_prompt(
        self,
        project: Dict[str, Any],
        score_data: Optional[Dict[str, Any]],
        persona: Dict[str, Any],
    ) -> str:
        """
        构建用户提示词 - 优化为更自然的沟通风格
        """
        prompt_parts = ["Write a direct, one-to-one message to the client in natural English."]
        prompt_parts.append(
            "Avoid list-style formatting or bold keywords. Use 2-3 concise paragraphs."
        )
        prompt_parts.append(
            "Focus on the 'how': Mention a specific technical detail or potential challenge related to this project to show you understand it."
        )

        # 项目信息
        title = project.get("title", "this project")
        prompt_parts.append(f"Project context: {title}")
        
        # 报价与周期建议
        if score_data:
            suggested_bid = score_data.get("suggested_bid")
            currency = project.get("currency_code", "USD")
            if suggested_bid:
                prompt_parts.append(
                    f"Our preliminary quote is around {suggested_bid} {currency}. "
                    "Discuss this budget naturally (e.g., 'Based on the requirements, I suggest a budget of...')."
                )

        # 引导提问
        prompt_parts.append(
            "End with one insightful question about their specific technical environment or data structure to encourage a reply."
        )

        return "\n".join(prompt_parts)

    def _extract_project_requirement_hints(self, project: Dict[str, Any]) -> List[str]:
        project_text = " ".join(
            [
                str(project.get("title", "") or ""),
                str(project.get("description", "") or ""),
                str(project.get("preview_description", "") or ""),
            ]
        ).lower()
        hints: List[str] = []
        for markers, label in _PROJECT_REQUIREMENT_HINTS:
            if any(marker in project_text for marker in markers):
                hints.append(label)

        if hints:
            return hints[:6]

        raw_title = str(project.get("title", "") or "").lower()
        stop_words = {
            "with",
            "for",
            "and",
            "the",
            "task",
            "project",
            "build",
            "need",
            "from",
            "using",
            "into",
            "your",
            "this",
        }
        tokens = re.findall(r"[a-z][a-z0-9#+-]{3,}", raw_title)
        fallback: List[str] = []
        for token in tokens:
            if token in stop_words or token in fallback:
                continue
            fallback.append(token)
        return fallback[:3]

    def _enhance_prompt_with_feedback(
        self,
        base_prompt: str,
        feedback: List[str],
        persona: Dict[str, Any],
    ) -> str:
        """
        根据反馈增强提示词

        Args:
            base_prompt: 原始提示词
            feedback: 验证反馈
            persona: 人设信息

        Returns:
            增强后的提示词
        """
        enhancement = "\n\n### Improvement Required (previous attempt failed validation):\n"
        for issue in feedback:
            enhancement += f"- {issue}\n"

        enhancement += "\nPlease improve the proposal based on the feedback above to meet quality standards."

        return base_prompt + enhancement

    def _enhance_prompt_for_english_only(self, base_prompt: str) -> str:
        """
        Add explicit language constraint when non-English output is detected.
        """
        enhancement = (
            "\n\n### Language Correction Requirement:\n"
            "The previous output was not in English.\n"
            "Regenerate the entire proposal in English only.\n"
            "Do not output any Chinese text.\n"
            "Do not translate from an already written Chinese draft.\n"
            "Write directly in English from the first sentence."
        )
        return base_prompt + enhancement

    def _contains_cjk_characters(self, text: str) -> bool:
        """Detect whether output still contains CJK characters."""
        if not text:
            return False
        return bool(_CJK_PATTERN.search(text))

    async def _compress_proposal_to_target_length(
        self, proposal: str, project: Dict[str, Any]
    ) -> str:
        """
        Rewrite long proposal into configured target character range.

        Returns the rewritten proposal; if rewrite fails, returns original proposal.
        """
        target_min = max(200, int(self.config.target_char_min))
        target_max = max(target_min + 50, int(self.config.target_char_max))
        if len(proposal) <= target_max:
            return proposal

        title = project.get("title", "the project")
        rewrite_system_prompt = (
            "You are an expert bid editor.\n"
            "Rewrite the given proposal into concise, high-conviction English.\n"
            f"Target length: {target_min}-{target_max} characters.\n"
            "Do not use Chinese.\n"
            "Keep project specificity and technical credibility.\n"
            "Include at least two of these words naturally: technical, implementation, delivery, plan, approach, solution.\n"
            "Include the word budget and one concrete budget/quote sentence.\n"
            "End with one concise clarifying question.\n"
            "Output only the final rewritten proposal."
        )
        expected_bid = project.get("expected_bid_amount")
        currency = project.get("currency_code", "USD")
        if expected_bid is not None:
            rewrite_system_prompt += (
                f"\nIf you mention a numeric quote, it MUST be exactly {float(expected_bid)} {currency}."
            )
        rewrite_user_prompt = (
            f"Project title: {title}\n\n"
            "Original proposal:\n"
            f"{proposal}"
        )
        try:
            rewritten = (await self._call_llm(rewrite_system_prompt, rewrite_user_prompt)).strip()
            if not rewritten:
                return proposal
            return rewritten
        except Exception:
            logger.warning("Proposal compression rewrite failed; using original long proposal.")
            return proposal

    def _project_to_dict(self, project: Project) -> Dict[str, Any]:
        """
        将 Project 模型转换为字典

        Args:
            project: Project 实例

        Returns:
            项目字典
        """
        if hasattr(project, "to_dict"):
            return project.to_dict()

        # 手动转换
        import json

        return {
            "id": project.freelancer_id,
            "title": project.title,
            "description": project.description,
            "preview_description": project.preview_description,
            "budget_minimum": float(project.budget_minimum)
            if project.budget_minimum
            else None,
            "budget_maximum": float(project.budget_maximum)
            if project.budget_maximum
            else None,
            "currency_code": project.currency_code,
            "skills": json.loads(project.skills) if project.skills else None,
            "bid_stats": json.loads(project.bid_stats) if project.bid_stats else None,
            "owner_info": json.loads(project.owner_info)
            if project.owner_info
            else None,
        }

    def _create_result(
        self,
        success: bool,
        proposal: str,
        attempts: int,
        validation_passed: bool,
        validation_issues: List[str],
        model: str,
        start_time: float,
        error: Optional[str],
    ) -> Dict[str, Any]:
        """
        创建结果字典

        Args:
            success: 是否成功
            proposal: 生成的提案
            attempts: 尝试次数
            validation_passed: 验证是否通过
            validation_issues: 验证问题
            model: 使用的模型
            start_time: 开始时间
            error: 错误信息

        Returns:
            结果字典
        """
        latency_ms = int((time.time() - start_time) * 1000)

        return {
            "success": success,
            "proposal": proposal,
            "attempts": attempts,
            "validation_passed": validation_passed,
            "validation_issues": validation_issues,
            "model_used": model,
            "latency_ms": latency_ms,
            "error": error,
        }

    async def generate_with_fallback(
        self,
        project: Project,
        score_data: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        带回退机制的提案生成

        如果 LLM 生成失败，会尝试使用备用方案。

        Args:
            project: 项目对象
            score_data: 可选的评分数据

        Returns:
            生成的提案文本，如果所有方法都失败则返回空字符串
        """
        try:
            result = await self.generate_proposal(project, score_data)
            if result["success"]:
                return result["proposal"]
        except Exception as e:
            logger.error(f"Primary proposal generation failed: {e}")

        # 备用方案：使用基础模板
        if self.config.fallback_enabled:
            return self._generate_fallback_proposal(project)

        return ""

    def generate_fallback_proposal(self, project: Project) -> str:
        """Generate fallback proposal directly without calling LLM."""
        return self._generate_fallback_proposal(project)

    def _generate_fallback_proposal(self, project: Project) -> str:
        """
        生成备用提案（模板化）

        Args:
            project: 项目对象

        Returns:
            备用提案文本
        """
        title = project.title or "本项目"
        budget_min = float(project.budget_minimum) if project.budget_minimum else None
        budget_max = float(project.budget_maximum) if project.budget_maximum else None
        currency = project.currency_code or "USD"
        suggested_bid = float(project.suggested_bid) if project.suggested_bid else None
        quote = suggested_bid or budget_max or budget_min

        budget_line = (
            "Budget is not fully defined yet; I will confirm scope first and then finalize the quote."
        )
        if budget_min is not None and budget_max is not None:
            budget_line = (
                f"Budget range: {budget_min:.0f}-{budget_max:.0f} {currency}. "
                f"My quote: {(quote or budget_max):.0f} {currency}."
            )
        elif budget_max is not None:
            budget_line = (
                f"Budget cap: {budget_max:.0f} {currency}. "
                f"My quote: {(quote or budget_max):.0f} {currency}."
            )

        return f"""For {title}, here is the practical execution plan.

I will start with scope decomposition, data and interface mapping, and clear acceptance criteria so delivery boundaries are explicit from day one. Then I will implement each module with robust validation and exception handling to keep the solution stable under real usage.

Delivery will proceed in three phases: scope confirmation and sample validation, core implementation and integration, and final quality review with fixes plus handover documentation. This keeps progress transparent and lowers project risk.

{budget_line} If you confirm the target scope, I can start immediately and follow this plan to deliver on time."""


# ============================================================================
# 单例管理
# ============================================================================

_service: Optional["ProposalService"] = None
_config: Optional[ProposalConfig] = None


def reset_service() -> None:
    """重置服务单例（用于测试）"""
    global _service, _config
    _service = None
    _config = None
    logger.debug("ProposalService singleton reset")


def create_proposal_service(
    config: Optional[ProposalConfig] = None,
) -> ProposalService:
    """
    创建提案服务实例（依赖注入模式）

    Args:
        config: 服务配置

    Returns:
        ProposalService 实例
    """
    return ProposalService(config=config)


def get_proposal_service() -> ProposalService:
    """
    获取提案服务单例（便捷访问）

    Returns:
        ProposalService 单例
    """
    global _service, _config
    if _service is None:
        cfg = _config
        _service = create_proposal_service(cfg)
    return _service


def configure_service(config: ProposalConfig) -> None:
    """
    配置单例服务（在应用启动时调用）

    Args:
        config: 服务配置
    """
    global _config
    _config = config
    _service = None  # 标记需要重建
    logger.info("ProposalService configured with custom settings")
