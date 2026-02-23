"""
Template Filler Service - 模板动态填充服务

自动从项目信息中提取关键要素,填充投标模板占位符:
- [具体需求]: 从项目标题/描述中提取核心需求
- [相关领域]: 匹配技能标签到专业领域
- [类似案例]: 从简历中选择相关项目经验
- [具体成果]: 量化成果描述
- [解决方案]: 针对需求生成技术方案
- [技术优势]: 突出相关技术能力
- [量化收益]: 预估项目价值提升
- [链接]: 作品集/GitHub链接
"""

import re
import json
import logging
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)

# 技能到领域的映射
SKILL_TO_DOMAIN_MAP = {
    "python": "Python backend development",
    "fastapi": "FastAPI microservices",
    "django": "Django full-stack development",
    "flask": "Flask API development",
    "api": "RESTful API design",
    "automation": "workflow automation",
    "scraping": "data scraping and extraction",
    "web scraping": "web data extraction",
    "data extraction": "data extraction and cleaning",
    "llm": "LLM integration",
    "ai": "AI application development",
    "machine learning": "machine learning",
    "chatbot": "intelligent chatbot systems",
    "docker": "containerized deployment",
    "mysql": "MySQL database design",
    "postgresql": "PostgreSQL database",
    "oauth": "OAuth2 authentication",
    "jwt": "JWT token authentication",
    "microservices": "microservice architecture",
    "spring boot": "Spring Boot development",
    "java": "Java enterprise development",
}

# 需求关键词到解决方案的映射
REQUIREMENT_TO_SOLUTION_MAP = {
    "scraping": "Implement dynamic page scraping with Playwright/Selenium, including proxy rotation and anti-bot strategies for stability",
    "api": "Design RESTful API architecture using FastAPI for high-performance async endpoints, with comprehensive documentation and testing",
    "automation": "Build automated workflows with scheduled tasks, error retry mechanisms, and logging/monitoring",
    "chatbot": "Integrate LLM APIs (OpenAI/Claude) with context management and multi-turn conversation support",
    "dashboard": "Develop admin dashboard with data visualization, role-based access control, and operation logs",
    "database": "Design normalized data models, optimize query performance, implement backup and migration solutions",
    "authentication": "Implement OAuth2/JWT authentication with multi-role permission management",
    "deployment": "Configure Docker containerization, set up CI/CD pipelines, provide DevOps documentation",
    "testing": "Write unit and integration tests ensuring >80% code coverage",
    "optimization": "Performance analysis and optimization including database indexing, caching strategies, and async processing",
}

# 技术优势模板
TECH_ADVANTAGE_TEMPLATES = {
    "python": "8 years Python development experience, proficient in FastAPI/Django for high-concurrency backend systems",
    "api": "Designed complete API systems with 19 REST endpoints supporting 100+ concurrent requests",
    "ai": "Delivered multiple AI platform projects with <2s dialogue response and <3s retrieval performance",
    "automation": "Built complete automation pipelines achieving 15-26% efficiency improvement",
    "microservices": "Hands-on microservice architecture experience including service discovery, config center, and API gateway",
    "docker": "Containerization deployment expert providing production-grade DevOps solutions",
}

# 量化收益模板
QUANTIFIED_BENEFIT_TEMPLATES = {
    "automation": "Automated workflows can save 60-80% manual operation time",
    "api": "High-performance API design can support 10x concurrent traffic growth",
    "optimization": "Performance optimization typically improves response speed by 30-50%",
    "ai": "AI integration can reduce repetitive work costs by 70%",
    "scraping": "Automated data collection can replace 90% manual gathering work",
}


class TemplateFillerService:
    """模板动态填充服务"""

    def __init__(self, portfolio_link: str = "https://github.com/yourusername"):
        """
        初始化服务

        Args:
            portfolio_link: 作品集链接
        """
        self.portfolio_link = portfolio_link

    def fill_template(
        self,
        template: str,
        project: Dict[str, Any],
        score_data: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        填充模板占位符

        Args:
            template: 模板字符串
            project: 项目信息
            score_data: 评分数据

        Returns:
            填充后的文本
        """
        # 提取项目信息
        title = project.get("title", "")
        description = project.get("description", "") or project.get("preview_description", "")
        skills = self._parse_skills(project.get("skills", []))

        # 组合项目文本用于分析
        project_text = f"{title} {description}".lower()

        # 填充各个占位符
        filled = template
        filled = filled.replace("[具体需求]", self._extract_requirement(project_text, title))
        filled = filled.replace("[相关领域]", self._match_domain(skills, project_text))
        filled = filled.replace("[类似案例]", self._select_case_study(skills, project_text))
        filled = filled.replace("[具体成果]", self._generate_achievement(skills, project_text))
        filled = filled.replace("[针对需求1的解决方案]", self._generate_solution(project_text, 1))
        filled = filled.replace("[针对需求2的技术优势]", self._generate_tech_advantage(skills, project_text))
        filled = filled.replace("[量化收益]", self._estimate_benefit(project_text))
        filled = filled.replace("[链接]", self.portfolio_link)

        return filled

    def _parse_skills(self, skills: Any) -> List[str]:
        """解析技能列表"""
        if isinstance(skills, str):
            try:
                skills = json.loads(skills)
            except:
                return []
        if isinstance(skills, list):
            return [str(s).lower() for s in skills]
        return []

    def _extract_requirement(self, project_text: str, title: str) -> str:
        """
        从项目中提取核心需求

        策略:
        1. 优先从标题中提取动词+名词组合
        2. 识别常见需求模式(build/create/develop + 对象)
        3. 回退到技术关键词
        """
        # 模式1: 动词+对象
        patterns = [
            r"(build|create|develop|design|implement)\s+(?:a\s+)?(\w+(?:\s+\w+){0,2})",
            r"(automate|scrape|extract|integrate)\s+(\w+(?:\s+\w+){0,2})",
            r"(\w+)\s+(automation|scraping|api|dashboard|system|platform)",
        ]

        for pattern in patterns:
            match = re.search(pattern, project_text, re.IGNORECASE)
            if match:
                return f"{match.group(1)} {match.group(2)}".strip()

        # 模式2: 从标题提取关键名词
        title_lower = title.lower()
        for keyword in ["api", "scraping", "automation", "dashboard", "chatbot", "system"]:
            if keyword in title_lower:
                return f"{keyword} development"

        # 回退: 通用描述
        return "custom solution development"

    def _match_domain(self, skills: List[str], project_text: str) -> str:
        """
        匹配专业领域

        策略:
        1. 从技能标签中匹配最相关的领域
        2. 结合项目描述中的关键词
        3. 返回最匹配的1-2个领域
        """
        matched_domains = []

        # 从技能标签匹配
        for skill in skills:
            domain = SKILL_TO_DOMAIN_MAP.get(skill)
            if domain and domain not in matched_domains:
                matched_domains.append(domain)

        # 从项目文本匹配
        for keyword, domain in SKILL_TO_DOMAIN_MAP.items():
            if keyword in project_text and domain not in matched_domains:
                matched_domains.append(domain)

        if not matched_domains:
            return "full-stack development and automation"

        # 返回前2个最相关的领域
        return " and ".join(matched_domains[:2])

    def _select_case_study(self, skills: List[str], project_text: str) -> str:
        """
        选择相关案例

        策略:
        1. 根据项目类型匹配案例库
        2. 优先选择技术栈匹配度高的案例
        """
        # 案例库(从简历中提取)
        case_studies = {
            "ai": "AI dialogue platform handling 100+ concurrent requests with <2s response time",
            "api": "RESTful backend with 19 endpoints serving production traffic",
            "automation": "Media generation workflow achieving 15-26% efficiency improvement",
            "scraping": "Data extraction system processing 10K+ pages daily",
            "microservices": "Microservice architecture with service discovery and API gateway",
        }

        # 匹配案例
        for keyword, case in case_studies.items():
            if keyword in project_text or keyword in " ".join(skills):
                return case

        # 默认案例
        return "enterprise-level backend systems with proven scalability"

    def _generate_achievement(self, skills: List[str], project_text: str) -> str:
        """
        生成具体成果描述

        策略:
        1. 根据项目类型选择量化指标
        2. 使用真实简历数据
        """
        achievements = {
            "ai": "100+ concurrent requests, <2s dialogue response",
            "api": "19 REST endpoints, production-grade reliability",
            "automation": "15-26% efficiency improvement via parallelization",
            "performance": "sub-3s retrieval performance optimization",
        }

        for keyword, achievement in achievements.items():
            if keyword in project_text or keyword in " ".join(skills):
                return achievement

        return "proven delivery track record across multiple production systems"

    def _generate_solution(self, project_text: str, priority: int = 1) -> str:
        """
        生成针对性解决方案

        Args:
            project_text: 项目文本
            priority: 优先级(1=主要方案, 2=次要方案)
        """
        matched_solutions = []

        for keyword, solution in REQUIREMENT_TO_SOLUTION_MAP.items():
            if keyword in project_text:
                matched_solutions.append(solution)

        if not matched_solutions:
            return "Deliver a robust, well-tested solution with comprehensive documentation"

        # 返回对应优先级的方案
        index = min(priority - 1, len(matched_solutions) - 1)
        return matched_solutions[index]

    def _generate_tech_advantage(self, skills: List[str], project_text: str) -> str:
        """
        生成技术优势描述

        策略:
        1. 匹配技能标签到优势模板
        2. 结合项目需求突出相关能力
        """
        matched_advantages = []

        # 从技能匹配
        for skill in skills:
            advantage = TECH_ADVANTAGE_TEMPLATES.get(skill)
            if advantage:
                matched_advantages.append(advantage)

        # 从项目文本匹配
        for keyword, advantage in TECH_ADVANTAGE_TEMPLATES.items():
            if keyword in project_text and advantage not in matched_advantages:
                matched_advantages.append(advantage)

        if not matched_advantages:
            return "8+ years full-stack development experience with proven delivery capability"

        return matched_advantages[0]

    def _estimate_benefit(self, project_text: str) -> str:
        """
        预估量化收益

        策略:
        1. 根据项目类型匹配收益模板
        2. 使用保守估计避免过度承诺
        """
        for keyword, benefit in QUANTIFIED_BENEFIT_TEMPLATES.items():
            if keyword in project_text:
                return benefit

        return "significant improvement in operational efficiency and cost reduction"


# 默认模板
DEFAULT_PROPOSAL_TEMPLATE = """Hi,

I noticed your project requires [具体需求]. With 8+ years specializing in [相关领域], I've helped clients like [类似案例] achieve [具体成果].

**Why I'm a great fit:**
- ✅ [针对需求1的解决方案]
- ✅ [针对需求2的技术优势]
- 📊 Portfolio: [链接]

I focus on building long-term partnerships through consistent quality. My clients typically see [量化收益].

**Next steps:**
Available for a quick call this week to discuss your specific requirements.

Best regards,
Yuanzhi"""


def create_template_filler(portfolio_link: str = "https://github.com/yourusername") -> TemplateFillerService:
    """
    创建模板填充服务实例

    Args:
        portfolio_link: 作品集链接

    Returns:
        TemplateFillerService实例
    """
    return TemplateFillerService(portfolio_link=portfolio_link)


# 便捷函数
def fill_proposal_template(
    project: Dict[str, Any],
    template: Optional[str] = None,
    portfolio_link: str = "https://github.com/yourusername",
    score_data: Optional[Dict[str, Any]] = None,
) -> str:
    """
    填充投标模板(便捷函数)

    Args:
        project: 项目信息
        template: 模板字符串(默认使用DEFAULT_PROPOSAL_TEMPLATE)
        portfolio_link: 作品集链接
        score_data: 评分数据

    Returns:
        填充后的投标文本
    """
    service = create_template_filler(portfolio_link)
    template_text = template or DEFAULT_PROPOSAL_TEMPLATE
    return service.fill_template(template_text, project, score_data)
