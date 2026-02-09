import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON_SERVICE = REPO_ROOT / "python_service"
sys.path.insert(0, str(PYTHON_SERVICE))

from services.project_scorer import ProjectScorer


def test_small_task_multiplier_reduces_hours():
    scorer = ProjectScorer()
    # Base hours for web might be 20. With "fix" it should be reduced.
    project = {
        "title": "Fix Android app bug",
        "full_description": "Small bug fix for Android app crash",
    }
    hours = scorer.estimate_project_hours(project)
    # Android base is 80 or 40. "fix" multiplier is 0.3. 80 * 0.3 = 24.
    # Actually let's check the code:
    # "android" in title -> hours += 80.
    # "fix" and "bug" in text -> small_hits = 2 -> multiplier = 0.2.
    # 80 * 0.2 = 16.
    assert hours <= 20


def test_budget_efficiency_bid_oriented():
    scorer = ProjectScorer()
    # Case 1: $50/h -> Optimal ($20-60 range) -> Score should be >= 8.0
    project = {
        "title": "API integration",
        "budget": {"minimum": 1000, "maximum": 1000},
        "currency_code": "USD",
        "type": "fixed",
    }
    # 1000 / 20 = 50.
    score, _ = scorer.score_budget_efficiency(project, estimated_hours=20)
    assert 8.0 <= score <= 10.0

    # Case 2: $100/h -> High risk ($80+) -> Score should be <= 6.0
    # 1000 / 10 = 100.
    score, _ = scorer.score_budget_efficiency(project, estimated_hours=10)
    assert score <= 6.0


def test_competition_scoring_with_bonus():
    scorer = ProjectScorer()
    # Optimal bid count (5-20) -> Base 10.0
    project = {
        "bid_stats": {"bid_count": 10},
        "submitdate": time.time(), # Recent
    }
    score = scorer.score_competition(project)
    assert score == 10.0 # Clamped to 10

    # High bid count (21-40) -> Base 6.0 + 1.0 bonus = 7.0
    project_with_bonus = {
        "bid_stats": {"bid_count": 30},
        "submitdate": time.time(),
    }
    score = scorer.score_competition(project_with_bonus)
    assert score == 7.0

    # High bid count (21-40) -> Base 6.0, no bonus
    project_no_bonus = {
        "bid_stats": {"bid_count": 30},
        "submitdate": time.time() - 48 * 3600, # 48h ago
    }
    score = scorer.score_competition(project_no_bonus)
    assert score == 6.0