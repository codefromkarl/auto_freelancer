import asyncio
import logging
from unittest.mock import AsyncMock

import pytest
import scheduler


@pytest.fixture
def cycle(monkeypatch, workflow_db):
    monkeypatch.setattr(scheduler, '_step_fetch', AsyncMock(return_value=set()))
    monkeypatch.setattr(scheduler, '_step_fetch_competitor_bids', AsyncMock(return_value=0))
    monkeypatch.setattr(scheduler, '_step_score', AsyncMock(return_value=0))
    candidates = [{'freelancer_id':123, 'currency_code':'USD', 'suggested_bid':100}]
    monkeypatch.setattr(scheduler, 'select_bid_candidates', lambda *_:candidates)
    return dict(keywords=['python'], limit=1, since_days=7, allowed_statuses=['active'],
        bid_threshold=7, max_bids_per_cycle=3, fixed_price_only=True,
        logger=logging.getLogger('scheduler-test'), weekly_report_enabled=False), candidates


def test_missing_qq_recipient_never_calls_submission(cycle, monkeypatch):
    from services.qqbot_service import QQBotConfig
    from services import approved_bids
    kwargs, _ = cycle
    monkeypatch.setattr(QQBotConfig, 'from_env', lambda:QQBotConfig())
    submit = AsyncMock()
    monkeypatch.setattr(approved_bids, 'submit_approved_bid', submit)
    result = asyncio.run(scheduler.run_cycle(**kwargs,dry_run=False))
    submit.assert_not_called()
    assert result['bids_submitted']==0


def test_preview_counts_are_not_submission(cycle, monkeypatch):
    kwargs, _ = cycle
    monkeypatch.setattr(scheduler,'_step_auto_bid',AsyncMock(return_value=[{'status':'dry_run'}]))
    result = asyncio.run(scheduler.run_cycle(**kwargs,dry_run=True))
    assert result['bids_submitted']==0
    assert result['bids_previewed']==1


@pytest.mark.parametrize('arguments',[[],['--dry-run']])
def test_cli_defaults_preview(monkeypatch,arguments):
    monkeypatch.setattr(scheduler.common,'load_env',lambda:None)
    monkeypatch.setattr(scheduler.common,'get_settings',lambda:None)
    monkeypatch.setattr(scheduler,'_shutdown',False)
    run=AsyncMock(return_value={})
    monkeypatch.setattr(scheduler,'run_cycle',run)
    assert scheduler.main(['--once','--no-night-mode',*arguments])==0
    assert run.call_args.kwargs['dry_run'] is True


def test_submit_flag_cannot_override_disabled_persistent_switch(monkeypatch):
    from config import settings
    monkeypatch.setattr(scheduler.common,'load_env',lambda:None)
    monkeypatch.setattr(scheduler.common,'get_settings',lambda:None)
    monkeypatch.setattr(settings,'BID_SUBMISSION_ENABLED',False)
    run=AsyncMock()
    monkeypatch.setattr(scheduler,'run_cycle',run)
    assert scheduler.main(['--once','--submit'])==1
    run.assert_not_called()


def test_failed_single_cycle_returns_failure(monkeypatch):
    monkeypatch.setattr(scheduler.common,'load_env',lambda:None)
    monkeypatch.setattr(scheduler.common,'get_settings',lambda:None)
    monkeypatch.setattr(scheduler,'_shutdown',False)
    monkeypatch.setattr(scheduler,'run_cycle',AsyncMock(side_effect=RuntimeError('fetch failed')))
    assert scheduler.main(['--once','--no-night-mode'])==1


def test_real_mode_always_requires_approval_even_without_confirm_flag(monkeypatch):
    from config import settings
    monkeypatch.setattr(scheduler.common,'load_env',lambda:None)
    monkeypatch.setattr(scheduler.common,'get_settings',lambda:None)
    monkeypatch.setattr(settings,'BID_SUBMISSION_ENABLED',True)
    monkeypatch.setattr(scheduler,'_shutdown',False)
    run=AsyncMock(return_value={})
    monkeypatch.setattr(scheduler,'run_cycle',run)
    assert scheduler.main(['--once','--submit','--no-night-mode'])==0
    assert run.call_args.kwargs['confirm_enabled'] is True


def test_explicit_night_collection_mode_does_not_prepare_or_submit(monkeypatch):
    monkeypatch.setattr(scheduler.common,'load_env',lambda:None)
    monkeypatch.setattr(scheduler.common,'get_settings',lambda:None)
    monkeypatch.setattr(scheduler,'_get_local_hour',lambda _:2)
    monkeypatch.setattr(scheduler,'_shutdown',False)
    run=AsyncMock(return_value={})
    monkeypatch.setattr(scheduler,'run_cycle',run)
    assert scheduler.main(['--once','--no-night-instant-bid'])==0
    assert run.call_args.kwargs['skip_bid'] is True
