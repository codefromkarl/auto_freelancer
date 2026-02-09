# Scoring System Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix currency fallback, improve hour estimates and bid-oriented scoring, and make LLM provider scoring truly concurrent with configurable race/ensemble modes.

**Architecture:** Adjust core scoring logic in `project_scorer.py`, add safe currency fallback logic in `currency_converter.py` with explicit None handling, and refactor `llm_scoring_service.py` to run provider calls concurrently with a settings-driven scoring mode. Align default weights in code and YAML config.

**Tech Stack:** Python, asyncio, pytest, httpx, pydantic settings

### Task 1: Fix currency converter fallback behavior (FIX-001)

**Files:**
- Modify: `python_service/utils/currency_converter.py`
- Modify: `python_service/services/project_scorer.py`
- Modify: `python_service/services/project_service.py`
- Test: `python_service/tests/test_currency_converter.py`

**Step 1: Write the failing test**

```python
import asyncio

from utils.currency_converter import CurrencyConverter


def test_get_rate_sync_fallback_on_missing(monkeypatch):
    converter = CurrencyConverter(cache_file=":memory:")
    converter.rates = {"USD": 1.0}
    converter.last_updated = 0.0

    def _no_update(*_args, **_kwargs):
        return None

    monkeypatch.setattr(converter, "update_rates_sync", _no_update)
    assert converter.get_rate_sync("INR") == 0.012
    assert converter.get_rate_sync("XXX") is None


async def _get_rate_async(converter, code):
    return await converter.get_rate(code)


def test_get_rate_async_fallback_on_missing(monkeypatch):
    converter = CurrencyConverter(cache_file=":memory:")
    converter.rates = {"USD": 1.0}
    converter.last_updated = 0.0

    async def _no_update(*_args, **_kwargs):
        return None

    monkeypatch.setattr(converter, "update_rates", _no_update)
    assert asyncio.run(_get_rate_async(converter, "VND")) == 0.000041
    assert asyncio.run(_get_rate_async(converter, "ZZZ")) is None
```

**Step 2: Run test to verify it fails**

Run: `pytest python_service/tests/test_currency_converter.py -v`
Expected: FAIL with `1.0` fallback or `None` mismatches.

**Step 3: Write minimal implementation**

```python
FALLBACK_RATES = {"INR": 0.012, "IDR": 0.000064, "VND": 0.000041}

# In get_rate_sync / get_rate:
rate = self.rates.get(currency_code)
if rate is None:
    rate = self.FALLBACK_RATES.get(currency_code)
return rate
```

Update call sites to handle `None` rate safely (skip budget filter and return neutral budget score when currency is unknown).

**Step 4: Run test to verify it passes**

Run: `pytest python_service/tests/test_currency_converter.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add python_service/utils/currency_converter.py python_service/services/project_scorer.py python_service/services/project_service.py python_service/tests/test_currency_converter.py
git commit -m "fix: add currency fallback rates"
```

### Task 2: Update hour estimation and bid-oriented scoring (FIX-002/REF-001/REF-002/REF-004)

**Files:**
- Modify: `python_service/services/project_scorer.py`
- Modify: `python_service/config/scoring_rules.yaml`
- Test: `python_service/tests/test_project_scorer.py`

**Step 1: Write the failing test**

```python
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
```

**Step 2: Run test to verify it fails**

Run: `pytest python_service/tests/test_project_scorer.py -v`
Expected: FAIL on old hour estimation/scoring ranges.

**Step 3: Write minimal implementation**

```python
from enum import Enum

class ProjectComplexity(Enum):
    TRIVIAL = (1, 4)
    SMALL = (4, 20)
    MEDIUM = (20, 80)
    LARGE = (80, 200)

# In estimate_project_hours:
# compute base hours then apply small-task multiplier based on keywords
# clamp final hours within [1, 200]

# In score_budget_efficiency:
# apply bid-oriented piecewise scoring

# In score_competition:
# apply bid count buckets and +bonus within 24h

# Update DEFAULT_WEIGHTS, ScoringConfig defaults, and scoring_rules.yaml to new weights
```

**Step 4: Run test to verify it passes**

Run: `pytest python_service/tests/test_project_scorer.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add python_service/services/project_scorer.py python_service/config/scoring_rules.yaml python_service/tests/test_project_scorer.py
git commit -m "refactor: bid-oriented scoring and hour estimates"
```

### Task 3: Make LLM scoring truly concurrent with race/ensemble (REF-003)

**Files:**
- Modify: `python_service/config.py`
- Modify: `python_service/services/llm_scoring_service.py`
- Test: `python_service/tests/test_llm_scoring_service.py`

**Step 1: Write the failing test**

```python
import asyncio

from services.llm_scoring_service import LLMScoringService


class DummyClient:
    def __init__(self, result):
        self.result = result


async def test_llm_scoring_ensemble(monkeypatch):
    service = LLMScoringService()
    service.providers = [
        {"name": "openai", "model": "m1", "api_key": "k", "base_url": None},
        {"name": "openai", "model": "m2", "api_key": "k", "base_url": None},
    ]

    async def _score(*_args, **_kwargs):
        return {"score": 6.0, "reason": "r", "proposal": "p", "provider_model": "m"}

    monkeypatch.setattr(service, "_get_openai_client", lambda *_: DummyClient({}))
    monkeypatch.setattr(service, "_score_with_openai", _score)

    payload = {"id": 1, "title": "t"}
    ok, result = await service._score_with_providers(payload)
    assert ok is True
    assert result["score"] == 6.0
```

**Step 2: Run test to verify it fails**

Run: `pytest python_service/tests/test_llm_scoring_service.py -v`
Expected: FAIL due to missing `_score_with_providers` or mode handling.

**Step 3: Write minimal implementation**

```python
# config.py: add LLM_SCORING_MODE: str = "ensemble"
# llm_scoring_service.py:
# - add helper to run provider tasks concurrently
# - ensemble: gather all results, average numeric fields
# - race: return first successful, cancel remaining
```

**Step 4: Run test to verify it passes**

Run: `pytest python_service/tests/test_llm_scoring_service.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add python_service/config.py python_service/services/llm_scoring_service.py python_service/tests/test_llm_scoring_service.py
git commit -m "refactor: concurrent LLM scoring with modes"
```
