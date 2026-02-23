import pytest
import sys
from pathlib import Path

# Add python_service to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from database.models import Project
from services import bid_service
from services.proposal_validator import ProposalValidator
from services.proposal_config_loader import ProposalConfigLoader


class TestProposalValidator:
    def test_validate_valid_proposal(self):
        # 满足 80-200 词，有问号，无禁用词
        text = "word " * 100 + " Can we discuss the technical details of the project? "
        result = ProposalValidator.validate(text)
        assert result.is_valid is True
        assert len(result.issues) == 0

    def test_validate_word_count_too_low(self):
        text = "Too short. " * 5 + " Any questions?"
        result = ProposalValidator.validate(text)
        assert result.is_valid is False
        assert any("Word count too low" in issue for issue in result.issues)

    def test_validate_word_count_too_high(self):
        text = "word " * 201 + " Any questions?"
        result = ProposalValidator.validate(text)
        assert result.is_valid is False
        assert any("Word count too high" in issue for issue in result.issues)

    def test_validate_no_question_mark(self):
        text = "word " * 100 + " I am ready to start right now."
        result = ProposalValidator.validate(text)
        assert result.is_valid is False
        assert any("No question marks found" in issue for issue in result.issues)

    def test_validate_prohibited_header(self):
        text = "# Project Proposal\n" + "word " * 100 + " Any questions?"
        result = ProposalValidator.validate(text)
        assert result.is_valid is False
        assert any("Prohibited header style" in issue for issue in result.issues)

    def test_validate_prohibited_phrase(self):
        bad_phrases = ["trust me", "dear sir", "kindly hire me"]
        for phrase in bad_phrases:
            text = "word " * 90 + f" {phrase} " + " Any questions?"
            result = ProposalValidator.validate(text)
            assert result.is_valid is False
            assert any("Prohibited phrase found" in issue for issue in result.issues)


class TestProposalConfigSchema:
    """Tests for P1: Configuration Schema Validation"""

    def test_validate_config_schema_valid(self, tmp_path):
        """Valid config should pass schema validation"""
        config_file = tmp_path / "valid_config.yaml"
        config_file.write_text("""
version: "2.0"
personas:
  frontend:
    name: Frontend Expert
    hints:
      - React, Vue, Angular
styles:
  narrative:
    description: Storytelling approach
structures:
  three_step:
    description: Problem-Solution-Action
validation_rules:
  min_words: 80
  max_words: 200
""")
        loader = ProposalConfigLoader()
        # Test that the schema validation method exists and works
        assert hasattr(loader, "validate_schema")
        result = loader.validate_schema({"version": "2.0"})
        assert result is True

    def test_validate_config_schema_missing_version(self, tmp_path):
        """Config without version should fail schema validation"""
        config = {"personas": {}}
        loader = ProposalConfigLoader()
        result = loader.validate_schema(config)
        assert result is False

    def test_validate_config_schema_invalid_version(self):
        """Config with invalid version should fail schema validation"""
        config = {"version": "1.0"}
        loader = ProposalConfigLoader()
        result = loader.validate_schema(config)
        assert result is False

    def test_validate_config_schema_invalid_structure(self):
        """Config with unknown keys should pass but log warning"""
        config = {"version": "2.0", "unknown_key": "value"}
        loader = ProposalConfigLoader()
        result = loader.validate_schema(config)
        # Unknown keys are allowed but warned about
        assert result is True


class TestProposalTechAccuracy:
    """Tests for P2: Technical Accuracy Validation"""

    def test_validate_tech_stack_match(self):
        """Proposal mentioning project skills should pass tech accuracy check"""
        project = {
            "title": "Build a React and Python API",
            "description": "Need a full-stack developer with React frontend and FastAPI backend experience",
            "skills": ["React", "Python", "FastAPI", "PostgreSQL"],
        }
        proposal = "I can build this React application with a Python FastAPI backend using PostgreSQL. Can you clarify the database requirements?"
        result = ProposalValidator.validate_tech_accuracy(proposal, project)
        assert result.is_valid is True

    def test_validate_tech_stack_mismatch(self):
        """Proposal not mentioning project skills should fail tech accuracy check"""
        project = {
            "title": "Build a React and Python API",
            "description": "Need a full-stack developer with React frontend and FastAPI backend experience",
            "skills": ["React", "Python", "FastAPI", "PostgreSQL"],
        }
        proposal = "I am a great developer with 10 years of experience. I can do this project well. Let me know if you are interested."
        result = ProposalValidator.validate_tech_accuracy(proposal, project)
        assert result.is_valid is False

    def test_validate_tech_stack_partial_match(self):
        """Proposal with partial skill match should have warnings but pass"""
        project = {
            "title": "Build a React and Python API",
            "description": "Need a full-stack developer with React frontend and FastAPI backend",
            "skills": ["React", "Python", "FastAPI"],
        }
        # Proposal only mentions Python, not React or FastAPI
        proposal = "I have extensive Python experience and can build the backend API. What about the frontend requirements?"
        result = ProposalValidator.validate_tech_accuracy(proposal, project)
        # Should have warnings about missing skills
        assert len(result.warnings) > 0


class TestProposalDuplicateDetection:
    """Tests for P3: Duplicate Content Detection"""

    def test_detect_similar_proposals(self):
        """Should detect high similarity between proposals"""
        proposals = [
            "I am a Python developer with FastAPI experience. Can we discuss the project details?",
            "I am a Python developer with FastAPI experience. Can we discuss the project details?",
        ]
        similarity = ProposalValidator.detect_duplicates(proposals)
        assert similarity >= 0.9  # Very high similarity

    def test_detect_different_proposals(self):
        """Should not flag different proposals as duplicates"""
        proposals = [
            "I have extensive React experience and can build your frontend application.",
            "I am a Python expert with Django and FastAPI background for backend development.",
        ]
        similarity = ProposalValidator.detect_duplicates(proposals)
        assert similarity < 0.5  # Low similarity

    def test_detect_similar_with_typos(self):
        """Should detect similarity even with minor differences"""
        proposals = [
            "I am a Python developer with FastAPI experience.",
            "I am a Python deveeloper with FastAPI experince.",  # Typos
        ]
        similarity = ProposalValidator.detect_duplicates(proposals)
        assert similarity >= 0.7  # Still high similarity despite typos


class TestBidContentRiskBudget:
    @staticmethod
    def _build_description(*, budget_line: str, quote_line: str) -> str:
        return (
            "针对 Soccer Development Foundation 的需求，我会先完成技术方案梳理，"
            "再按交付计划推进实现与验收，确保范围和节奏清晰。"
            f"{budget_line}"
            f"{quote_line}"
            "我会先提交里程碑并保持每日报告，确保沟通和交付都稳定。"
        )

    def test_allows_quote_within_budget_range(self):
        project = Project(
            freelancer_id=40136969,
            title="VP Fundraising for Soccer Development Foundation",
            description="Need fundraising automation and process support for soccer foundation.",
            budget_minimum=10,
            budget_maximum=30,
            currency_code="CAD",
            status="open",
            owner_id=1001,
        )

        description = self._build_description(
            budget_line="预算范围是 10-30 CAD，",
            quote_line="报价 30 CAD。",
        )

        safe, reason = bid_service.check_content_risk(description, project)
        assert safe is True, reason

    def test_blocks_quote_far_below_budget_range(self):
        project = Project(
            freelancer_id=40135964,
            title="3D Character Animation for Entertainment",
            description="Need 3D character animation delivery with clear milestones.",
            budget_minimum=12500,
            budget_maximum=37500,
            currency_code="INR",
            status="open",
            owner_id=1002,
        )

        description = self._build_description(
            budget_line="预算范围是 12500-37500 INR，",
            quote_line="报价 350 INR。",
        )

        safe, reason = bid_service.check_content_risk(description, project)
        assert safe is False
        # Validator rejects due to anchor coverage or other quality issues
        assert reason != "通过"
