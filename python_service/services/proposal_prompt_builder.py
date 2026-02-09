"""
Proposal Prompt Builder - 标书提示词构建器

提供模块化的提示词组装功能，支持：
- BASE_SYSTEM_PROMPT: 基础提示词（不包含评分逻辑）
- STYLE_NARRATIVE: 叙事化风格指令（禁止列表，段落式）
- STRUCTURE_THREE_STEP: 三段式结构（痛点→经验→问题）
- build_prompt(project, style, structure): 组装完整提示词
- build_project_context(project, score_data): 构建项目上下文
"""

from typing import Dict, Any, Optional, List
import json
import logging
from pathlib import Path
from sqlalchemy.orm import Session
from config import settings

logger = logging.getLogger(__name__)

RESUME_GUIDE_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "guides" / "个人简历-核心能力.md"
)
BID_REFERENCE_SAMPLES_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "bid_reference_samples.json"
)


# 基础提示词（仅用于评分，不包含提案生成逻辑）
BASE_SYSTEM_PROMPT = """You are an expert Freelancer project evaluator. Your goal is to identify
projects with HIGH WIN RATE and COMPLETION RATE for a senior developer.

PRIMARY GOAL: Maximize win rate and successful project completion, not just profit.

EVALUATION WORKFLOW:
1. Estimate Workload:
   - Simple scripts/automation: 5-15h (small task multiplier 0.1-0.3)
   - Bug fixes/updates: 10-20h
   - API integration/Scraping: 15-30h
   - Mobile apps (iOS/Android): 60-120h+
   - Web Platform: 40-80h+
   - AI/LLM integration: +20h extra complexity

2. Calculate Hourly Rate: (budget_max) / (estimated_hours)
   - $20-60/hour: OPTIMAL for win rate (Score 8-10)
   - $60-80/hour: GOOD but competitive (Score 6-8)
   - $80+/hour: HIGH RISK - hard to win (Score 4-6)
   - $15-20/hour: FAIR (Score 6-8)
   - <$15/hour: LOW VALUE (Score < 5)

3. Assess Competition:
   - 0-4 bids: SUSPICIOUS - likely low quality (Score 2)
   - 5-20 bids: OPTIMAL for win rate (Score 10)
   - 21-40 bids: MODERATE competition (Score 6)
   - >40 bids: HIGH competition - hard to win (Score 2)
   - New projects (<24h old): BONUS - slightly higher score

4. Identify Risks & Clarity:
   - Clarity: Does it name specific deliverables, acceptance criteria, tools?
   - Vague keywords (e.g., "optimize", "insights", "improve") reduce clarity score
   - Long descriptions without technical details are LOW QUALITY signals

SCORING CRITERIA (0-10) - WIN RATE OPTIMIZED:
- Budget Efficiency (15%): $20-60/h is optimal. High rates ($80+) hurt win rate.
- Competition (25%): 5-20 bids is optimal. Too few = bad project, too many = hard to win.
- Requirement Clarity (25%): Specific deliverables and acceptance criteria required.
- Client Trust (20%): Payment verification and hire rate are CRITICAL for completion.
- Technical Match (10%): Must fit standard stacks (Python, API, automation).
- Risk Assessment (5%): Overall project risk evaluation.

SCORING RULES (WIN RATE FOCUS):
- Hourly rate $20-60 MUST result in Budget score >= 8.0.
- Hourly rate $80+ MUST result in Budget score <= 6.0 (hard to win).
- Payment NOT verified MUST result in Client score <= 5.0.
- New client (0 projects) MUST result in Client score <= 5.0.
- Bid count 5-20 MUST result in Competition score >= 8.0.
- Bid count 0-4 MUST result in Competition score <= 3.0 (suspicious).

Return strict JSON only:
{
    "score": 7.5,
    "reason": "Clear explanation (2-3 sentences)",
    "suggested_bid": 500,
    "estimated_hours": 40,
    "hourly_rate": 25.0,
    "risk_keywords": ["insights"]
}
"""


# 叙事化风格指令（禁止列表，段落式）
STYLE_NARRATIVE = """
## 风格要求：叙事化表达

### 必须遵守的规则：
1. **禁止列表格式**：绝对不要使用 Markdown 列表（如 `1.`, `-`, `*`），所有内容必须是完整的段落
2. **段落式表达**：每个要点用完整的句子段落表达，避免碎片化的bullet points
3. **自然流畅**：像写文章一样自然叙述，而非机械填充模板
4. **专业但不死板**：保持专业性，同时具有人情味和说服力

### 段落结构：
- 使用过渡词连接上下文（"首先"、"此外"、"最后"、"因此"等）
- 每个段落3-5个完整句子
- 段落之间逻辑清晰，层层递进
"""


# 三段式结构（痛点→经验→问题）
STRUCTURE_THREE_STEP = """
## 结构要求：三段式提案

### 第一段：痛点共鸣
- 开篇直击客户核心需求和潜在痛点
- 展示对项目背景的深刻理解
- 使用具体场景描述让客户产生共鸣
- 长度：80-120字

### 第二段：经验证词
- 突出与项目相关的成功案例和经验
- 具体说明技术方案的核心优势
- 量化成果（如：提升效率XX%、节省成本XX）
- 长度：150-200字

### 第三段：行动号召
- 提出下一步具体行动（不是空泛的"期待合作"）
- 询问客户最关心的1-2个问题
- 自然引出报价讨论
- 长度：80-120字
"""


class ProposalPromptBuilder:
    """
    提示词构建器

    提供模块化的提示词组装功能，支持不同的风格和结构组合。
    """

    def __init__(
        self,
        base_system_prompt: Optional[str] = None,
        style_instructions: Optional[str] = None,
        structure_instructions: Optional[str] = None,
    ):
        """
        初始化提示词构建器

        Args:
            base_system_prompt: 基础系统提示词（默认使用 BASE_SYSTEM_PROMPT）
            style_instructions: 风格指令（默认使用 STYLE_NARRATIVE）
            structure_instructions: 结构指令（默认使用 STRUCTURE_THREE_STEP）
        """
        self.base_system_prompt = base_system_prompt or BASE_SYSTEM_PROMPT
        self.style_instructions = style_instructions or STYLE_NARRATIVE
        self.structure_instructions = structure_instructions or STRUCTURE_THREE_STEP
        self._resume_markdown_cache: Optional[str] = None
        self._bid_reference_samples_cache: Optional[List[Dict[str, Any]]] = None

        logger.debug("ProposalPromptBuilder initialized with custom instructions")

    def fetch_prompts(self, db: Session):
        """Fetch active prompts from database and update builder state."""
        from database.models import PromptTemplate
        
        # Fetch proposal prompt
        template = db.query(PromptTemplate).filter(
            PromptTemplate.category == "proposal",
            PromptTemplate.is_active == True
        ).order_by(PromptTemplate.created_at.desc()).first()
        
        if template:
            # We use this as base system prompt for proposals
            self.base_system_prompt = template.content
            logger.info(f"Updated proposal base prompt from DB: {template.name}")
        
        # Optional: could also fetch style/structure from DB if we added those categories

    def build_prompt(
        self,
        project: Dict[str, Any],
        style: str = "narrative",
        structure: str = "three_step",
    ) -> str:
        """
        组装完整的提案生成提示词

        Args:
            project: 项目信息字典
            style: 风格选项（当前仅支持 "narrative"）
            structure: 结构选项（当前仅支持 "three_step"）

        Returns:
            完整的系统提示词
        """
        # 获取项目上下文
        project_context = self.build_project_context(project)

        # 根据风格和结构选择对应的指令
        style_section = self._get_style_section(style)
        structure_section = self._get_structure_section(structure)
        reference_section = self.build_bid_reference_context()
        target_char_min = max(200, int(getattr(settings, "PROPOSAL_TARGET_CHAR_MIN", 700)))
        target_char_max = max(target_char_min + 50, int(getattr(settings, "PROPOSAL_TARGET_CHAR_MAX", 1200)))
        hard_char_max = max(target_char_max, int(getattr(settings, "PROPOSAL_MAX_LENGTH", 1800)))

        # 组装完整提示词
        full_prompt = f"""你是 Freelancer 平台的资深开发者，擅长撰写高中标率的提案。

{project_context}

{self.build_resume_context(project)}

{reference_section}

{style_section}

{structure_section}

请基于以上信息，生成一个专业的、自由职业者风格的提案文本。

要求：
- 语言风格：必须全程使用英文（English only），从第一句开始直接英文生成，禁止先写中文再翻译
- 长度控制：目标 {target_char_min}-{target_char_max} 字符；硬上限不超过 {hard_char_max} 字符
- 输出格式：仅输出提案文本内容，不要包含 JSON 或其他包装
- 自然真实：避免模板化、机械化的表达
- 针对性：紧密围绕客户的具体需求展开
- **关键词引用**：必须在投标中自然地引用项目标题中的核心关键词（如技术栈、项目类型等），以展示对项目的理解
- **风控兼容关键词**：正文中必须自然包含以下词汇中的至少两个：technical, implementation, delivery, plan, approach, solution
- **预算表述**：必须包含单词 budget，并给出清晰的预算/报价讨论语句
"""

        return full_prompt

    def _get_style_section(self, style: str) -> str:
        """获取风格指令"""
        style_map = {
            "narrative": STYLE_NARRATIVE,
            "default": STYLE_NARRATIVE,
        }
        return style_map.get(style, STYLE_NARRATIVE)

    def _get_structure_section(self, structure: str) -> str:
        """获取结构指令"""
        structure_map = {
            "three_step": STRUCTURE_THREE_STEP,
            "default": STRUCTURE_THREE_STEP,
        }
        return structure_map.get(structure, STRUCTURE_THREE_STEP)

    def build_project_context(
        self,
        project: Dict[str, Any],
        score_data: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        构建项目上下文描述

        Args:
            project: 项目信息字典
            score_data: 可选的评分数据

        Returns:
            项目上下文描述字符串
        """
        # 提取项目基本信息
        title = project.get("title", "未命名项目")
        description = project.get("description", "") or project.get(
            "preview_description", ""
        )

        # 预算信息
        budget_obj = project.get("budget") or {}
        if not isinstance(budget_obj, dict):
            budget_obj = {}
        budget_min = project.get("budget_minimum") or budget_obj.get("minimum")
        budget_max = project.get("budget_maximum") or budget_obj.get("maximum")
        currency = project.get("currency_code", "USD")

        # 技能要求
        skills = project.get("skills", [])
        if isinstance(skills, str):
            try:
                skills = json.loads(skills)
            except json.JSONDecodeError:
                skills = []

        # 竞争情况
        bid_stats = project.get("bid_stats") or {}
        if isinstance(bid_stats, str):
            try:
                bid_stats = json.loads(bid_stats)
            except json.JSONDecodeError:
                bid_stats = {}
        if not isinstance(bid_stats, dict):
            bid_stats = {}
        bid_count = bid_stats.get("bid_count", 0)

        # 客户信息
        owner_info = project.get("owner_info") or {}
        if isinstance(owner_info, str):
            try:
                owner_info = json.loads(owner_info)
            except json.JSONDecodeError:
                owner_info = {}
        if not isinstance(owner_info, dict):
            owner_info = {}

        # 构建上下文描述
        context_parts = ["### 项目基本信息："]
        context_parts.append(f"- 项目名称：{title}")

        if budget_min is not None and budget_max is not None:
            context_parts.append(f"- 预算范围：{budget_min}-{budget_max} {currency}")
        elif budget_max is not None:
            context_parts.append(f"- 预算上限：{budget_max} {currency}")

        context_parts.append(f"- 当前竞争：{bid_count} 个竞标")

        if skills:
            skills_str = (
                ", ".join(skills[:5]) if isinstance(skills, list) else str(skills)
            )
            context_parts.append(f"- 技能要求：{skills_str}")

        # 添加描述摘要
        if description:
            desc_preview = description[:2000] if len(description) > 2000 else description
            context_parts.append(f"\n### 项目详细描述：\n{desc_preview}")

        # 添加评分数据（如有）
        if score_data:
            context_parts.append("\n### AI 分析结果：")
            if score_data.get("score") is not None:
                context_parts.append(f"- 综合评分：{score_data['score']:.1f}/10")
            if score_data.get("reason"):
                context_parts.append(f"- 评分理由：{score_data['reason']}")
            if score_data.get("estimated_hours"):
                context_parts.append(
                    f"- 预估工时：{score_data['estimated_hours']} 小时"
                )
            if score_data.get("suggested_bid"):
                context_parts.append(
                    f"- 建议报价：{score_data['suggested_bid']} {currency}"
                )

        return "\n".join(context_parts)

    def _load_resume_markdown(self) -> str:
        """Load resume guide markdown from docs; best-effort only."""
        if self._resume_markdown_cache is not None:
            return self._resume_markdown_cache

        try:
            self._resume_markdown_cache = RESUME_GUIDE_PATH.read_text(encoding="utf-8")
        except Exception:
            self._resume_markdown_cache = ""
        return self._resume_markdown_cache

    def build_resume_context(self, project: Dict[str, Any]) -> str:
        """
        Build concise career profile context from resume for proposal prompting.
        """
        project_text = " ".join(
            [
                str(project.get("title", "")),
                str(project.get("description", "")),
                str(project.get("preview_description", "")),
                json.dumps(project.get("skills", []), ensure_ascii=False),
            ]
        ).lower()

        category_desc = {
            101: "Backend/API engineering with Python, FastAPI, Java, Spring Boot, and Spring Cloud.",
            102: "Microservice architecture including service discovery, configuration center, API gateway, and service governance.",
            103: "Security and auth implementation with OAuth2, RBAC, and API authorization.",
            104: "AI/LLM engineering with LangChain, RAG retrieval, vector databases, multi-LLM integration, and prompt engineering.",
            105: "Database delivery across MySQL, SQLite, SQL modeling, and enterprise persistence layers.",
            106: "Containerized delivery with Docker, Docker Compose, DevOps pipelines, and production-oriented deployment.",
            107: "Media processing with FFmpeg for video composition and subtitle rendering.",
        }

        matched_ids: List[int] = []
        for cid, keywords in settings.RESUME_SKILL_MAPPINGS.items():
            if any(str(keyword).lower() in project_text for keyword in keywords):
                matched_ids.append(cid)

        if not matched_ids:
            matched_ids = [101, 104, 106]

        skills_text = "\n".join(
            f"- {category_desc.get(cid, 'Relevant professional capability.')}"
            for cid in matched_ids[:4]
        )

        resume_md = self._load_resume_markdown()
        highlights: List[str] = []
        if "100+并发请求" in resume_md:
            highlights.append(
                "Delivered AI systems handling 100+ concurrent requests in production scenarios."
            )
        if "<2秒" in resume_md or "<3秒" in resume_md:
            highlights.append(
                "Optimized response latency with sub-2s dialogue and sub-3s retrieval performance."
            )
        if "效率提升15-26%" in resume_md:
            highlights.append(
                "Improved end-to-end media generation efficiency by 15-26% via parallelized workflows."
            )
        if "19个REST端点" in resume_md:
            highlights.append(
                "Built and maintained a full automation backend with 19 REST endpoints across core modules."
            )

        if not highlights:
            highlights.append(
                "Hands-on delivery across AI platforms, microservices, and workflow automation systems."
            )

        highlights_text = "\n".join(f"- {item}" for item in highlights[:3])

        return (
            "### 候选人职业背景（来自个人简历-核心能力）\n"
            f"{skills_text}\n"
            "### 候选人可证明的项目成绩\n"
            f"{highlights_text}"
        )

    def _load_bid_reference_samples(self) -> List[Dict[str, Any]]:
        """Load shortlisted bid reference samples for style guidance."""
        if self._bid_reference_samples_cache is not None:
            return self._bid_reference_samples_cache

        try:
            payload = json.loads(
                BID_REFERENCE_SAMPLES_PATH.read_text(encoding="utf-8")
            )
            samples = payload.get("samples", [])
            if isinstance(samples, list):
                self._bid_reference_samples_cache = [
                    item for item in samples if isinstance(item, dict)
                ]
            else:
                self._bid_reference_samples_cache = []
        except Exception:
            self._bid_reference_samples_cache = []

        return self._bid_reference_samples_cache

    def build_bid_reference_context(self) -> str:
        """
        Build style/structure references from curated real bid samples.
        """
        samples = self._load_bid_reference_samples()
        if not samples:
            return ""

        lines = ["### 高质量投标参考（仅参考风格与结构，禁止照搬原文）"]
        for sample in samples[:4]:
            author = str(sample.get("author", "Unknown"))
            tags = sample.get("style_tags", [])
            strengths = sample.get("strengths", [])
            char_range = str(sample.get("length_chars_range", "700-1200"))
            tag_text = ", ".join(str(t) for t in tags[:3]) if isinstance(tags, list) else "structured"
            strength_text = (
                "; ".join(str(s) for s in strengths[:2]) if isinstance(strengths, list) else "clear scope and milestones"
            )
            lines.append(
                f"- {author}: style={tag_text}; length≈{char_range}; strengths={strength_text}"
            )

        lines.append("- 仅吸收其逻辑与表达节奏，不要复用具体句子。")
        return "\n".join(lines)

    def build_scoring_prompt(self, project: Dict[str, Any]) -> str:
        """
        构建仅用于评分的提示词（无提案生成逻辑）

        Args:
            project: 项目信息字典

        Returns:
            评分专用的系统提示词
        """
        project_context = self.build_project_context(project)

        return f"""你是 Freelancer 平台的资深项目评估专家。

{self.base_system_prompt}

项目信息：
{project_context}

请根据以上信息评估项目并返回 JSON 结果。
"""

    def get_system_prompt_for_scoring(self) -> str:
        """
        获取仅用于评分的系统提示词（纯评分，不含提案生成）

        Returns:
            纯评分系统提示词
        """
        return self.base_system_prompt


# 单例模式
_builder: Optional["ProposalPromptBuilder"] = None


def get_proposal_prompt_builder() -> ProposalPromptBuilder:
    """
    获取提示词构建器单例

    Returns:
        ProposalPromptBuilder 实例
    """
    global _builder
    if _builder is None:
        _builder = ProposalPromptBuilder()
    return _builder


def reset_prompt_builder() -> None:
    """重置提示词构建器单例（用于测试）"""
    global _builder
    _builder = None
