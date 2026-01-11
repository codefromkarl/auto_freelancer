"""
Configuration management for Freelancer Python API Service.
"""

from pydantic_settings import BaseSettings
from typing import Optional, List, Dict, Any


class LLMConfig(BaseSettings):
    """Single LLM provider configuration."""
    api_key: str = ""
    base_url: Optional[str] = None
    model: str = "gpt-4o-mini"
    enabled: bool = True


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Freelancer API Configuration
    FREELANCER_OAUTH_TOKEN: str
    FREELANCER_USER_ID: str
    FLN_URL: str = "https://www.freelancer.com"

    # API Configuration
    PYTHON_API_KEY: str
    API_V1_PREFIX: str = "/api/v1"

    # LLM 配置（支持多个 API 并行调用）
    # 支持的 provider: openai, zhipu, anthropic, deepseek
    LLM_PROVIDER: str = "openai"

    # OpenAI 配置
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_ENABLED: bool = True

    # Zhipu AI (GLM) 配置
    ZHIPU_API_KEY: str = ""
    ZHIPU_MODEL: str = "glm-4"
    ZHIPU_API_URL: str = "https://open.bigmodel.cn/api/paas/v4"
    ZHIPU_ENABLED: bool = True

    # Anthropic Claude 配置
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-3-5-sonnet-20241022"
    ANTHROPIC_ENABLED: bool = False

    # DeepSeek 配置
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_MODEL: str = "deepseek-chat"
    DEEPSEEK_API_URL: str = "https://api.deepseek.com"
    DEEPSEEK_ENABLED: bool = False

    # 默认主要 LLM (用于非并行场景)
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_API_URL: Optional[str] = None

    # Database Configuration
    DATABASE_PATH: str = "/app/data/freelancer.db"

    # Logging Configuration
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "/app/logs/python_service.log"

    # Application Configuration
    APP_NAME: str = "Freelancer Python API"
    APP_VERSION: str = "1.0.0"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    # Timezone
    TZ: str = "Asia/Shanghai"

    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 60

    # Freelancer API 侧缓存/限流（方向四：客户风控会显著增加 getUser 调用次数）
    # 说明：默认值偏保守，避免触发 Freelancer 侧 429；可通过环境变量覆盖
    FREELANCER_USER_CACHE_TTL_SECONDS: int = 600
    FREELANCER_REVIEWS_CACHE_TTL_SECONDS: int = 600

    # Business Logic Configuration
    DEFAULT_SKILLS: List[str] = [
        "python",
        "n8n",
        "automation",
        "api",
        "webhook",
        "docker",
        "fastapi",
        "sql",
        "workflow",
    ]

    CURRENCY_RATES: Dict[str, float] = {
        "USD": 1.0,
        "EUR": 1.1,
        "GBP": 1.3,
        "INR": 0.012,
        "CAD": 0.75,
        "AUD": 0.65,
        "SGD": 0.74,
        "NZD": 0.60,
        "HKD": 0.13,
        "JPY": 0.0067,
        "CNY": 0.14,
        "MYR": 0.22,
        "PHP": 0.018,
        "THB": 0.028,
    }

    # 简历核心技能匹配配置 (技能ID -> 匹配关键词)
    RESUME_SKILL_MAPPINGS: Dict[int, List[str]] = {
        # Python后端
        101: ["python", "fastapi", "flask", "django", "backend", "api"],
        # 微服务
        102: ["microservice", "spring boot", "spring cloud", "grpc", "kafka"],
        # 安全认证
        103: ["oauth", "jwt", "authentication", "rbac", "security"],
        # AI/大模型
        104: [
            "ai",
            "llm",
            "langchain",
            "rag",
            "openai",
            "claude",
            "gpt",
            "embedding",
            "vector",
        ],
        # 数据库
        105: ["mysql", "postgresql", "mongodb", "sql", "database", "mybatis"],
        # 容器化
        106: ["docker", "kubernetes", "k8s", "container", "devops", "ci/cd"],
        # FFmpeg媒体
        107: ["ffmpeg", "video", "audio", "media", "streaming"],
    }

    # 初筛阈值
    MIN_BUDGET_THRESHOLD: float = 20.0  # 最低预算阈值 (USD)
    MIN_DESCRIPTION_LENGTH: int = 30  # 最小描述长度
    ALLOWED_STATUSES: List[str] = [
        "active",
        "open",
        "open_for_bidding",
    ]  # 允许的项目状态

    # Project Kick-off Automation (方向六：中标后的"瞬间启动"工作流)
    KICKOFF_REPO_PROVIDER: str = "github"  # github, gitlab
    KICKOFF_COLLAB_PROVIDER: str = "notion"  # notion, trello
    GITHUB_TOKEN: str = ""
    GITHUB_USERNAME: str = ""
    GITLAB_TOKEN: str = ""
    GITLAB_URL: str = "https://gitlab.com"
    NOTION_TOKEN: str = ""
    NOTION_PROJECTS_DB_ID: str = ""
    TRELLO_API_KEY: str = ""
    TRELLO_TOKEN: str = ""

    # External Scoring Configuration
    SCORING_CONFIG_PATH: str = "python_service/config/scoring_rules.yaml"
    _scoring_rules: Optional[Dict[str, Any]] = None

    @property
    def scoring_rules(self) -> Dict[str, Any]:
        """Lazy load scoring rules from YAML."""
        if self._scoring_rules is None:
            import yaml
            import os
            if os.path.exists(self.SCORING_CONFIG_PATH):
                try:
                    with open(self.SCORING_CONFIG_PATH, "r", encoding="utf-8") as f:
                        self._scoring_rules = yaml.safe_load(f)
                except Exception as e:
                    print(f"Error loading scoring rules: {e}")
            
            if self._scoring_rules is None:
                # Fallback to defaults if file missing or error
                self._scoring_rules = {
                    "weights": {
                        "budget_efficiency": 0.15,
                        "competition": 0.25,
                        "clarity": 0.25,
                        "customer": 0.20,
                        "tech": 0.10,
                        "risk": 0.05
                    }
                }
        return self._scoring_rules

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # 忽略未定义的 env 变量

    def get_enabled_llm_providers(self) -> List[Dict[str, Any]]:
        """
        Get list of enabled LLM providers for parallel processing.

        Returns:
            List of provider configs with 'name', 'api_key', 'base_url', 'model'
        """
        providers = []

        if self.OPENAI_ENABLED and self.OPENAI_API_KEY:
            providers.append({
                "name": "openai",
                "api_key": self.OPENAI_API_KEY,
                "base_url": None,
                "model": self.OPENAI_MODEL,
            })

        if self.ZHIPU_ENABLED and self.ZHIPU_API_KEY:
            # Zhipu API URL handling
            base_url = self.ZHIPU_API_URL
            if base_url:
                if "chat/completions" in base_url:
                    base_url = base_url.replace("chat/completions", "")
                if base_url.endswith("/"):
                    base_url = base_url[:-1]
            providers.append({
                "name": "zhipu",
                "api_key": self.ZHIPU_API_KEY,
                "base_url": base_url,
                "model": self.ZHIPU_MODEL,
            })

        if self.ANTHROPIC_ENABLED and self.ANTHROPIC_API_KEY:
            providers.append({
                "name": "anthropic",
                "api_key": self.ANTHROPIC_API_KEY,
                "base_url": None,
                "model": self.ANTHROPIC_MODEL,
            })

        if self.DEEPSEEK_ENABLED and self.DEEPSEEK_API_KEY:
            providers.append({
                "name": "deepseek",
                "api_key": self.DEEPSEEK_API_KEY,
                "base_url": self.DEEPSEEK_API_URL,
                "model": self.DEEPSEEK_MODEL,
            })

        return providers

    def get_default_llm(self) -> Dict[str, Any]:
        """
        Get default LLM provider config for backward compatibility.

        Returns:
            Dict with 'api_key', 'base_url', 'model'
        """
        # 优先使用 OPENAI
        if self.OPENAI_ENABLED and self.OPENAI_API_KEY:
            return {
                "api_key": self.OPENAI_API_KEY,
                "base_url": None,
                "model": self.OPENAI_MODEL,
            }

        # 其次使用 Zhipu
        if self.ZHIPU_ENABLED and self.ZHIPU_API_KEY:
            base_url = self.ZHIPU_API_URL
            if base_url:
                if "chat/completions" in base_url:
                    base_url = base_url.replace("chat/completions", "")
                if base_url.endswith("/"):
                    base_url = base_url[:-1]
            return {
                "api_key": self.ZHIPU_API_KEY,
                "base_url": base_url,
                "model": self.ZHIPU_MODEL,
            }

        # 再次使用 LLM_API_KEY (旧配置兼容)
        if self.LLM_API_KEY:
            base_url = self.LLM_API_URL
            if self.LLM_PROVIDER == "zhipu" and base_url:
                if "chat/completions" in base_url:
                    base_url = base_url.replace("chat/completions", "")
                if base_url.endswith("/"):
                    base_url = base_url[:-1]
            return {
                "api_key": self.LLM_API_KEY,
                "base_url": base_url,
                "model": self.LLM_MODEL,
            }

        raise ValueError("No valid LLM API key configured")


# Global settings instance
settings = Settings()
