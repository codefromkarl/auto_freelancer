"""Validated non-secret local configuration and an explicit legacy-engine bridge."""

import secrets
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, ConfigDict
from desktop.paths import data_directory, atomic_json


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="", max_length=100)
    skills: list[str] = Field(default_factory=list, max_length=50)
    background: str = Field(default="", max_length=6000)
    minimum_net_hourly: float = Field(default=15, gt=0, le=1000, allow_inf_nan=False)
    maximum_amount: float = Field(default=1000, gt=0, le=100000, allow_inf_nan=False)
    maximum_hours: int = Field(default=40, ge=1, le=2000)

    @field_validator("skills")
    @classmethod
    def skills_are_concise(cls, values):
        if any(not v.strip() or len(v) > 100 for v in values):
            raise ValueError("Skills must be 1–100 characters each")
        return list(dict.fromkeys(v.strip() for v in values))


class Provider(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol: Literal["openai-compatible"] = "openai-compatible"
    base_url: str = "https://api.openai.com/v1"
    model: str = Field(default="", max_length=150)

    @field_validator("base_url")
    @classmethod
    def secure_endpoint(cls, value):
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "Use a direct HTTPS API endpoint without embedded credentials, query or fragment"
            )
        return value.rstrip("/")


class LocalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    revision: int = Field(default=1, ge=1)
    installation_id: str = Field(
        default_factory=lambda: secrets.token_hex(16), pattern=r"^[a-f0-9]{32}$"
    )
    profile: Profile = Field(default_factory=Profile)
    provider: Provider = Field(default_factory=Provider)
    freelancer_user_id: int | None = Field(default=None, gt=0)
    queue_paused: bool = False
    daily_model_tasks: int = Field(default=50, ge=1, le=1000)
    platform_mode: Literal["preview", "automatic"] = "preview"


class ConfigStore:
    def __init__(self, directory=None):
        self.directory = Path(directory or data_directory())
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / "config.json"
        if not self.path.exists():
            self.save(LocalConfig())

    def load(self):
        return LocalConfig.model_validate_json(self.path.read_text(encoding="utf-8"))

    def save(self, config):
        config = LocalConfig.model_validate(config)
        atomic_json(self.path, config.model_dump())
        return config


def engine_overrides(config=None, vault=None, directory=None, worker=False):
    """All engine values are explicit: never inherit a developer .env or credentials."""
    import os
    from desktop.secrets import SecretStore, VaultUnavailable

    directory = Path(directory or data_directory())
    config = config or ConfigStore(directory).load()
    vault = vault or SecretStore(directory)
    try:
        from desktop.redaction import remember

        model_key = remember(vault.get("model_api_key"))
        platform_token = remember(vault.get("freelancer_token"))
    except VaultUnavailable:
        model_key = platform_token = ""
    values = {
        "LOCAL_PRODUCT_MODE": True,
        "FREELANCER_OAUTH_TOKEN": platform_token,
        "FREELANCER_USER_ID": str(config.freelancer_user_id or 0),
        "PYTHON_API_KEY": os.environ.get("BIDMASTER_SESSION_TOKEN")
        or secrets.token_urlsafe(32),
        "FLN_URL": "https://www.freelancer.com",
        "DATABASE_PATH": str(directory / "projects.db"),
        "LOG_FILE": str(directory / "engine.log"),
        "SCORING_CONFIG_PATH": str(directory / "scoring_rules.yaml"),
        "APP_HOST": "127.0.0.1",
        "CORS_ORIGINS": [],
        "OPENAI_API_KEY": "",
        "OPENAI_ENABLED": False,
        "ZHIPU_API_KEY": "",
        "ZHIPU_ENABLED": False,
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_AUTH_TOKEN": "",
        "ANTHROPIC_ENABLED": False,
        "DEEPSEEK_API_KEY": "",
        "DEEPSEEK_ENABLED": False,
        "LLM_PROVIDER": "openai",
        "LLM_API_KEY": model_key,
        "LLM_API_URL": config.provider.base_url,
        "LLM_MODEL": config.provider.model or "not-configured",
        "LLM_SCORING_MODE": "single",
        "DEFAULT_SKILLS": config.profile.skills,
        "RESUME_SKILL_MAPPINGS": {1: config.profile.skills},
        "BID_SUBMISSION_ENABLED": False,
        "BID_APPROVAL_MODE": "automatic" if worker else "qq",
        "BID_MIN_NET_HOURLY_USD": config.profile.minimum_net_hourly,
        "BID_MAX_AMOUNT_USD": config.profile.maximum_amount,
        "BID_MAX_ESTIMATED_HOURS": config.profile.maximum_hours,
        "BID_MIN_AUTO_SCORE": 7,
        "BID_AUTO_REQUIRE_VERIFIED_CLIENT_PAYMENT": True,
        "BID_MAX_DAILY_ATTEMPTS": 1,
        "BID_MAX_DAILY_SCORED_PROJECTS": config.daily_model_tasks,
        "BID_MAX_SCORED_PROJECTS_PER_CYCLE": 20,
        "GITHUB_TOKEN": "",
        "NOTION_TOKEN": "",
        "TRELLO_TOKEN": "",
        "GITLAB_TOKEN": "",
    }
    if worker and config.platform_mode == "automatic":
        from desktop.licensing import require_platform_access

        require_platform_access(directory, config.installation_id, "platform_bid")
        values["BID_SUBMISSION_ENABLED"] = True
    return values
