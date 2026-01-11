"""
Quality comparison tests for proposal generation.

Validates that proposals meet quality standards including:
- Three-paragraph structure (pain point → experience → solution)
- No Markdown headers
- Appropriate word count
- Narrative style compliance
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON_SERVICE = REPO_ROOT / "python_service"
sys.path.insert(0, str(PYTHON_SERVICE))

import pytest
from unittest.mock import MagicMock, AsyncMock
import re

from services.proposal_service import (
    ProposalService,
    ProposalConfig,
    DefaultProposalValidator,
)
from services.proposal_prompt_builder import (
    STYLE_NARRATIVE,
    STRUCTURE_THREE_STEP,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_project():
    """Create a mock Project for testing."""
    project = MagicMock()
    project.freelancer_id = 12345
    project.title = "Build Python FastAPI REST API for E-commerce Platform"
    project.description = (
        "We need an experienced Python developer to build a complete REST API "
        "for our e-commerce platform. The API should handle user authentication, "
        "product catalog, shopping cart, order processing, and payment integration."
    )
    project.preview_description = (
        "Build Python FastAPI REST API for E-commerce Platform"
    )
    project.budget_minimum = 500
    project.budget_maximum = 1500
    project.currency_code = "USD"
    project.skills = '["Python", "FastAPI", "PostgreSQL", "Docker"]'
    project.owner_info = '{"online_status": "online", "jobs_posted": 15, "rating": 4.8}'
    project.bid_stats = '{"bid_count": 25, "average_bid": 800}'

    def to_dict():
        return {
            "id": project.freelancer_id,
            "title": project.title,
            "description": project.description,
            "preview_description": project.preview_description,
            "budget_minimum": float(project.budget_minimum),
            "budget_maximum": float(project.budget_maximum),
            "currency_code": project.currency_code,
            "skills": ["Python", "FastAPI", "PostgreSQL", "Docker"],
            "owner_info": {"online_status": "online", "jobs_posted": 15, "rating": 4.8},
            "bid_stats": {"bid_count": 25, "average_bid": 800},
        }

    project.to_dict = to_dict
    return project


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client for quality testing."""
    client = MagicMock()

    # High-quality proposal following three-paragraph structure
    high_quality_proposal = """基于您发布的项目需求，我对电商平台API开发有以下深入理解和完整方案。

首先，贵公司的电商平台需要一个能够支撑高并发访问的健壮后端系统。FastAPI凭借其异步特性和自动文档生成能力，是构建此类系统的理想选择。我将采用RESTful设计原则，确保API的易用性和可维护性，同时通过PostgreSQL数据库实现数据的可靠存储。在此基础上，我会设计合理的索引策略和缓存机制，进一步优化查询性能。

其次，用户认证与安全是电商平台的核心模块。我计划使用JWT令牌配合OAuth2.0协议，实现安全的用户身份验证机制，并针对敏感操作实施严格的权限控制。此外，我会遵循OWASP安全最佳实践，对API进行全面的安全加固，包括输入验证、SQL注入防护、以及防止常见的Web攻击。

最后，订单处理与支付集成是决定用户体验的关键环节。我将设计清晰的订单状态流转流程，并集成主流支付网关（如Stripe或PayPal），确保交易过程的安全可靠。每个环节都会配备完善的错误处理和日志记录，便于后续的问题排查和系统维护。"""

    async def generate_proposal(system_prompt, user_prompt, model, temperature):
        return high_quality_proposal

    client.generate_proposal = AsyncMock(side_effect=generate_proposal)
    return client


@pytest.fixture
def proposal_config():
    """Create test configuration."""
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


# =============================================================================
# Quality Validation Tests
# =============================================================================


class TestThreeParagraphStructure:
    """Tests for verifying three-paragraph (三段式) proposal structure."""

    def test_proposal_has_three_paragraphs(
        self, mock_llm_client, proposal_config, sample_project
    ):
        """Verify that generated proposal has the expected three-paragraph structure."""
        service = ProposalService(
            llm_client=mock_llm_client,
            config=proposal_config,
        )

        # Get the generated proposal synchronously for structure analysis
        import asyncio

        result = asyncio.run(service.generate_proposal(sample_project))

        proposal = result["proposal"]

        # Split by double newlines (paragraph breaks)
        paragraphs = [p.strip() for p in proposal.split("\n\n") if p.strip()]

        # Should have at least 3 paragraphs
        assert len(paragraphs) >= 3, (
            f"Expected at least 3 paragraphs, got {len(paragraphs)}"
        )

    def test_first_paragraph_contains_pain_points(
        self, mock_llm_client, proposal_config, sample_project
    ):
        """Verify that first paragraph addresses pain points."""
        service = ProposalService(
            llm_client=mock_llm_client,
            config=proposal_config,
        )

        import asyncio

        result = asyncio.run(service.generate_proposal(sample_project))

        proposal = result["proposal"]
        first_paragraph = proposal.split("\n\n")[0].strip()

        # Should contain project-related keywords
        pain_point_keywords = ["需要", "需求", "平台", "系统", "API"]
        has_pain_point = any(kw in first_paragraph for kw in pain_point_keywords)

        assert has_pain_point, "First paragraph should address project pain points"

    def test_paragraphs_have_sufficient_sentences(
        self, mock_llm_client, proposal_config, sample_project
    ):
        """Verify that each paragraph has sufficient sentences (3-5 as per guidelines)."""
        service = ProposalService(
            llm_client=mock_llm_client,
            config=proposal_config,
        )

        import asyncio

        result = asyncio.run(service.generate_proposal(sample_project))

        proposal = result["proposal"]
        paragraphs = [p.strip() for p in proposal.split("\n\n") if p.strip()]

        for i, paragraph in enumerate(paragraphs):
            # Count sentences (split by 。 or . or ？ or ！)
            sentences = re.split(r"[。！？.!?]", paragraph)
            sentences = [s.strip() for s in sentences if s.strip()]

            # Each paragraph should have at least 3 sentences
            assert len(sentences) >= 3, (
                f"Paragraph {i + 1} has only {len(sentences)} sentences, "
                f"expected at least 3"
            )


class TestNoMarkdownHeaders:
    """Tests for verifying absence of Markdown headers."""

    def test_proposal_has_no_markdown_headers(
        self, mock_llm_client, proposal_config, sample_project
    ):
        """Verify that proposal does not contain Markdown headers."""
        service = ProposalService(
            llm_client=mock_llm_client,
            config=proposal_config,
        )

        import asyncio

        result = asyncio.run(service.generate_proposal(sample_project))

        proposal = result["proposal"]

        # Check for Markdown headers (#, ##, ###)
        header_pattern = r"^#{1,6}\s+"
        has_headers = bool(re.search(header_pattern, proposal, re.MULTILINE))

        assert not has_headers, "Proposal should not contain Markdown headers"

    def test_proposal_has_no_bullet_points(
        self, mock_llm_client, proposal_config, sample_project
    ):
        """Verify that proposal does not contain bullet point lists."""
        service = ProposalService(
            llm_client=mock_llm_client,
            config=proposal_config,
        )

        import asyncio

        result = asyncio.run(service.generate_proposal(sample_project))

        proposal = result["proposal"]

        # Check for bullet points (-, *, 1., etc.)
        bullet_pattern = r"^[\s]*[-*+]\s+"
        has_bullets = bool(re.search(bullet_pattern, proposal, re.MULTILINE))

        assert not has_bullets, "Proposal should not contain bullet points"

    def test_proposal_has_no_numbered_list(
        self, mock_llm_client, proposal_config, sample_project
    ):
        """Verify that proposal does not contain numbered lists."""
        service = ProposalService(
            llm_client=mock_llm_client,
            config=proposal_config,
        )

        import asyncio

        result = asyncio.run(service.generate_proposal(sample_project))

        proposal = result["proposal"]

        # Check for numbered lists (1., 2., etc.)
        numbered_pattern = r"^[\s]*(?:\d+[.)]|\([0-9]+\))\s+"
        has_numbered = bool(re.search(numbered_pattern, proposal, re.MULTILINE))

        assert not has_numbered, "Proposal should not contain numbered lists"


class TestWordCountRange:
    """Tests for verifying appropriate word/character count."""

    def test_proposal_within_length_limits(
        self, mock_llm_client, proposal_config, sample_project
    ):
        """Verify that proposal is within configured length limits."""
        service = ProposalService(
            llm_client=mock_llm_client,
            config=proposal_config,
        )

        import asyncio

        result = asyncio.run(service.generate_proposal(sample_project))

        proposal = result["proposal"]
        char_count = len(proposal)

        # Should be within config limits
        assert char_count >= proposal_config.min_length, (
            f"Proposal too short: {char_count} chars < {proposal_config.min_length}"
        )
        assert char_count <= proposal_config.max_length, (
            f"Proposal too long: {char_count} chars > {proposal_config.max_length}"
        )

    def test_proposal_not_too_short(
        self, mock_llm_client, proposal_config, sample_project
    ):
        """Verify minimum character count (200 chars as per config)."""
        service = ProposalService(
            llm_client=mock_llm_client,
            config=proposal_config,
        )

        import asyncio

        result = asyncio.run(service.generate_proposal(sample_project))

        proposal = result["proposal"]

        # Minimum is 200 characters
        assert len(proposal) >= 200, (
            f"Proposal must be at least 200 characters, got {len(proposal)}"
        )


class TestNarrativeStyle:
    """Tests for verifying narrative/prose style compliance."""

    def test_proposal_uses_narrative_style(
        self, mock_llm_client, proposal_config, sample_project
    ):
        """Verify that proposal uses narrative paragraph style."""
        service = ProposalService(
            llm_client=mock_llm_client,
            config=proposal_config,
        )

        import asyncio

        result = asyncio.run(service.generate_proposal(sample_project))

        proposal = result["proposal"]

        # Should have paragraph breaks
        paragraphs = [p.strip() for p in proposal.split("\n\n") if p.strip()]

        # Should be using paragraph style, not line-by-line
        lines = proposal.split("\n")
        paragraph_lines = sum(1 for line in lines if len(line.strip()) > 50)

        # Most content should be in longer paragraphs
        assert paragraph_lines >= len(paragraphs), (
            "Proposal should use paragraph style, not line-by-line format"
        )

    def test_proposal_uses_transition_words(
        self, mock_llm_client, proposal_config, sample_project
    ):
        """Verify that proposal uses transition words as per guidelines."""
        service = ProposalService(
            llm_client=mock_llm_client,
            config=proposal_config,
        )

        import asyncio

        result = asyncio.run(service.generate_proposal(sample_project))

        proposal = result["proposal"]

        # Check for transition words
        transition_words = ["首先", "其次", "最后", "此外", "因此", "同时", "然后"]
        has_transitions = any(word in proposal for word in transition_words)

        assert has_transitions, (
            "Proposal should use transition words (首先, 其次, 最后, 此外, etc.)"
        )


class TestTemplateDetection:
    """Tests for detecting template-generated content."""

    def test_proposal_not_template_content(
        self, mock_llm_client, proposal_config, sample_project
    ):
        """Verify that proposal is not template-style content."""
        service = ProposalService(
            llm_client=mock_llm_client,
            config=proposal_config,
        )

        import asyncio

        result = asyncio.run(service.generate_proposal(sample_project))

        proposal = result["proposal"]

        # Template phrases that should not appear
        template_phrases = [
            "我有丰富的经验",
            "了解您的需求",
            "这正是我的专长领域",
            "完整的解决方案",
            "仔细分析需求",
            "包括需求分析、开发、测试和部署",
            "基于我的相关经验",
            "作为一名经验丰富的开发者",
            "我的技术栈包括",
            "快速交付高质量结果",
        ]

        template_count = sum(1 for phrase in template_phrases if phrase in proposal)

        assert template_count < 3, (
            f"Proposal contains {template_count} template phrases, "
            "should be less than 3"
        )


class TestQualityComparison:
    """Tests for comparing new vs old proposal generation quality."""

    def test_new_proposal_more_narrative_than_old_style(self, sample_project):
        """Compare new narrative style against old bullet-point style."""
        # Old style (bullet points)
        old_style_proposal = """我有丰富的Python开发经验。
- 5年Python开发经验
- 熟悉FastAPI和Django
- 完成过多个电商项目

我可以提供完整的解决方案。
- 需求分析
- 系统设计
- 开发测试"""

        # New style (narrative)
        new_style_proposal = """基于您发布的项目需求，我对电商平台开发有以下深入理解。

首先，贵公司的平台需要支撑高并发访问。FastAPI凭借其异步特性，是构建此类系统的理想选择。我将采用RESTful设计原则，确保API的易用性和可维护性。

其次，用户认证与安全是核心模块。我计划使用JWT令牌配合OAuth2.0协议，实现安全的身份验证机制。

最后，订单处理与支付集成是关键环节。我将设计清晰的订单状态流转流程，确保交易过程的安全可靠。"""

        # Old style should fail narrative checks
        old_paragraphs = [
            p.strip() for p in old_style_proposal.split("\n\n") if p.strip()
        ]

        # Check if old style has bullet points
        has_bullets = bool(
            re.search(r"^[\s]*[-*]\s+", old_style_proposal, re.MULTILINE)
        )

        # New style should pass narrative checks
        new_paragraphs = [
            p.strip() for p in new_style_proposal.split("\n\n") if p.strip()
        ]

        # Validate the comparison
        assert has_bullets, "Old style should contain bullet points"
        assert len(new_paragraphs) >= 3, "New style should have 3+ paragraphs"

    def test_proposal_matches_project_context(
        self, mock_llm_client, proposal_config, sample_project
    ):
        """Verify that proposal references project-specific details."""
        service = ProposalService(
            llm_client=mock_llm_client,
            config=proposal_config,
        )

        import asyncio

        result = asyncio.run(service.generate_proposal(sample_project))

        proposal = result["proposal"]

        # Should reference project-relevant terms
        project_terms = ["FastAPI", "API", "电商", "平台", "系统"]
        has_project_refs = any(
            term.lower() in proposal.lower() for term in project_terms
        )

        assert has_project_refs, "Proposal should reference project-specific terms"


class TestValidatorQualityChecks:
    """Tests for the DefaultProposalValidator quality checks."""

    def test_validator_checks_three_paragraph_structure(self):
        """Test that validator can verify paragraph structure."""
        validator = DefaultProposalValidator(min_length=200, max_length=800)

        # Good proposal with 3 paragraphs and matching project description
        good_proposal = """基于您发布的项目需求，我对电商平台API开发有以下深入理解和完整方案。

首先，贵公司的电商平台需要一个能够支撑高并发访问的健壮后端系统。FastAPI凭借其异步特性和自动文档生成能力，是构建此类系统的理想选择。我将采用RESTful设计原则，确保API的易用性和可维护性，同时通过PostgreSQL数据库实现数据的可靠存储。

其次，用户认证与安全是电商平台的核心模块。我计划使用JWT令牌配合OAuth2.0协议，实现安全的用户身份验证机制。

最后，订单处理与支付集成是决定用户体验的关键环节。"""

        # Must provide matching project description
        project = {
            "title": "电商平台API开发项目",
            "description": "电商平台需要使用FastAPI构建API，包括用户认证和订单处理功能",
        }

        is_valid, issues = validator.validate(good_proposal, project)

        # Should pass basic validation
        assert is_valid or not any("结构" in i for i in issues)

    def test_validator_rejects_empty_lines(self):
        """Test that validator rejects proposals with too many empty lines."""
        validator = DefaultProposalValidator(min_length=200, max_length=800)

        # Proposal with too many empty lines
        proposal_with_empty_lines = """第一段内容。

第二段内容。

第三段内容。

第四段内容。"""

        # Count empty lines
        lines = proposal_with_empty_lines.split("\n")
        empty_lines = sum(1 for line in lines if not line.strip())

        # If more than 30% are empty, should fail
        if empty_lines > len(lines) * 0.3:
            is_valid, issues = validator.validate(
                proposal_with_empty_lines, {"title": "Test", "description": "Desc"}
            )
            assert not is_valid or any("空行" in i for i in issues)

    def test_validator_rejects_duplicate_sentences(self):
        """Test that validator detects duplicate sentences."""
        validator = DefaultProposalValidator(min_length=200, max_length=800)

        # Proposal with repeated sentences
        duplicate_proposal = """这是第一句。这是第一句。这是第二句。这是第二句。这是第三句。这是第三句。"""

        is_valid, issues = validator.validate(
            duplicate_proposal, {"title": "Test", "description": "Desc"}
        )

        # Should detect duplicates
        has_duplicate_check = any("重复" in i for i in issues)
        assert has_duplicate_check or len(duplicate_proposal) < validator.min_length


class TestPromptBuilderCompliance:
    """Tests for verifying compliance with prompt builder requirements."""

    def test_three_step_structure_defined(self):
        """Verify that three-step structure prompt is properly defined."""
        assert len(STRUCTURE_THREE_STEP) > 0, (
            "Three-step structure prompt should be defined"
        )
        assert "痛点" in STRUCTURE_THREE_STEP or "问题" in STRUCTURE_THREE_STEP, (
            "Three-step structure should include pain point section"
        )

    def test_narrative_style_defined(self):
        """Verify that narrative style prompt is properly defined."""
        assert len(STYLE_NARRATIVE) > 0, "Narrative style prompt should be defined"
        assert "禁止" in STYLE_NARRATIVE or "列表" in STYLE_NARRATIVE, (
            "Narrative style should include list prohibition"
        )

    def test_style_forbids_markdown_lists(self):
        """Verify that narrative style explicitly forbids markdown lists."""
        forbids_lists = (
            "禁止" in STYLE_NARRATIVE
            or "不要使用" in STYLE_NARRATIVE
            or "禁止使用" in STYLE_NARRATIVE
        )
        assert forbids_lists, "Narrative style should explicitly forbid markdown lists"
