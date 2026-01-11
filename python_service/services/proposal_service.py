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

from config import settings
from database.models import Project

logger = logging.getLogger(__name__)


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
    min_length: int = 200
    max_length: int = 800
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
            min_length=getattr(settings, "PROPOSAL_MIN_LENGTH", 200),
            max_length=getattr(settings, "PROPOSAL_MAX_LENGTH", 800),
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
            "n8n",
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

        # 4. 与项目描述的匹配度检查
        project_desc = (project.get("description") or "").lower()
        if project_desc:
            title_words = set((project.get("title", "") or "").lower().split())
            proposal_words = set(proposal_lower.split())
            common_words = title_words & proposal_words
            if len(common_words) < 3 and len(title_words) > 5:
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

        # 7. 检查是否为空行或仅包含特殊字符
        lines = proposal.split("\n")
        empty_lines = sum(
            1 for line in lines if not line.strip() or re.match(r"^[\s\t\xA0]+$", line)
        )
        if empty_lines > len(lines) * 0.3:
            issues.append(f"空行过多（{empty_lines}/{len(lines)}）")

        return len(issues) == 0, issues

    def get_min_length(self) -> int:
        return self.min_length

    def get_max_length(self) -> int:
        return self.max_length


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

    def __init__(self, api_key: str, model: str, base_url: Optional[str] = None):
        if not api_key:
            raise ValueError("Missing LLM_API_KEY")
        if not model:
            raise ValueError("Missing LLM_MODEL")

        self._api_key = api_key
        self._model = model
        self._base_url = base_url

        try:
            from openai import AsyncOpenAI
        except Exception as e:
            raise RuntimeError(f"OpenAI SDK not available: {e}")

        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

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
            logger.error(f"OpenAI proposal generation failed: {e}")
            raise


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
            api_key = getattr(settings, "LLM_API_KEY", "")
            model = self.config.model
            base_url = getattr(settings, "LLM_BASE_URL", None)
            self.llm_client = OpenAILLMClientAdapter(
                api_key=api_key,
                model=model,
                base_url=base_url,
            )

        logger.info(
            f"ProposalService initialized with model={self.config.model}, "
            f"max_retries={self.config.max_retries}"
        )

    async def generate_proposal(
        self,
        project: Project,
        score_data: Optional[Dict[str, Any]] = None,
        max_retries: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        生成提案

        这是服务的主方法，负责协调整个提案生成流程。

        Args:
            project: 项目对象
            score_data: 可选的评分数据
            max_retries: 最大重试次数（覆盖配置）

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

        # 获取人设信息
        persona = self.persona_controller.get_persona_for_project(project_dict)

        # 构建提示词
        system_prompt = self.prompt_builder.build_prompt(
            project=project_dict,
            style="narrative",
            structure="three_step",
        )

        # 根据人设调整风格
        system_prompt = self.persona_controller.adjust_style(
            system_prompt, project_dict
        )

        # 构建用户提示词
        user_prompt = self._build_user_prompt(project_dict, score_data, persona)

        logger.info(f"Generating proposal for project {project.freelancer_id}")

        # 生成并验证
        for attempt in range(effective_max_retries):
            try:
                # 调用 LLM 生成
                proposal = await self._call_llm(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )

                # 验证提案
                if self.config.validate_before_return:
                    valid, issues = self._validate_proposal(proposal, project_dict)
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
                            # 最后一次尝试，返回带警告的提案
                            return self._create_result(
                                success=True,
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
        return await self.llm_client.generate_proposal(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.config.model,
            temperature=self.config.temperature,
        )

    def _build_user_prompt(
        self,
        project: Dict[str, Any],
        score_data: Optional[Dict[str, Any]],
        persona: Dict[str, Any],
    ) -> str:
        """
        构建用户提示词

        Args:
            project: 项目信息
            score_data: 评分数据
            persona: 人设信息

        Returns:
            用户提示词
        """
        prompt_parts = []

        # 项目摘要
        title = project.get("title", "未命名项目")
        prompt_parts.append(f"项目名称：{title}")

        # 预算信息
        budget_min = project.get("budget_minimum")
        budget_max = project.get("budget_maximum")
        currency = project.get("currency_code", "USD")
        if budget_min is not None and budget_max is not None:
            prompt_parts.append(f"预算范围：{budget_min}-{budget_max} {currency}")

        # 预估工时和报价（如果有）
        if score_data:
            if score_data.get("estimated_hours"):
                prompt_parts.append(f"预估工时：{score_data['estimated_hours']} 小时")
            if score_data.get("suggested_bid"):
                prompt_parts.append(
                    f"建议报价：{score_data['suggested_bid']} {currency}"
                )

        # 人设调整提示
        tone = persona.get("tone", "professional")
        if tone == "concise":
            prompt_parts.append("\n请用简洁直接的方式表达，避免冗余。")
        elif tone == "highly_professional":
            prompt_parts.append("\n请使用正式专业的语言风格。")

        return "\n".join(prompt_parts)

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
        enhancement = "\n\n### 改进要求（上次生成未通过验证）：\n"
        for issue in feedback:
            enhancement += f"- {issue}\n"

        enhancement += "\n请根据以上反馈改进提案，确保质量达标。"

        return base_prompt + enhancement

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

    def _generate_fallback_proposal(self, project: Project) -> str:
        """
        生成备用提案（模板化）

        Args:
            project: 项目对象

        Returns:
            备用提案文本
        """
        title = project.title or "本项目"
        description = project.description or ""

        # 简单模板
        return f"""基于您发布的项目需求，我对{title}有以下理解和方案：

我是一名经验丰富的开发者，对您描述的{title}有深入理解。

我的技术方案：
- 仔细分析了项目需求和交付标准
- 制定了详细的开发计划和里程碑
- 确保代码质量和可维护性

期待与您进一步沟通具体细节。"""


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
