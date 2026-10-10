import asyncio
import logging
from unittest.mock import AsyncMock

import pytest
import scheduler


@pytest.fixture
def cycle(monkeypatch):
    monkeypatch.setattr(scheduler, "_step_fetch", AsyncMock(return_value=set()))
    monkeypatch.setattr(scheduler, "_step_fetch_competitor_bids", AsyncMock(return_value=0))
    monkeypatch.setattr(scheduler, "_step_score", AsyncMock(return_value=0))
    candidates = [{"freelancer_id": 123, "currency_code": "USD", "suggested_bid": 100}]
    monkeypatch.setattr(scheduler, "select_bid_candidates", lambda *_: candidates)
    bid = AsyncMock(return_value=[{"status": "dry_run"}])
    monkeypatch.setattr(scheduler, "_step_auto_bid", bid)
    return dict(keywords=["python"], limit=1, since_days=7, allowed_statuses=["open"],
        bid_threshold=7, max_bids_per_cycle=3, fixed_price_only=True,
        logger=logging.getLogger("scheduler-test"), weekly_report_enabled=False), bid, candidates


def test_requested_confirmation_without_config_blocks(cycle, monkeypatch):
    kwargs, bid, _ = cycle
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    result = asyncio.run(scheduler.run_cycle(**kwargs, dry_run=False, confirm_enabled=True))
    bid.assert_not_called()
    assert result["bids_submitted"] == 0
    assert result["confirm_result"] == "not_configured"


def test_confirmation_failure_blocks(cycle, monkeypatch):
    import telegram_confirm
    kwargs, bid, _ = cycle
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setattr(telegram_confirm.TelegramConfirm, "send_candidates",
                        lambda *_: (_ for _ in ()).throw(RuntimeError("offline")))
    result = asyncio.run(scheduler.run_cycle(**kwargs, dry_run=False, confirm_enabled=True))
    bid.assert_not_called()
    assert result["bids_submitted"] == 0


def test_preview_is_not_counted_as_submitted(cycle):
    kwargs, _, _ = cycle
    result = asyncio.run(scheduler.run_cycle(**kwargs, dry_run=True, confirm_enabled=True))
    assert result["bids_submitted"] == 0
    assert result["bids_previewed"] == 1


def test_morning_confirmation_is_required_by_default(cycle, monkeypatch):
    _, bid, candidates = cycle
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    result = asyncio.run(scheduler._morning_batch_bid(candidates, False, 1, logging.getLogger()))
    bid.assert_not_called()
    assert result["bids_submitted"] == 0


@pytest.mark.parametrize("arguments,preview", [([], True), (["--dry-run"], True), (["--submit"], False)])
def test_cli_default_preview_and_explicit_submission(monkeypatch, arguments, preview):
    monkeypatch.setattr(scheduler.common, "load_env", lambda: None)
    monkeypatch.setattr(scheduler.common, "get_settings", lambda: None)
    run = AsyncMock(return_value={})
    monkeypatch.setattr(scheduler, "run_cycle", run)
    monkeypatch.setattr(scheduler, "_shutdown", False)
    assert scheduler.main(["--once", "--no-night-mode", *arguments]) == 0
    assert run.call_args.kwargs["dry_run"] is preview


def test_night_mode_preserves_confirmation(monkeypatch):
    monkeypatch.setattr(scheduler.common, "load_env", lambda: None)
    monkeypatch.setattr(scheduler.common, "get_settings", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setattr(scheduler, "_get_local_hour", lambda _: 2)
    monkeypatch.setattr(scheduler, "_shutdown", False)
    run = AsyncMock(return_value={})
    monkeypatch.setattr(scheduler, "run_cycle", run)
    assert scheduler.main(["--once", "--submit", "--confirm"]) == 0
    assert run.call_args.kwargs["confirm_enabled"] is True
