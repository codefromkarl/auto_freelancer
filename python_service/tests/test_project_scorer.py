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
    assert score == 10.0  # High net earnings are not an inferred low win probability.


def test_competition_scoring_is_continuous_and_age_sensitive():
    scorer = ProjectScorer()
    values = [scorer.score_competition({"bid_stats": {"bid_count": n}}) for n in (0, 4, 5, 20, 21, 41)]
    assert values == sorted(values, reverse=True)
    assert abs(values[1] - values[2]) < 1
    assert scorer.score_competition({}) == 5
    fresh = {"bid_stats": {"bid_count": 30}, "submitdate": time.time()}
    old = {**fresh, "submitdate": time.time() - 48 * 3600}
    assert scorer.score_competition(fresh) > scorer.score_competition(old)
