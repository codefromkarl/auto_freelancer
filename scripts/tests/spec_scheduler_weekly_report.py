import asyncio
import importlib.util
import sys
from pathlib import Path


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _Logger:
    def info(self, *_args, **_kwargs):
        return None

    def warning(self, *_args, **_kwargs):
        return None

    def error(self, *_args, **_kwargs):
        return None


def test_step_generate_weekly_report_invokes_report_script(monkeypatch, tmp_path):
    module = _load_module(Path("scripts/manual_pipeline/scheduler.py"), "scheduler_weekly_report")

    captured = {}

    class _RunResult:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def _fake_run(cmd, capture_output, text, timeout):
        captured["cmd"] = cmd
        captured["capture_output"] = capture_output
        captured["text"] = text
        captured["timeout"] = timeout
        return _RunResult()

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    output_file = tmp_path / "weekly.md"
    generated = module._step_generate_weekly_report(
        since_days=7,
        output_path=str(output_file),
        sync_awards=False,
        logger=_Logger(),
    )

    assert generated == str(output_file)
    assert captured["cmd"][0] == sys.executable
    assert captured["cmd"][1].endswith("scripts/utils/bid_outcome_weekly_report.py")
    assert "--since-days" in captured["cmd"]
    assert "--output" in captured["cmd"]
    assert "--no-sync-awards" in captured["cmd"]


def test_run_cycle_includes_weekly_report_summary(monkeypatch):
    module = _load_module(Path("scripts/manual_pipeline/scheduler.py"), "scheduler_weekly_report_cycle")

    async def _fake_fetch(*_args, **_kwargs):
        return set()

    async def _fake_fetch_comp(*_args, **_kwargs):
        return 0

    async def _fake_score(*_args, **_kwargs):
        return 0

    monkeypatch.setattr(module, "_step_fetch", _fake_fetch)
    monkeypatch.setattr(module, "_step_fetch_competitor_bids", _fake_fetch_comp)
    monkeypatch.setattr(module, "_step_score", _fake_score)
    monkeypatch.setattr(module, "select_bid_candidates", lambda *_a, **_k: [])
    monkeypatch.setattr(
        module,
        "_step_generate_weekly_report",
        lambda **_kwargs: "/tmp/weekly_report.md",
    )

    summary = asyncio.run(
        module.run_cycle(
            keywords=["python"],
            limit=1,
            since_days=1,
            allowed_statuses=["open", "active", "open_for_bidding"],
            bid_threshold=7.0,
            max_bids_per_cycle=1,
            dry_run=True,
            fixed_price_only=True,
            logger=_Logger(),
            confirm_enabled=False,
            confirm_timeout=1,
            skip_bid=False,
            weekly_report_enabled=True,
            weekly_report_since_days=7,
            weekly_report_output="/tmp/weekly_report.md",
            weekly_report_sync_awards=False,
        )
    )

    assert summary["weekly_report_generated"] == "/tmp/weekly_report.md"
