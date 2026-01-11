"""
LLM Provider 工厂模块 - Factory Pattern 实现。

提供统一的 LLM Provider 创建和管理接口，
支持动态添加新 Provider 而无需修改现有代码。

支持的 Provider:
- openai (OpenAI, DeepSeek, Azure OpenAI 等兼容 API)
- anthropic (Anthropic Claude)
- zhipu (智谱 AI)
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Type, TypeVar, Generic
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)

T = TypeVar("T")


# =============================================================================
# Provider 接口与配置
# =============================================================================


@dataclass
class ProviderCredentials:
    """
    Provider 凭据配置。

    Attributes:
        api_key: API 密钥
        base_url: API 基础 URL（可选）
        org_id: 组织 ID（部分 provider 需要）
    """

    api_key: str
    base_url: Optional[str] = None
    org_id: Optional[str] = None


@dataclass
class ProviderConfig:
    """
    Provider 配置。

    Attributes:
        name: Provider 标识符
        display_name: 显示名称
        credentials: 凭据
        model: 默认模型
        timeout: 超时时间（秒）
        max_retries: 最大重试次数
        enabled: 是否启用
    """

    name: str
    display_name: str
    credentials: ProviderCredentials
    model: str = "gpt-4o-mini"
    timeout: float = 30.0
    max_retries: int = 3
    enabled: bool = True


class LLMProviderInterface(ABC):
    """
    LLM Provider 抽象接口。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider 名称"""
        pass

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Provider 是否可用"""
        pass

    @abstractmethod
    def create_client(self):
        """创建客户端实例"""
        pass

    @abstractmethod
    async def close(self, client):
        """关闭客户端"""
        pass


# =============================================================================
# 具体 Provider 实现
# =============================================================================


class OpenAIProvider(LLMProviderInterface):
    """
    OpenAI 兼容 Provider。

    支持 OpenAI、DeepSeek、Azure 等兼容 OpenAI API 的服务。
    """

    def __init__(self, config: ProviderConfig, client_type: str = "openai"):
        """
        初始化 Provider。

        Args:
            config: Provider 配置
            client_type: 客户端类型标识
        """
        self.config = config
        self.client_type = client_type

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def is_available(self) -> bool:
        return self.config.enabled and bool(self.config.credentials.api_key)

    def create_client(self):
        """创建 OpenAI 兼容客户端"""
        try:
            from openai import AsyncOpenAI

            return AsyncOpenAI(
                api_key=self.config.credentials.api_key,
                base_url=self.config.credentials.base_url,
                timeout=self.config.timeout,
                max_retries=self.config.max_retries,
            )
        except ImportError as e:
            logger.error(f"Failed to import OpenAI: {e}")
            raise RuntimeError("OpenAI package not installed")

    async def close(self, client):
        """关闭客户端"""
        if hasattr(client, "close"):
            await client.close()


class AnthropicProvider(LLMProviderInterface):
    """
    Anthropic Claude Provider。
    """

    def __init__(self, config: ProviderConfig):
        self.config = config

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def is_available(self) -> bool:
        return self.config.enabled and bool(self.config.credentials.api_key)

    def create_client(self):
        """创建 Anthropic 客户端"""
        try:
            from anthropic import AsyncAnthropic

            return AsyncAnthropic(
                api_key=self.config.credentials.api_key,
                timeout=self.config.timeout,
            )
        except ImportError as e:
            logger.error(f"Failed to import Anthropic: {e}")
            raise RuntimeError("Anthropic package not installed")

    async def close(self, client):
        """关闭客户端"""
        if hasattr(client, "close"):
            await client.close()


# =============================================================================
# Provider 注册表
# =============================================================================


class ProviderRegistry:
    """
    Provider 注册表。

    管理所有可用的 Provider 类和实例。
    """

    def __init__(self):
        self._providers: Dict[str, Type[LLMProviderInterface]] = {}
        self._instances: Dict[str, LLMProviderInterface] = {}

    def register(self, name: str, provider_class: Type[LLMProviderInterface]) -> None:
        """
        注册 Provider 类。

        Args:
            name: Provider 名称
            provider_class: Provider 类
        """
        self._providers[name] = provider_class
        logger.info(f"Registered provider: {name}")

    def get(self, name: str) -> Optional[Type[LLMProviderInterface]]:
        """
        获取 Provider 类。

        Args:
            name: Provider 名称

        Returns:
            Provider 类，未找到返回 None
        """
        return self._providers.get(name)

    def create(
        self, name: str, config: ProviderConfig
    ) -> Optional[LLMProviderInterface]:
        """
        创建 Provider 实例。

        Args:
            name: Provider 名称
            config: Provider 配置

        Returns:
            Provider 实例，未找到返回 None
        """
        provider_class = self.get(name)
        if provider_class is None:
            logger.error(f"Unknown provider: {name}")
            return None

        instance = provider_class(config)
        self._instances[name] = instance
        return instance

    def get_instance(self, name: str) -> Optional[LLMProviderInterface]:
        """
        获取已创建的 Provider 实例。

        Args:
            name: Provider 名称

        Returns:
            Provider 实例，未找到返回 None
        """
        return self._instances.get(name)

    def list_registered(self) -> list:
        """列出所有已注册的 Provider"""
        return list(self._providers.keys())


# 全局注册表
registry = ProviderRegistry()

# 注册默认 Provider
registry.register("openai", OpenAIProvider)
registry.register("anthropic", AnthropicProvider)


# =============================================================================
# Provider 工厂
# =============================================================================


class LLMProviderFactory:
    """
    LLM Provider 工厂。

    简化 Provider 的创建和管理，
    支持从配置创建 Provider 实例。
    """

    # 默认 Provider 配置模板
    PROVIDER_TEMPLATES = {
        "openai": {
            "display_name": "OpenAI",
            "model": "gpt-4o-mini",
            "timeout": 30.0,
            "max_retries": 3,
        },
        "deepseek": {
            "display_name": "DeepSeek",
            "model": "deepseek-chat",
            "timeout": 60.0,
            "max_retries": 3,
        },
        "zhipu": {
            "display_name": "智谱 AI",
            "model": "glm-4",
            "timeout": 30.0,
            "max_retries": 3,
        },
        "anthropic": {
            "display_name": "Anthropic Claude",
            "model": "claude-3-5-sonnet-20241022",
            "timeout": 60.0,
            "max_retries": 3,
        },
    }

    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> Optional[LLMProviderInterface]:
        """
        从字典创建 Provider 实例。

        Args:
            config: 配置字典，格式：
                {
                    "name": "openai",
                    "api_key": "sk-...",
                    "base_url": "https://api.openai.com/v1",
                    "model": "gpt-4",
                    "enabled": True
                }

        Returns:
            Provider 实例，失败返回 None
        """
        name = config.get("name")
        if not name:
            logger.error("Provider config must have 'name' field")
            return None

        api_key = config.get("api_key")
        if not api_key:
            logger.error(f"Provider {name} requires 'api_key'")
            return None

        # 获取模板配置
        template = cls.PROVIDER_TEMPLATES.get(name, {})

        credentials = ProviderCredentials(
            api_key=api_key,
            base_url=config.get("base_url") or template.get("base_url"),
            org_id=config.get("org_id"),
        )

        provider_config = ProviderConfig(
            name=name,
            display_name=template.get("display_name", name),
            credentials=credentials,
            model=config.get("model") or template.get("model", "gpt-4o-mini"),
            timeout=config.get("timeout") or template.get("timeout", 30.0),
            max_retries=config.get("max_retries") or template.get("max_retries", 3),
            enabled=config.get("enabled", True),
        )

        return registry.create(name, provider_config)

    @classmethod
    def from_settings(cls, settings) -> Dict[str, LLMProviderInterface]:
        """
        从应用设置创建 Provider 实例。

        Args:
            settings: 应用设置对象

        Returns:
            Provider 实例字典
        """
        providers = {}
        enabled_providers = settings.get_enabled_llm_providers()

        for config in enabled_providers:
            name = config.get("name")
            if name:
                provider = cls.from_dict(config)
                if provider:
                    providers[name] = provider

        return providers

    @classmethod
    def create(
        cls,
        name: str,
        api_key: str,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Optional[LLMProviderInterface]:
        """
        快速创建 Provider 实例。

        Args:
            name: Provider 名称
            api_key: API 密钥
            base_url: 基础 URL（可选）
            model: 模型名称（可选）

        Returns:
            Provider 实例
        """
        config = {
            "name": name,
            "api_key": api_key,
            "base_url": base_url,
            "model": model,
        }
        return cls.from_dict(config)

    @classmethod
    def list_available(cls) -> list:
        """列出所有可用的 Provider"""
        return registry.list_registered()


# =============================================================================
# 便捷函数
# =============================================================================


def create_openai_provider(
    api_key: str,
    base_url: Optional[str] = None,
    model: str = "gpt-4o-mini",
) -> OpenAIProvider:
    """创建 OpenAI Provider（便捷函数）"""
    credentials = ProviderCredentials(api_key=api_key, base_url=base_url)
    config = ProviderConfig(
        name="openai",
        display_name="OpenAI",
        credentials=credentials,
        model=model,
    )
    return OpenAIProvider(config)


def create_anthropic_provider(
    api_key: str,
    model: str = "claude-3-5-sonnet-20241022",
) -> AnthropicProvider:
    """创建 Anthropic Provider（便捷函数）"""
    credentials = ProviderCredentials(api_key=api_key)
    config = ProviderConfig(
        name="anthropic",
        display_name="Anthropic Claude",
        credentials=credentials,
        model=model,
    )
    return AnthropicProvider(config)


def create_deepseek_provider(
    api_key: str,
    base_url: str = "https://api.deepseek.com",
    model: str = "deepseek-chat",
) -> OpenAIProvider:
    """创建 DeepSeek Provider（便捷函数）"""
    credentials = ProviderCredentials(api_key=api_key, base_url=base_url)
    config = ProviderConfig(
        name="deepseek",
        display_name="DeepSeek",
        credentials=credentials,
        model=model,
    )
    return OpenAIProvider(config)
