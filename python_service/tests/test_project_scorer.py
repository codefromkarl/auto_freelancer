import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON_SERVICE = REPO_ROOT / "python_service"
sys.path.insert(0, str(PYTHON_SERVICE))

from services.project_scorer import ProjectScorer


def test_small_task_multiplier_reduces_hours():
    scorer = ProjectScorer()
    project = {
        "title": "Fix Android app bug",
        "full_description": "Small bug fix for Android app crash",
    }
    hours = scorer.estimate_project_hours(project)
    assert hours <= 20


def test_budget_efficiency_bid_oriented():
    scorer = ProjectScorer()
    project = {
        "title": "API integration",
        "budget": {"minimum": 1000, "maximum": 1000},
        "currency_code": "USD",
        "type": "fixed",
    }
    score, _ = scorer.score_budget_efficiency(project, estimated_hours=20)
    assert 8.0 <= score <= 10.0


def test_competition_scoring_with_bonus():
    scorer = ProjectScorer()
    project = {
        "bid_stats": {"bid_count": 10},
        "submitdate": 0,
    }
    score = scorer.score_competition(project)
    assert score >= 10.0
