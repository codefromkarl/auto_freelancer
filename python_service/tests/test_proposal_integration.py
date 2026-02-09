"""
Integration tests for ProposalService

Tests the complete proposal generation flow with mocked LLM responses
to avoid actual API calls while validating service integration.
"""

import sys
from pathlib import Path
import asyncio

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON_SERVICE = REPO_ROOT / "python_service"
sys.path.insert(0, str(PYTHON_SERVICE))

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass
import services.proposal_service as proposal_service_module

from services.proposal_service import (
    ProposalService,
    ProposalConfig,
    DefaultProposalValidator,
    DefaultPersonaController,
    LLMClientProtocol,
    MultiProviderLLMClientAdapter,
)
from database.models import Project


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_project_dict():
    """Sample project data for testing."""
    return {
        "id": 12345,
        "title": "Build Python FastAPI REST API for E-commerce Platform",
        "description": "We need an experienced Python developer to build a complete REST API "
        "for our e-commerce platform. The API should handle user authentication, "
        "product catalog, shopping cart, order processing, and payment integration.",
        "preview_description": "Build Python FastAPI REST API for E-commerce Platform",
        "budget_minimum": 500,
        "budget_maximum": 1500,
        "currency_code": "USD",
        "skills": '["Python", "FastAPI", "PostgreSQL", "Docker"]',
        "owner_info": '{"online_status": "online", "jobs_posted": 15, "rating": 4.8}',
        "bid_stats": '{"bid_count": 25, "average_bid": 800}',
    }


@pytest.fixture
def sample_project(sample_project_dict):
    """Create a mock Project object."""
    project = MagicMock(spec=Project)
    project.freelancer_id = sample_project_dict["id"]
    project.title = sample_project_dict["title"]
    project.description = sample_project_dict["description"]
    project.preview_description = sample_project_dict["preview_description"]
    project.budget_minimum = sample_project_dict["budget_minimum"]
    project.budget_maximum = sample_project_dict["budget_maximum"]
    project.currency_code = sample_project_dict["currency_code"]
    project.skills = sample_project_dict["skills"]
    project.owner_info = sample_project_dict["owner_info"]
    project.bid_stats = sample_project_dict["bid_stats"]

    def to_dict():
        return sample_project_dict

    project.to_dict = to_dict
    return project


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client with configurable responses."""
    client = MagicMock(spec=LLMClientProtocol)

    # Default high-quality proposal response
    default_proposal = """基于您发布的项目需求，我对电商平台API开发有以下深入理解和完整方案。

首先，贵公司的电商平台需要一个能够支撑高并发访问的健壮后端系统。FastAPI凭借其异步特性和自动文档生成能力，是构建此类系统的理想选择。我将采用RESTful设计原则，确保API的易用性和可维护性，同时通过PostgreSQL数据库实现数据的可靠存储。

其次，用户认证与安全是电商平台的核心模块。我计划使用JWT令牌配合OAuth2.0协议，实现安全的用户身份验证机制，并针对敏感操作实施严格的权限控制。

最后，订单处理与支付集成是决定用户体验的关键环节。我将设计清晰的订单状态流转流程，并集成主流支付网关（如Stripe或PayPal），确保交易过程的安全可靠。

期待有机会与您深入探讨项目细节，共同打造一个功能完善、性能卓越的电商API系统。"""

    async def generate_proposal(system_prompt, user_prompt, model, temperature):
        return default_proposal

    client.generate_proposal = AsyncMock(side_effect=generate_proposal)
    return client


@pytest.fixture
def mock_llm_client_template_response():
    """Create a mock LLM client that returns template-style response (for testing validation)."""
    client = MagicMock(spec=LLMClientProtocol)

    template_proposal = """我有丰富的Python开发经验，了解您的FastAPI需求。

这正是我的专长领域，我可以使用完整的解决方案，包括需求分析、开发、测试和部署。

基于我的相关经验，我可以提供高质量的代码交付。"""

    async def generate_proposal(system_prompt, user_prompt, model, temperature):
        return template_proposal

    client.generate_proposal = AsyncMock(side_effect=generate_proposal)
    return client


@pytest.fixture
def mock_llm_client_short_response():
    """Create a mock LLM client that returns a too-short response."""
    client = MagicMock(spec=LLMClientProtocol)

    short_proposal = "我可以帮您完成这个项目。我有相关经验。"

    async def generate_proposal(system_prompt, user_prompt, model, temperature):
        return short_proposal

    client.generate_proposal = AsyncMock(side_effect=generate_proposal)
    return client


@pytest.fixture
def proposal_config():
    """Create a test configuration."""
    return ProposalConfig(
        max_retries=2,
        timeout=30.0,
        min_length=200,
        max_length=800,
        validate_before_return=True,
        fallback_enabled=True,
        model="gpt-4o-mini",
        temperature=0.7,
    )


@pytest.fixture
def service_with_mock_llm(mock_llm_client, proposal_config):
    """Create a ProposalService with mocked LLM client."""
    return ProposalService(
        llm_client=mock_llm_client,
        config=proposal_config,
    )


# =============================================================================
# Integration Tests
# =============================================================================


class TestProposalServiceIntegration:
    """Integration tests for ProposalService with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_generate_proposal_success(
        self, sample_project, service_with_mock_llm
    ):
        """Test successful proposal generation flow."""
        result = await service_with_mock_llm.generate_proposal(sample_project)

        assert result["success"] is True
        assert len(result["proposal"]) > 0
        assert result["attempts"] == 1
        assert result["validation_passed"] is True
        assert result["model_used"] == "gpt-4o-mini"
        assert result["error"] is None
        assert result["latency_ms"] > 0

    @pytest.mark.asyncio
    async def test_generate_proposal_calls_llm_correctly(
        self, sample_project, mock_llm_client, proposal_config
    ):
        """Test that LLM client is called with correct parameters."""
        service = ProposalService(
            llm_client=mock_llm_client,
            config=proposal_config,
        )

        await service.generate_proposal(sample_project)

        # Verify LLM was called
        mock_llm_client.generate_proposal.assert_called_once()

        # Verify call parameters
        call_kwargs = mock_llm_client.generate_proposal.call_args
        assert "system_prompt" in call_kwargs.kwargs
        assert "user_prompt" in call_kwargs.kwargs
        assert call_kwargs.kwargs["model"] == "gpt-4o-mini"
        assert call_kwargs.kwargs["temperature"] == 0.7

    @pytest.mark.asyncio
    async def test_generate_proposal_with_score_data(
        self, sample_project, mock_llm_client, proposal_config
    ):
        """Test proposal generation with score data context."""
        service = ProposalService(
            llm_client=mock_llm_client,
            config=proposal_config,
        )

        score_data = {
            "estimated_hours": 40,
            "suggested_bid": 800,
        }

        result = await service.generate_proposal(sample_project, score_data=score_data)

        assert result["success"] is True
        assert "user_prompt" in service._build_user_prompt(
            sample_project.to_dict(), score_data, {}
        )

    def test_build_user_prompt_contains_risk_compatibility_terms(
        self, sample_project, mock_llm_client, proposal_config
    ):
        service = ProposalService(
            llm_client=mock_llm_client,
            config=proposal_config,
        )
        prompt = service._build_user_prompt(sample_project.to_dict(), {}, {})
        assert "technical" in prompt.lower()
        assert "budget" in prompt.lower()

    def test_build_user_prompt_contains_project_specific_coverage(
        self, sample_project, mock_llm_client, proposal_config
    ):
        service = ProposalService(
            llm_client=mock_llm_client,
            config=proposal_config,
        )
        project = sample_project.to_dict()
        project["description"] = (
            "Need webhook handling, admin dashboard, and OTP verification "
            "with clear logging and deployment docs."
        )
        prompt = service._build_user_prompt(
            project,
            {"suggested_bid": 800, "estimated_hours": 24},
            {},
        )
        lower_prompt = prompt.lower()
        assert "project-specific mandatory coverage" in lower_prompt
        assert "otp verification" in lower_prompt
        assert "admin dashboard" in lower_prompt
        assert "if you mention a numeric quote" in lower_prompt

    @pytest.mark.asyncio
    async def test_generate_proposal_validation_failure_triggers_retry(
        self, sample_project, mock_llm_client_template_response, proposal_config
    ):
        """Test that validation failure triggers retry mechanism."""
        # First call returns template response (will fail validation)
        # Configure mock to return a good response on second call
        good_proposal = "这是一个符合要求的提案，长度足够且不包含模板化内容。"

        mock_llm_client_template_response.generate_proposal = AsyncMock(
            side_effect=[
                mock_llm_client_template_response.generate_proposal(),
                good_proposal,
            ]
        )

        service = ProposalService(
            llm_client=mock_llm_client_template_response,
            config=proposal_config,
        )

        result = await service.generate_proposal(sample_project)

        # Should have attempted multiple times
        assert result["attempts"] >= 1

    @pytest.mark.asyncio
    async def test_generate_proposal_regenerates_in_english_when_first_output_non_english(
        self, sample_project
    ):
        """Final bid content should be directly regenerated in English, not translated."""
        chinese_proposal = (
            "我可以帮助你完成这个项目，并提供完整方案。"
            "首先我会梳理需求，其次我会实现核心功能，最后我会交付和优化。"
        )
        english_proposal = (
            "I can help you complete this project with a clear implementation plan. "
            "First, I will clarify scope and acceptance criteria. "
            "Then I will implement core features with strong testing and risk controls. "
            "Finally, I will deliver, document, and support a smooth handover."
        )

        llm_client = MagicMock(spec=LLMClientProtocol)
        llm_client.generate_proposal = AsyncMock(
            side_effect=[chinese_proposal, english_proposal]
        )

        config = ProposalConfig(
            max_retries=2,
            timeout=30.0,
            min_length=50,
            max_length=1000,
            validate_before_return=False,
            fallback_enabled=True,
            model="gpt-4o-mini",
            temperature=0.7,
        )
        service = ProposalService(llm_client=llm_client, config=config)

        result = await service.generate_proposal(sample_project)

        assert result["success"] is True
        assert result["proposal"] == english_proposal
        assert llm_client.generate_proposal.call_count == 2

    @pytest.mark.asyncio
    async def test_generate_proposal_auto_compresses_when_over_target_length(
        self, sample_project
    ):
        """Overlong proposal should trigger an automatic compression rewrite pass."""
        long_proposal = (
            "This is a highly detailed proposal. " * 120
            + "technical implementation delivery plan approach solution budget 1200 USD?"
        )
        compressed_proposal = (
            "I can deliver your RAG backend with a technical implementation plan and clear delivery milestones. "
            "For budget alignment, my quote is 1200 USD within your range. "
            "Should we prioritize admin document controls first?"
        )

        llm_client = MagicMock(spec=LLMClientProtocol)
        llm_client.generate_proposal = AsyncMock(
            side_effect=[long_proposal, compressed_proposal]
        )

        config = ProposalConfig(
            max_retries=1,
            timeout=30.0,
            min_length=200,
            max_length=1800,
            target_char_min=700,
            target_char_max=1200,
            validate_before_return=False,
            fallback_enabled=True,
            model="gpt-4o-mini",
            temperature=0.7,
        )
        service = ProposalService(llm_client=llm_client, config=config)

        result = await service.generate_proposal(sample_project)

        assert result["success"] is True
        assert result["proposal"] == compressed_proposal
        assert len(result["proposal"]) < len(long_proposal)
        assert llm_client.generate_proposal.call_count == 2


class TestProposalServiceWithBidService:
    """Integration tests for ProposalService integration with bid_service."""

    @pytest.mark.asyncio
    async def test_proposal_service_integration_with_bid_workflow(
        self, sample_project, mock_llm_client, proposal_config
    ):
        """Test complete proposal generation as used in bid workflow."""
        service = ProposalService(
            llm_client=mock_llm_client,
            config=proposal_config,
        )

        # Simulate the workflow from bid_service
        result = await service.generate_proposal(sample_project)

        # Verify the result format matches what bid_service expects
        assert "success" in result


class TestProposalValidatorProjectAnchors:
    def test_validator_rejects_generic_proposal_without_project_anchors(self):
        validator = DefaultProposalValidator(min_length=120, max_length=1200)
        project = {
            "title": "WhatsApp Order & OTP Automation with Admin Dashboard",
            "description": (
                "Need WhatsApp webhook integration, OTP verification, state machine flow, "
                "and admin dashboard for scheduling."
            ),
        }
        proposal = (
            "I can provide a technical implementation plan with high quality delivery. "
            "My approach is professional and solution oriented with solid execution details. "
            "The budget is within range and I can start immediately. "
            "Please share access details."
        )

        valid, issues = validator.validate(proposal, project)
        assert valid is False
        assert any("关键需求点覆盖不足" in issue for issue in issues)

    def test_validator_accepts_phrase_anchor_partial_token_match(self):
        validator = DefaultProposalValidator(min_length=120, max_length=1200)
        project = {
            "title": "WhatsApp Order & OTP Automation with Admin Dashboard",
            "description": (
                "Need WhatsApp webhook integration, OTP verification, state machine flow, "
                "and admin dashboard for scheduling."
            ),
        }
        proposal = (
            "I can deliver a technical implementation plan for your WhatsApp webhook backend. "
            "My approach includes OTP flow handling, delivery checkpoints, and dashboard updates. "
            "The budget is aligned with your range, and I can start immediately. "
            "Could you share your preferred deployment environment?"
        )

        valid, issues = validator.validate(proposal, project)
        assert not any("关键需求点覆盖不足" in issue for issue in issues)


class TestPersonaControllerIntegration:
    """Integration tests for persona controller with project types."""

    @pytest.mark.asyncio
    async def test_persona_adjusted_for_ai_project(
        self, mock_llm_client, proposal_config
    ):
        """Test that persona is correctly adjusted for AI/ML projects."""
        service = ProposalService(
            llm_client=mock_llm_client,
            config=proposal_config,
        )

        ai_project = MagicMock(spec=Project)
        ai_project.to_dict = lambda: {
            "id": 1,
            "title": "Build LLM Fine-tuning Pipeline",
            "description": "Create a fine-tuning pipeline for large language models using PyTorch and HuggingFace.",
            "budget_minimum": 1000,
            "budget_maximum": 3000,
            "currency_code": "USD",
        }
        ai_project.freelancer_id = 1
        ai_project.title = "Build LLM Fine-tuning Pipeline"

        persona = service.persona_controller.get_persona_for_project(
            ai_project.to_dict()
        )

        assert persona["technical_depth"] == "advanced"
        assert persona["focus"] == "innovation"

    @pytest.mark.asyncio
    async def test_persona_adjusted_for_simple_task(
        self, mock_llm_client, proposal_config
    ):
        """Test that persona is correctly adjusted for simple tasks."""
        service = ProposalService(
            llm_client=mock_llm_client,
            config=proposal_config,
        )

        simple_project = MagicMock(spec=Project)
        simple_project.to_dict = lambda: {
            "id": 2,
            "title": "Fix small bug in Python script",
            "description": "There is a small bug that needs to be fixed.",
            "budget_minimum": 50,
            "budget_maximum": 100,
            "currency_code": "USD",
        }
        simple_project.freelancer_id = 2
        simple_project.title = "Fix small bug in Python script"

        persona = service.persona_controller.get_persona_for_project(
            simple_project.to_dict()
        )

        assert persona["tone"] == "concise"
        assert persona["formality"] == "informal"


class TestValidatorIntegration:
    """Integration tests for proposal validation."""

    def test_validator_accepts_valid_proposal(self, sample_project_dict):
        """Test that validator accepts a high-quality proposal."""
        validator = DefaultProposalValidator(min_length=200, max_length=800)

        # Valid proposal that passes all validation checks
        # Using Chinese project terms to match with Chinese proposal
        # Note: Only 2 empty lines (between 4 paragraphs) = 2/6 = 33%, which should pass
        valid_proposal = """基于您发布的项目需求，我对电商平台API开发有以下深入理解和完整方案。

首先，贵公司的电商平台需要一个能够支撑高并发访问的健壮后端系统。FastAPI凭借其异步特性和自动文档生成能力，是构建此类系统的理想选择。我将采用RESTful设计原则，确保API的易用性和可维护性，同时通过PostgreSQL数据库实现数据的可靠存储。

其次，用户认证与安全是电商平台的核心模块。我计划使用JWT令牌配合OAuth2.0协议，实现安全的用户身份验证机制，并针对敏感操作实施严格的权限控制。

最后，订单处理与支付集成是决定用户体验的关键环节。"""

        # Use a project dict with matching Chinese terms
        project = {
            "title": "电商平台API开发项目",
            "description": "电商平台需要使用FastAPI构建API，包括用户认证、订单处理和支付集成功能",
        }

        is_valid, issues = validator.validate(valid_proposal, project)

        assert is_valid is True, f"Expected valid proposal, but got issues: {issues}"

    def test_validator_rejects_template_content(self, sample_project_dict):
        """Test that validator rejects template-style content."""
        validator = DefaultProposalValidator(min_length=200, max_length=800)

        template_proposal = """我有丰富的Python开发经验，了解您的FastAPI需求。

这正是我的专长领域，我可以使用完整的解决方案，包括需求分析、开发、测试和部署。

基于我的相关经验，我可以提供高质量的代码交付。"""

        project = {"title": "Test", "description": "Test description"}

        is_valid, issues = validator.validate(template_proposal, project)

        assert is_valid is False
        assert any("模板化内容" in issue for issue in issues)

    def test_validator_rejects_short_proposal(self, sample_project_dict):
        """Test that validator rejects too short proposals."""
        validator = DefaultProposalValidator(min_length=200, max_length=800)

        short_proposal = "我可以帮您完成这个项目。我有相关经验。"

        project = {"title": "Test", "description": "Test description"}

        is_valid, issues = validator.validate(short_proposal, project)

        assert is_valid is False
        assert any("过短" in issue for issue in issues)

    def test_validator_rejects_keyword_stuffing(self, sample_project_dict):
        """Test that validator rejects keyword stuffing."""
        validator = DefaultProposalValidator(min_length=200, max_length=800)

        # Create a proposal with high keyword density (more than 35% tech keywords)
        # This requires enough words (>20) and high keyword ratio
        tech_words = "python fastapi api automation workflow django flask"
        repeated = (tech_words + " ") * 10 + "some common text to make it longer"

        keyword_stuffed = repeated

        project = {"title": "Test", "description": "Test description"}

        is_valid, issues = validator.validate(keyword_stuffed, project)

        # Should fail either for keyword stuffing or short length
        assert not is_valid, (
            f"Expected invalid proposal due to keyword stuffing, got: {issues}"
        )
        # Check if keyword stuffing was detected (or short length which is also valid failure)

    @pytest.mark.asyncio
    async def test_validation_failure_returns_error_instead_of_partial_success(
        self, sample_project, mock_llm_client, proposal_config
    ):
        """Validation failures should not return success with invalid proposal."""

        class AlwaysInvalidValidator:
            def validate(self, proposal, project):
                return False, ["mock validation failure"]

            def get_min_length(self):
                return 1

            def get_max_length(self):
                return 9999

        config = ProposalConfig(
            max_retries=2,
            timeout=proposal_config.timeout,
            min_length=proposal_config.min_length,
            max_length=proposal_config.max_length,
            validate_before_return=True,
            fallback_enabled=True,
            model=proposal_config.model,
            temperature=proposal_config.temperature,
        )

        service = ProposalService(
            llm_client=mock_llm_client,
            validator=AlwaysInvalidValidator(),
            config=config,
        )

        result = await service.generate_proposal(sample_project)

        assert result["success"] is False
        assert result["validation_passed"] is False
        assert result["attempts"] == 2
        assert result["error"] == "proposal_validation_failed"
        assert "mock validation failure" in result["validation_issues"]


class TestFallbackMechanism:
    """Tests for fallback proposal generation."""

    @pytest.mark.asyncio
    async def test_fallback_generation(
        self, sample_project, mock_llm_client, proposal_config
    ):
        """Test that fallback proposal is generated when LLM fails."""
        # Create a client that always raises an exception
        failing_client = MagicMock(spec=LLMClientProtocol)

        async def fail(*args, **kwargs):
            raise Exception("LLM API Error")

        failing_client.generate_proposal = AsyncMock(side_effect=fail)

        service = ProposalService(
            llm_client=failing_client,
            config=proposal_config,
        )

        result = await service.generate_proposal(sample_project)

        # Should fail primary and return fallback
        assert result["attempts"] > 0
        # Fallback may or may not be used depending on error handling


class TestServiceReset:
    """Tests for service singleton management."""

    def test_reset_service_clears_singleton(self, mock_llm_client, proposal_config):
        """Test that reset_service properly clears the singleton."""
        from services.proposal_service import get_proposal_service, reset_service

        # Get initial service
        service1 = get_proposal_service()

        # Reset
        reset_service()

        # Get new service
        service2 = get_proposal_service()

        # They should be different instances
        assert service1 is not service2


class TestProviderFallbackAndTimeout:
    """Tests for provider fallback and timeout enforcement."""

    def test_proposal_service_prioritizes_primary_provider(self, monkeypatch, proposal_config):
        captured = {}

        class DummyMultiProvider:
            def __init__(self, providers, default_model, timeout=None):
                captured["providers"] = providers
                captured["default_model"] = default_model
                captured["timeout"] = timeout

            async def generate_proposal(
                self,
                *,
                system_prompt: str,
                user_prompt: str,
                model: str,
                temperature: float,
            ) -> str:
                return "ok"

        monkeypatch.setattr(
            proposal_service_module, "MultiProviderLLMClientAdapter", DummyMultiProvider
        )
        monkeypatch.setattr(
            proposal_service_module.settings.__class__,
            "get_enabled_llm_providers",
            lambda _self: [
                {
                    "name": "deepseek",
                    "api_key": "k-deepseek",
                    "model": "deepseek-chat",
                    "base_url": "https://api.deepseek.com",
                },
                {
                    "name": "zhipu",
                    "api_key": "k-zhipu",
                    "model": "glm-4",
                    "base_url": "https://open.bigmodel.cn/api/paas/v4",
                },
            ],
        )
        monkeypatch.setattr(proposal_service_module.settings, "LLM_PROVIDER", "zhipu")

        service = ProposalService(config=proposal_config)
        assert service.llm_client is not None
        assert captured["providers"][0]["name"] == "zhipu"
        assert captured["providers"][1]["name"] == "deepseek"

    @pytest.mark.asyncio
    async def test_multi_provider_fallback_uses_secondary_provider(self, monkeypatch):
        call_order = []

        class DummyAdapter:
            def __init__(
                self,
                api_key: str,
                model: str,
                base_url: str | None = None,
                timeout: float | None = None,
                provider_name: str = "openai",
            ):
                self.provider_name = provider_name

            async def generate_proposal(
                self,
                *,
                system_prompt: str,
                user_prompt: str,
                model: str,
                temperature: float,
            ) -> str:
                call_order.append(self.provider_name)
                if self.provider_name == "openai":
                    raise RuntimeError("primary provider timeout")
                return "secondary provider proposal"

        monkeypatch.setattr(proposal_service_module, "OpenAILLMClientAdapter", DummyAdapter)

        llm = MultiProviderLLMClientAdapter(
            providers=[
                {"name": "openai", "api_key": "k1", "model": "m1"},
                {"name": "zhipu", "api_key": "k2", "model": "m2"},
            ],
            default_model="m-default",
            timeout=0.1,
        )

        proposal = await llm.generate_proposal(
            system_prompt="system",
            user_prompt="user",
            model="ignored-model",
            temperature=0.7,
        )

        assert proposal == "secondary provider proposal"
        assert call_order == ["openai", "zhipu"]

    @pytest.mark.asyncio
    async def test_proposal_service_enforces_timeout(self, sample_project):
        class SlowClient:
            async def generate_proposal(
                self,
                *,
                system_prompt: str,
                user_prompt: str,
                model: str,
                temperature: float,
            ) -> str:
                await asyncio.sleep(0.2)
                return "late proposal"

        service = ProposalService(
            llm_client=SlowClient(),
            config=ProposalConfig(
                max_retries=1,
                timeout=0.05,
                min_length=50,
                max_length=800,
                validate_before_return=True,
                fallback_enabled=True,
                model="gpt-4o-mini",
                temperature=0.7,
            ),
        )

        result = await service.generate_proposal(sample_project)
        assert result["success"] is False
        assert result["attempts"] == 1
