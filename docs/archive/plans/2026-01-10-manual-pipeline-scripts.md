# Manual Pipeline Scripts Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build five standalone manual pipeline scripts with shared utilities, idempotency, clear summaries, and file-lock based concurrency safety.

**Architecture:** Add a shared `common.py` for env loading, DB access, logging, and locking, then implement each script as a CLI entrypoint that uses DB state and service modules directly. Keep logic deterministic and idempotent via DB checks and status updates.

**Tech Stack:** Python 3, SQLAlchemy, freelancersdk, openai SDK, asyncio.

### Task 1: Add shared utilities and tests

**Files:**
- Modify: `scripts/manual_pipeline/common.py`
- Test: `python_service/tests/test_manual_pipeline_common.py`

**Step 1: Write the failing test**

```python
from scripts.manual_pipeline import common

def test_parse_env_lines_basic():
    data = common.parse_env_lines("A=1\n# comment\nB=two\n")
    assert data == {"A": "1", "B": "two"}
```

**Step 2: Run test to verify it fails**

Run: `pytest python_service/tests/test_manual_pipeline_common.py::test_parse_env_lines_basic -v`
Expected: FAIL (function not implemented or behavior incorrect)

**Step 3: Write minimal implementation**

```python
def parse_env_lines(text: str) -> dict[str, str]:
    # ...
```

**Step 4: Run test to verify it passes**

Run: `pytest python_service/tests/test_manual_pipeline_common.py::test_parse_env_lines_basic -v`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/manual_pipeline/common.py python_service/tests/test_manual_pipeline_common.py
git commit -m "feat: add manual pipeline shared utilities"
```

### Task 2: Implement 01_check_env and tests

**Files:**
- Modify: `scripts/manual_pipeline/01_check_env.py`
- Test: `python_service/tests/test_manual_pipeline_scripts.py`

**Step 1: Write the failing test**

```python
from scripts.manual_pipeline import check_env

def test_check_env_main_missing_env_exits_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(check_env.common, "validate_env", lambda *args, **kwargs: (False, ["FREELANCER_OAUTH_TOKEN"]))
    code = check_env.main([])
    assert code == 1
```

**Step 2: Run test to verify it fails**

Run: `pytest python_service/tests/test_manual_pipeline_scripts.py::test_check_env_main_missing_env_exits_nonzero -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
def main(argv=None) -> int:
    # parse args, validate env, return exit code
```

**Step 4: Run test to verify it passes**

Run: `pytest python_service/tests/test_manual_pipeline_scripts.py::test_check_env_main_missing_env_exits_nonzero -v`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/manual_pipeline/01_check_env.py python_service/tests/test_manual_pipeline_scripts.py
git commit -m "feat: add env check script"
```

### Task 3: Implement 02_fetch and tests

**Files:**
- Modify: `scripts/manual_pipeline/02_fetch.py`
- Test: `python_service/tests/test_manual_pipeline_scripts.py`

**Step 1: Write the failing test**

```python
from scripts.manual_pipeline import fetch_projects

def test_fetch_main_runs(monkeypatch):
    async def fake_search(*args, **kwargs):
        return [{"id": 1, "title": "t"}]
    monkeypatch.setattr(fetch_projects.project_service, "search_projects", fake_search)
    code = fetch_projects.main(["--limit", "1", "--keywords", "python"])
    assert code == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest python_service/tests/test_manual_pipeline_scripts.py::test_fetch_main_runs -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
def main(argv=None) -> int:
    # parse args, call search, update status, print summary
```

**Step 4: Run test to verify it passes**

Run: `pytest python_service/tests/test_manual_pipeline_scripts.py::test_fetch_main_runs -v`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/manual_pipeline/02_fetch.py python_service/tests/test_manual_pipeline_scripts.py
git commit -m "feat: add fetch script"
```

### Task 4: Implement 03_score and tests

**Files:**
- Modify: `scripts/manual_pipeline/03_score.py`
- Test: `python_service/tests/test_manual_pipeline_scripts.py`

**Step 1: Write the failing test**

```python
from scripts.manual_pipeline import score_projects

def test_score_main_no_projects(monkeypatch):
    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self
        def order_by(self, *args, **kwargs):
            return self
        def limit(self, *args, **kwargs):
            return self
        def all(self):
            return []
    class FakeSession:
        def query(self, *args, **kwargs):
            return FakeQuery()
    monkeypatch.setattr(score_projects.common, "get_db_context", lambda: (yield FakeSession()))
    code = score_projects.main(["--limit", "10"])
    assert code == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest python_service/tests/test_manual_pipeline_scripts.py::test_score_main_no_projects -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
def main(argv=None) -> int:
    # query pending, call LLM, update, summary
```

**Step 4: Run test to verify it passes**

Run: `pytest python_service/tests/test_manual_pipeline_scripts.py::test_score_main_no_projects -v`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/manual_pipeline/03_score.py python_service/tests/test_manual_pipeline_scripts.py
git commit -m "feat: add scoring script"
```

### Task 5: Implement 04_review and tests

**Files:**
- Modify: `scripts/manual_pipeline/04_review.py`
- Test: `python_service/tests/test_manual_pipeline_scripts.py`

**Step 1: Write the failing test**

```python
from scripts.manual_pipeline import review_projects

def test_review_main_no_rows(monkeypatch, tmp_path):
    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self
        def order_by(self, *args, **kwargs):
            return self
        def all(self):
            return []
    class FakeSession:
        def query(self, *args, **kwargs):
            return FakeQuery()
    monkeypatch.setattr(review_projects.common, "get_db_context", lambda: (yield FakeSession()))
    code = review_projects.main(["--output", str(tmp_path / "out.txt")])
    assert code == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest python_service/tests/test_manual_pipeline_scripts.py::test_review_main_no_rows -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
def main(argv=None) -> int:
    # query, print table, write report
```

**Step 4: Run test to verify it passes**

Run: `pytest python_service/tests/test_manual_pipeline_scripts.py::test_review_main_no_rows -v`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/manual_pipeline/04_review.py python_service/tests/test_manual_pipeline_scripts.py
git commit -m "feat: add review script"
```

### Task 6: Implement 05_bid and tests

**Files:**
- Modify: `scripts/manual_pipeline/05_bid.py`
- Test: `python_service/tests/test_manual_pipeline_scripts.py`

**Step 1: Write the failing test**

```python
from scripts.manual_pipeline import bid_projects

def test_bid_main_dry_run(monkeypatch):
    code = bid_projects.main(["--project-id", "1", "--dry-run"])
    assert code == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest python_service/tests/test_manual_pipeline_scripts.py::test_bid_main_dry_run -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
def main(argv=None) -> int:
    # prompt/select project, show preview, dry-run or submit
```

**Step 4: Run test to verify it passes**

Run: `pytest python_service/tests/test_manual_pipeline_scripts.py::test_bid_main_dry_run -v`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/manual_pipeline/05_bid.py python_service/tests/test_manual_pipeline_scripts.py
git commit -m "feat: add bid script"
```

**Note:** If this repository is not a git repo, skip commit steps.
