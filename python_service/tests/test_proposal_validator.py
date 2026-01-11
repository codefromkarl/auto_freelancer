import pytest
from services.proposal_validator import ProposalValidator

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