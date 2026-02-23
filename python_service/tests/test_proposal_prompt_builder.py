import pytest
from services.proposal_prompt_builder import ProposalPromptBuilder, get_proposal_prompt_builder, reset_prompt_builder

@pytest.fixture
def builder():
    reset_prompt_builder()
    return get_proposal_prompt_builder()

@pytest.fixture
def sample_project():
    return {
        "title": "Build a Website",
        "description": "I need a website built with Python.",
        "budget_minimum": 500,
        "budget_maximum": 1000,
        "currency_code": "USD",
        "skills": ["Python", "Django", "HTML"],
        "bid_stats": {"bid_count": 10},
        "owner_info": {"username": "client123"}
    }

class TestProposalPromptBuilder:

    def test_singleton(self):
        b1 = get_proposal_prompt_builder()
        b2 = get_proposal_prompt_builder()
        assert b1 is b2

    def test_build_project_context(self, builder, sample_project):
        context = builder.build_project_context(sample_project)
        assert "项目基本信息" in context
        assert "Build a Website" in context
        assert "500-1000 USD" in context

    def test_build_project_context_with_score(self, builder, sample_project):
        score_data = {"score": 8.5, "reason": "Good budget.", "suggested_bid": 750}
        context = builder.build_project_context(sample_project, score_data)
        assert "AI 分析结果" in context
        assert "8.5/10" in context

    def test_build_prompt(self, builder, sample_project):
        prompt = builder.build_prompt(sample_project, style="narrative", structure="three_step")
        assert "senior freelance developer" in prompt
        assert "风格要求：叙事化表达" in prompt
        assert "结构要求：三段式提案" in prompt

    def test_build_prompt_includes_career_profile_context(self, builder, sample_project):
        prompt = builder.build_prompt(sample_project, style="narrative", structure="three_step")
        assert "候选人职业背景（来自个人简历-核心能力）" in prompt
        assert "Backend/API engineering" in prompt
        assert "Language Correction" not in prompt

    def test_build_prompt_enforces_direct_english_generation(self, builder, sample_project):
        prompt = builder.build_prompt(sample_project, style="narrative", structure="three_step")
        assert "English only" in prompt
        assert "do not translate from Chinese" in prompt
        assert "Target" in prompt and "characters" in prompt

    def test_build_prompt_includes_reference_samples(self, builder, sample_project):
        prompt = builder.build_prompt(sample_project, style="narrative", structure="three_step")
        assert "高质量投标参考（仅参考风格与结构，禁止照搬原文）" in prompt
        assert "Anti-Template" in prompt
        assert "Sentence Variety" in prompt
        assert "Project-Specific Detail" in prompt

    def test_get_system_prompt_for_scoring(self, builder):
        prompt = builder.get_system_prompt_for_scoring()
        assert "EVALUATION WORKFLOW" in prompt
        assert "SCORING CRITERIA" in prompt
