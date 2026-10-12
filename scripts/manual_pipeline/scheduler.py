#!/usr/bin/env python3
"""
Bounded polling pipeline: fetch -> score -> immutable QQ preview -> approved submission.
Default preview mode never submits. Real mode additionally requires the persistent
submission switch, configured approvers and an unexpired content-bound approval.
QQ Gateway runs separately via run_qqbot.py. Night collection-only mode pauses
candidate preparation and submission until the next daytime polling cycle.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import random
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_

script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))

import common

# ---------------------------------------------------------------------------
# Lazy imports (after common sets up sys.path)
# ---------------------------------------------------------------------------

_PROXY_ENV_KEYS = [
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
]
# Graceful shutdown flag
_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    _shutdown = True
    print(f"\n[Scheduler] Received signal {signum}, shutting down after current cycle...")


def _get_local_hour(tz_name: str) -> int:
    """获取指定时区的当前小时 (0-23)。"""
    return datetime.now(ZoneInfo(tz_name)).hour


def _is_night(hour: int, night_start: int, night_end: int) -> bool:
    """判断当前小时是否处于夜间时段。"""
    if night_start < night_end:
        return night_start <= hour < night_end
    # 跨午夜场景，如 night_start=22, night_end=8
    return hour >= night_start or hour < night_end


def _dedup_candidates(
    accumulated: List[Dict[str, Any]],
    new_batch: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """合并新候选到累积列表，按 freelancer_id 去重，保留高分版本。"""
    by_id: Dict[int, Dict[str, Any]] = {}
    for c in accumulated:
        by_id[c["freelancer_id"]] = c
    for c in new_batch:
        pid = c["freelancer_id"]
        existing = by_id.get(pid)
        if existing is None or c.get("ai_score", 0) > existing.get("ai_score", 0):
            by_id[pid] = c
    return sorted(by_id.values(), key=lambda x: x.get("ai_score", 0), reverse=True)


def _human_delay(min_sec: float = 1.0, max_sec: float = 3.0) -> None:
    """模拟人类操作间隔的随机延迟。"""
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)


async def _step_fetch(
    keywords: List[str],
    limit: int,
    since_days: int,
    allowed_statuses: List[str],
    fixed_price_only: bool,
    logger: logging.Logger,
) -> Set[int]:
    """Fetch projects from API and return set of freelancer_ids stored."""
    from services import project_service

    new_ids: Set[int] = set()
    successful_reads = 0
    with common.get_db_context() as db:
        for i, keyword in enumerate(keywords):
            # 关键词之间短延迟（API 自带限流，无需过长等待）
            if i > 0:
                _human_delay(0.5, 1.5)
            try:
                results = await project_service.search_projects(
                    db=db,
                    query=keyword,
                    limit=limit,
                    offset=0,
                    sync_from_api=True,
                    since_days=since_days,
                    allowed_statuses=allowed_statuses,
                    fixed_price_only=fixed_price_only,
                )
                successful_reads += 1
                for item in results:
                    pid = item.get("id")
                    if pid is not None:
                        new_ids.add(int(pid))
            except Exception as exc:
                logger.error("Fetch error for keyword '%s': %s", keyword, exc)
                from services import workflow_service as workflow
                workflow.event(db, "fetch", "failed", reason=type(exc).__name__)

    if not successful_reads:
        raise RuntimeError("All project fetches failed; this cycle is stopped")
    logger.info("Fetched %d unique project IDs", len(new_ids))
    return new_ids


async def _step_fetch_competitor_bids(
    since_days: int,
    allowed_statuses: List[str],
    fixed_price_only: bool,
    concurrency: int,
    logger: logging.Logger,
    skip_recently_fetched_minutes: int = 30,
    project_ids: Optional[Set[int]] = None,
) -> int:
    """Fetch competitor bids for market-active projects and all our bidded projects.

    Incremental strategy: skip projects whose competitor bids were fetched
    within the last ``skip_recently_fetched_minutes`` minutes.
    """
    from database.models import Project
    from services.project_service import published_since
    from services import competitor_bid_service

    cutoff = datetime.utcnow() - timedelta(days=since_days)
    freshness_cutoff = datetime.utcnow() - timedelta(minutes=skip_recently_fetched_minutes)

    with common.get_db_context() as db:
        query = (
            db.query(Project)
            .filter(func.lower(Project.status).in_(allowed_statuses))
            .filter(published_since(cutoff))
        )
        if fixed_price_only:
            query = query.filter(Project.type_id == 1)
        if project_ids is not None:
            query = query.filter(Project.freelancer_id.in_(project_ids))
        projects = query.all()

        eligible = set()
        bid_stats_ids = set()
        skipped_fresh = 0
        for p in projects:
            bid_stats = {}
            if p.bid_stats:
                try:
                    bid_stats = json.loads(p.bid_stats)
                except (json.JSONDecodeError, TypeError):
                    pass
            if bid_stats.get("bid_count", 0) > 0:
                # 增量策略：跳过最近已拉取的项目
                if (
                    p.competitor_bids_fetched_at is not None
                    and p.competitor_bids_fetched_at >= freshness_cutoff
                ):
                    skipped_fresh += 1
                    continue
                eligible.add(p.freelancer_id)
                bid_stats_ids.add(p.freelancer_id)

        # Ensure coverage for all projects we have already bid on.
        bidded_ids = competitor_bid_service.get_bidded_project_ids(db, since_days=None) if project_ids is None else []
        # 已投标项目也做增量检查
        for bid_pid in bidded_ids:
            proj = db.query(Project).filter(Project.freelancer_id == bid_pid).first()
            if proj and proj.competitor_bids_fetched_at and proj.competitor_bids_fetched_at >= freshness_cutoff:
                skipped_fresh += 1
                continue
            eligible.add(bid_pid)

        if skipped_fresh:
            logger.info(
                "Skipped %d projects with fresh competitor data (<%d min old)",
                skipped_fresh, skip_recently_fetched_minutes,
            )

        if not eligible:
            return 0

        eligible_list = sorted(eligible)
        results = await competitor_bid_service.batch_fetch_bids(
            db, eligible_list, concurrency=concurrency,
        )
        total = sum(results.values())
        logger.info(
            "Fetched %d competitor bids for %d projects (with_bids=%d, bidded=%d, skipped_fresh=%d)",
            total,
            len(eligible_list),
            len(bid_stats_ids),
            len(bidded_ids),
            skipped_fresh,
        )
        return total


async def _step_score(
    since_days: int,
    allowed_statuses: List[str],
    fixed_price_only: bool,
    batch_size: int,
    logger: logging.Logger,
) -> int:
    """Score unscored projects. Returns count of newly scored."""
    from database.models import Project
    from services.project_service import published_since, publication_timestamp
    from services.scoring_policy import score_is_current, policy_signature
    from services.llm_scoring_service import get_scoring_service

    cutoff = datetime.utcnow() - timedelta(days=since_days)
    with common.get_db_context() as db:
        pending = (
            db.query(Project)
            .filter(func.lower(Project.status).in_(allowed_statuses))
            .filter(published_since(cutoff))
            .order_by(publication_timestamp().desc(), Project.freelancer_id.desc())
            .all()
        )
        if fixed_price_only:
            # Unknown billing types stay deferred until confirmed fixed.
            pending = [p for p in pending if getattr(p, "type_id", None) == 1]

        from services import workflow_service as workflow
        signature = policy_signature(db)
        pending = [p for p in pending if workflow.evaluation_allowed(db, p) and not score_is_current(p, signature)][:50]
        if not pending:
            logger.info("No projects need scoring")
            return 0

        from config import settings
        from services.qqbot_service import QQBotConfig
        from services.qqbot_store import QQBotStore
        store = QQBotStore(QQBotConfig.from_env().state_path)
        allowance = store.score_allowance(len(pending), settings.BID_MAX_DAILY_SCORED_PROJECTS)
        pending = pending[:allowance]
        if not pending:
            logger.info('Daily scoring limit reached')
            return 0
        scoring_service = get_scoring_service()
        scoring_service.config.generate_proposals = False
        total_scored, errors, _, _ = await scoring_service.score_projects_concurrent(
            projects=pending, db=db, batch_size=batch_size, max_retries=2,
        )
        logger.info("Scored %d projects (%d errors)", total_scored, errors)
        return total_scored


def select_bid_candidates(
    since_days: int,
    allowed_statuses: List[str],
    bid_threshold: float,
    max_candidates: int,
    fixed_price_only: bool,
) -> list:
    """Select high-scoring projects that haven't been bid on yet.

    Returns list of Project ORM objects (detached-safe for read).
    """
    from database.models import Project, Bid, BidSubmission
    from services.project_service import published_since, publication_timestamp
    from services.scoring_policy import score_is_current, policy_signature, object_value
    from services.approved_bids import validate_terms, risk_review

    if max_candidates <= 0:
        return []
    cutoff = datetime.utcnow() - timedelta(days=since_days)
    with common.get_db_context() as db:
        # Subquery: project IDs that already have an active bid
        already_bid_subq = (
            db.query(Bid.project_freelancer_id)
            .filter(Bid.status.in_(["active", "submitted", "submitted_remote_only"]))
            .subquery()
            .select()
        )

        query = (
            db.query(Project)
            .filter(Project.ai_score >= bid_threshold)
            .filter(Project.ai_score.isnot(None))
            .filter(func.lower(Project.status).in_(allowed_statuses))
            .filter(published_since(cutoff))
            .filter(~Project.freelancer_id.in_(already_bid_subq))
            .filter(~Project.freelancer_id.in_(db.query(BidSubmission.project_freelancer_id)))
        )
        if fixed_price_only:
            query = query.filter(Project.type_id == 1)

        candidates = (
            query.order_by(Project.ai_score.desc(), publication_timestamp().desc(), Project.freelancer_id.desc())
            .all()
        )

        # Detach-safe: convert to dicts with needed fields
        result = []
        from services import workflow_service as workflow
        workflow.reconcile(db)
        signature = policy_signature(db)
        for p in candidates:
            row = workflow.refresh_readiness(db, p, bid_threshold, signature)
            if row.state != "ready":
                continue
            if not score_is_current(p, signature):
                continue
            if object_value(p.score_metadata).get("candidate_blocked"):
                continue
            if p.suggested_bid is None or p.estimated_hours is None:
                continue
            try:
                from services.bid_service import _resolve_submission_amount
                native = _resolve_submission_amount(p, float(p.suggested_bid), "USD")
                validate_terms(p, native, _determine_bid_period({"estimated_hours": p.estimated_hours}))
                risk_review(p)
            except (ValueError, TypeError, OverflowError):
                continue
            result.append({
                "freelancer_id": p.freelancer_id,
                "title": p.title,
                "ai_score": p.ai_score,
                "suggested_bid": float(p.suggested_bid) if p.suggested_bid else None,
                "budget_minimum": float(p.budget_minimum) if p.budget_minimum else None,
                "budget_maximum": float(p.budget_maximum) if p.budget_maximum else None,
                "currency_code": p.currency_code,
                "estimated_hours": p.estimated_hours,
                "status": p.status,
            })
            if len(result) >= max_candidates:
                break
        return result


def _determine_bid_amount(candidate: Dict[str, Any]) -> Optional[float]:
    """Determine bid amount from suggested_bid or budget range.

    Strategy: 新手阶段偏向竞争力定价，取预算范围的 55% 位置。
    """
    if candidate.get("suggested_bid"):
        return candidate["suggested_bid"]
    budget_max = candidate.get("budget_maximum")
    budget_min = candidate.get("budget_minimum")
    if budget_max and budget_min:
        # Bid at ~55% of budget range (competitive for newcomers)
        return round(budget_min + (budget_max - budget_min) * 0.55, 2)
    if budget_max:
        return round(budget_max * 0.65, 2)
    if budget_min:
        return round(budget_min * 1.2, 2)
    return None


def _determine_bid_period(candidate: Dict[str, Any]) -> int:
    """Determine bid period from estimated_hours or default."""
    hours = candidate.get("estimated_hours")
    if hours and hours > 0:
        # ~6 productive hours per day
        days = max(2, math.ceil(hours / 6))
        return min(days, 30)
    return 7  # default 7 days


async def _step_auto_bid(candidates, dry_run, logger, replacement_selector=None):
    """Prepare, notify and submit only an immutable, explicitly approved snapshot."""
    from services.approved_bids import prepare_bid, submit_approved_bid
    from services.qqbot_service import QQBotClient, QQBotConfig
    from services.qqbot_store import QQBotStore
    from services.qqbot_events import notify_snapshot
    config = QQBotConfig.from_env()
    if not config.target_id or not config.approvers:
        logger.warning('QQ target/approvers not configured; candidates stay local, no approval or submission')
        return [{'project_id': c['freelancer_id'], 'status': 'configuration_required'} for c in candidates]
    store = QQBotStore(config.state_path)
    client = QQBotClient(config)
    results = []
    from config import settings
    from database.models import Project
    from services.scoring_policy import object_value
    queue = list(candidates)
    target = len(queue)
    prepared = 0
    attempted = set()
    while queue and prepared < target and len(attempted) < settings.BID_MAX_CANDIDATE_PREPARATIONS_PER_CYCLE:
        candidate = queue.pop(0)
        pid = candidate['freelancer_id']
        if pid in attempted:
            continue
        attempted.add(pid)
        operation_stage = "preparation"
        try:
            amount = _determine_bid_amount(candidate)
            if amount is None:
                raise ValueError('Missing proposed amount')
            period = _determine_bid_period(candidate)
            with common.get_db_context() as db:
                snapshot = await prepare_bid(db, pid, amount, period,
                    amount_currency='USD' if candidate.get('suggested_bid') else candidate.get('currency_code'), store=store)
                prepared += 1
                try:
                    confirmed = await asyncio.to_thread(notify_snapshot, client, store, snapshot)
                    if confirmed:
                        from services import workflow_service as workflow
                        workflow.event(db, "notification", "confirmed", project_id=pid,
                            key=f"notified:{snapshot['id']}")
                except Exception as exc:
                    logger.error('QQ notification failed (%s); delivery not confirmed', type(exc).__name__)
                    from services import workflow_service as workflow
                    workflow.event(db, 'notification', 'failed', project_id=pid, reason=type(exc).__name__)
                    results.append({'project_id': pid, 'status': 'notification_failed'})
                    continue
                current = store.get(snapshot['id'])
                if dry_run or current['state'] != 'approved':
                    results.append({'project_id': pid, 'approval_id': snapshot['id'],
                        'status': 'dry_run' if dry_run else 'awaiting_approval'})
                else:
                    operation_stage = "submission"
                    result = await submit_approved_bid(db, snapshot['id'], store)
                    results.append({'project_id': pid, 'status': result['status']})
        except Exception as exc:
            logger.error('Candidate %s blocked (%s): %s', pid, type(exc).__name__, exc)
            results.append({'project_id': pid, 'status': 'error'})
            with common.get_db_context() as db:
                project = db.query(Project).filter_by(freelancer_id=pid).first()
                if project is not None:
                    metadata = object_value(project.score_metadata)
                    if isinstance(metadata, dict):
                        metadata['candidate_blocked'] = type(exc).__name__
                        project.score_metadata = json.dumps(metadata, ensure_ascii=False)
                    from services import workflow_service as workflow
                    row = workflow.ensure(db, project)
                    workflow.reconcile(db)
                    if row.state not in {"submitted", "outcome_unknown"}:
                        workflow.transition(db, row, "deferred", "preparation_failed", str(exc),
                            held_by="system", resume_condition="score_changed")
                    if operation_stage == "preparation":
                        workflow.event(db, "preparation", "failed", project_id=pid, reason=type(exc).__name__)
            if replacement_selector is not None:
                queue.extend(c for c in replacement_selector() if c['freelancer_id'] not in attempted
                             and c['freelancer_id'] not in {p['freelancer_id'] for p in queue})
    return results


async def _consume_approved(logger):
    from services.qqbot_service import QQBotConfig
    from services.qqbot_store import QQBotStore
    from services.approved_bids import submit_approved_bid
    config = QQBotConfig.from_env()
    if not config.target_id or not config.approvers:
        return
    store = QQBotStore(config.state_path)
    for record in store.list_active():
        if record['state'] != 'approved':
            continue
        try:
            with common.get_db_context() as db:
                await submit_approved_bid(db, record['id'], store)
        except Exception as exc:
            logger.error('Approved bid blocked (%s); no automatic retry of claimed outcomes', type(exc).__name__)


def _step_generate_weekly_report(
    since_days: int,
    output_path: str,
    sync_awards: bool,
    logger: logging.Logger,
) -> str:
    """Generate weekly bid outcome report by invoking report script."""
    script_path = common.REPO_ROOT / "scripts" / "utils" / "bid_outcome_weekly_report.py"
    cmd = [
        sys.executable,
        str(script_path),
        "--since-days",
        str(since_days),
        "--output",
        str(output_path),
    ]
    cmd.append("--sync-awards" if sync_awards else "--no-sync-awards")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        raise RuntimeError(
            f"weekly report failed (code={result.returncode}): {stderr or stdout or 'unknown error'}"
        )

    if result.stdout:
        logger.info("Weekly report generated: %s", result.stdout.strip())
    return str(output_path)


# ============================================================================
# Main cycle
# ============================================================================

async def _run_cycle(
    keywords: List[str],
    limit: int,
    since_days: int,
    allowed_statuses: List[str],
    bid_threshold: float,
    max_bids_per_cycle: int,
    dry_run: bool,
    fixed_price_only: bool,
    logger: logging.Logger,
    confirm_enabled: bool = False,
    confirm_timeout: int = 300,
    skip_bid: bool = False,
    weekly_report_enabled: bool = True,
    weekly_report_since_days: int = 7,
    weekly_report_output: Optional[str] = None,
    weekly_report_sync_awards: bool = False,
) -> Dict[str, Any]:
    """Execute one full pipeline cycle. Returns summary dict.

    Args:
        skip_bid: If True, only fetch+score, skip candidate selection and bidding.
                  Used during night mode to accumulate data without acting.
    """
    cycle_start = time.monotonic()
    summary: Dict[str, Any] = {"timestamp": datetime.utcnow().isoformat()}
    report_output = weekly_report_output or str(common.REPO_ROOT / "logs" / "bid_outcome_weekly_report.md")

    def _attach_weekly_report() -> None:
        if not weekly_report_enabled:
            return
        try:
            generated = _step_generate_weekly_report(
                since_days=weekly_report_since_days,
                output_path=report_output,
                sync_awards=weekly_report_sync_awards,
                logger=logger,
            )
            summary["weekly_report_generated"] = generated
        except Exception as exc:
            logger.error("Weekly report generation failed: %s", exc)
            summary["weekly_report_error"] = str(exc)

    # Step 1: Fetch projects
    logger.info("── Step 1/4: Fetching projects ──")
    fetched_ids = await _observed_step("fetch", _step_fetch(
        keywords, limit, since_days, allowed_statuses, fixed_price_only, logger))
    summary["fetched_projects"] = len(fetched_ids)

    # Score from search metadata first; full competitor context is only needed for
    # viable top candidates, never for projects awaiting clarification or held by an operator.
    logger.info("── Step 2/4: Scoring projects ──")
    scored = await _observed_step("score", _step_score(
        since_days, allowed_statuses, fixed_price_only, batch_size=5, logger=logger))
    summary["projects_scored"] = scored
    candidates = select_bid_candidates(
        since_days, allowed_statuses, bid_threshold, max_bids_per_cycle, fixed_price_only)
    logger.info("── Step 3/4: Fetching competitor bids for viable candidates ──")
    comp_bids = await _observed_step("competition", _step_fetch_competitor_bids(
        since_days, allowed_statuses, fixed_price_only, concurrency=10, logger=logger,
        project_ids={c["freelancer_id"] for c in candidates}))
    summary["competitor_bids_fetched"] = comp_bids

    # Night mode: skip bidding, only collect candidates for later
    if skip_bid:
        logger.info("── Step 4/4: Night mode — collecting candidates only ──")
        candidates = select_bid_candidates(
            since_days, allowed_statuses, bid_threshold, max_bids_per_cycle, fixed_price_only,
        )
        summary["bid_candidates"] = len(candidates)
        summary["bids_submitted"] = 0
        summary["bids_failed"] = 0
        summary["night_candidates"] = candidates
        _attach_weekly_report()
        elapsed = time.monotonic() - cycle_start
        summary["elapsed_seconds"] = round(elapsed, 1)
        return summary

    # Step 4: Select candidates and bid
    logger.info("── Step 4/4: Selecting candidates & bidding ──")
    candidates = select_bid_candidates(
        since_days, allowed_statuses, bid_threshold, max_bids_per_cycle, fixed_price_only,
    )
    summary["bid_candidates"] = len(candidates)

    if candidates:
        for c in candidates:
            logger.info(
                "  Candidate: %s (score=%.1f, budget=%s-%s %s)",
                c["freelancer_id"],
                c.get("ai_score", 0),
                c.get("budget_minimum", "?"),
                c.get("budget_maximum", "?"),
                c.get("currency_code", "USD"),
            )

        bid_results = await _observed_step("preparation", _step_auto_bid(candidates, dry_run, logger,
            replacement_selector=lambda: select_bid_candidates(
                since_days, allowed_statuses, bid_threshold, max_bids_per_cycle, fixed_price_only)))
        summary["bids_submitted"] = sum(
            1 for r in bid_results if r.get("status") == "submitted"
        )
        summary["bids_previewed"] = sum(1 for r in bid_results if r.get("status") == "dry_run")
        summary["bids_failed"] = sum(
            1 for r in bid_results if r.get("status") == "error"
        )

    else:
        logger.info("No qualifying candidates found (threshold=%.1f)", bid_threshold)
        summary["bids_submitted"] = 0
        summary["bids_failed"] = 0

    _attach_weekly_report()
    elapsed = time.monotonic() - cycle_start
    summary["elapsed_seconds"] = round(elapsed, 1)
    return summary


from contextvars import ContextVar
_CYCLE_STAGE = ContextVar("cycle_stage", default=None)
_CYCLE_TIMINGS = ContextVar("cycle_timings", default=None)


async def _observed_step(stage, operation):
    _CYCLE_STAGE.set(stage)
    started = time.monotonic()
    try:
        return await operation
    finally:
        timings = _CYCLE_TIMINGS.get()
        if timings is not None:
            timings[stage] = round((time.monotonic() - started) * 1000, 2)


async def run_cycle(*args, **kwargs):
    from services import workflow_service as workflow
    from database.models import WorkflowRun
    import uuid
    identity = uuid.uuid4().hex
    started = time.monotonic()
    with common.get_db_context() as db:
        db.add(WorkflowRun(id=identity, status="running"))
        workflow.reconcile(db)
    token = workflow.CURRENT_RUN.set(identity)
    stage_token = _CYCLE_STAGE.set("fetch")
    timing_token = _CYCLE_TIMINGS.set({})
    summary = {}
    failure = None
    try:
        summary = await _run_cycle(*args, **kwargs)
        summary["run_id"] = identity
        return summary
    except Exception as exc:
        failure = exc
        raise
    finally:
        summary["step_durations_ms"] = dict(_CYCLE_TIMINGS.get())
        try:
            with common.get_db_context() as db:
                row = db.query(WorkflowRun).filter_by(id=identity).one()
                from database.models import WorkflowEvent
                partial = db.query(WorkflowEvent).filter_by(run_id=identity, outcome="failed").order_by(WorkflowEvent.id).first()
                row.status = "failed" if failure else "completed_with_errors" if partial else "completed"
                row.finished_at = workflow.now()
                row.duration_ms = (time.monotonic()-started)*1000
                row.summary = json.dumps(summary, ensure_ascii=False)
                row.failed_stage = _CYCLE_STAGE.get() if failure else partial.stage if partial else None
                row.error_type = type(failure).__name__ if failure else None
        finally:
            workflow.CURRENT_RUN.reset(token)
            _CYCLE_STAGE.reset(stage_token)
            _CYCLE_TIMINGS.reset(timing_token)


# ============================================================================
# Entry point
# ============================================================================

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Automated pipeline scheduler: fetch → score → bid.",
    )
    parser.add_argument(
        "--interval", type=int, default=30,
        help="Base minutes between cycles (default: 30)",
    )
    parser.add_argument(
        "--keywords",
        default="python automation,fastapi,web scraping,api integration",
        help="Comma-separated fetch keywords",
    )
    parser.add_argument("--limit", type=int, default=20, help="Fetch limit per keyword")
    parser.add_argument("--since-days", type=int, default=3, help="Lookback window in days")
    parser.add_argument(
        "--allowed-statuses",
        default=",".join(common.DEFAULT_BIDDABLE_STATUSES),
        help="Comma-separated allowed statuses",
    )
    parser.add_argument(
        "--bid-threshold", type=float, default=7.0,
        help="Minimum AI score to auto-bid (default: 7.0)",
    )
    parser.add_argument(
        "--max-bids-per-cycle", type=int, default=3,
        help="Max bids per cycle (default: 3)",
    )
    submission_mode = parser.add_mutually_exclusive_group()
    submission_mode.add_argument(
        "--dry-run", dest="dry_run", action="store_true",
        help="Preview mode: no real bids submitted (default)",
    )
    submission_mode.add_argument(
        "--submit", dest="dry_run", action="store_false",
        help="Explicitly enable real bidding after local validation",
    )
    parser.set_defaults(dry_run=True)
    parser.add_argument(
        "--once", action="store_true",
        help="Run a single cycle then exit",
    )
    parser.add_argument(
        "--include-hourly", action="store_true",
        help="Include hourly projects (default: fixed-price only)",
    )
    parser.add_argument(
        "--keep-proxy", action="store_true",
        help="Keep proxy environment variables",
    )
    parser.add_argument(
        "--confirm", action="store_true",
        help="Compatibility flag: real bidding always requires QQ approval",
    )
    parser.add_argument(
        "--confirm-timeout", type=int, default=300,
        help="Confirmation wait timeout in seconds (default: 300)",
    )
    # 夜间模式参数
    parser.add_argument(
        "--night-start", type=int, default=0,
        help="Night mode start hour in local time (default: 0)",
    )
    parser.add_argument(
        "--night-end", type=int, default=8,
        help="Night mode end hour in local time (default: 8)",
    )
    parser.add_argument(
        "--timezone", type=str, default=None,
        help="Timezone for schedule (default: from TIMEZONE env or Asia/Shanghai)",
    )
    parser.add_argument(
        "--no-night-mode", action="store_true",
        help="Disable night mode, run 24h with same behavior",
    )
    parser.add_argument(
        "--night-instant-bid", action="store_true", default=True,
        help="Bid immediately during night mode instead of accumulating (default: on)",
    )
    parser.add_argument(
        "--no-night-instant-bid", dest="night_instant_bid", action="store_false",
        help="Accumulate candidates during night and batch-bid at morning (legacy behavior)",
    )
    parser.add_argument(
        "--weekly-report",
        dest="weekly_report",
        action="store_true",
        help="Generate bid outcome weekly report each cycle (default: on)",
    )
    parser.add_argument(
        "--no-weekly-report",
        dest="weekly_report",
        action="store_false",
        help="Disable weekly report generation in scheduler",
    )
    parser.add_argument(
        "--weekly-report-since-days",
        type=int,
        default=7,
        help="Lookback days for weekly report (default: 7)",
    )
    parser.add_argument(
        "--weekly-report-output",
        default=str(common.REPO_ROOT / "logs" / "bid_outcome_weekly_report.md"),
        help="Output path for weekly report",
    )
    parser.add_argument(
        "--weekly-report-sync-awards",
        action="store_true",
        help="Sync award data when generating weekly report (default: off)",
    )
    parser.set_defaults(weekly_report=True)
    args = parser.parse_args(argv)

    logger = common.setup_logging(
        "scheduler",
        log_file=str(common.REPO_ROOT / "logs" / "scheduler.log"),
    )

    try:
        common.load_env()
        common.get_settings()
    except Exception as exc:
        print(f"Failed to load settings: {exc}")
        return common.EXIT_VALIDATION_ERROR

    if not args.dry_run:
        from config import settings
        if not settings.BID_SUBMISSION_ENABLED:
            logger.error('Real bidding is disabled in configuration')
            return common.EXIT_VALIDATION_ERROR
        from services.qqbot_service import QQBotConfig
        config = QQBotConfig.from_env()
        if not config.target_id or not config.approvers:
            logger.error('QQ target and approver OpenIDs must be configured')
            return common.EXIT_VALIDATION_ERROR

    if not args.keep_proxy:
        for key in _PROXY_ENV_KEYS:
            os.environ.pop(key, None)
    else:
        # httpx (used by openai/anthropic SDKs) does not support socks proxies.
        # Remove ALL_PROXY/all_proxy if they use socks:// to avoid breaking LLM calls,
        # while keeping HTTP_PROXY/HTTPS_PROXY (http://) intact.
        for key in ("ALL_PROXY", "all_proxy"):
            val = os.environ.get(key, "")
            if val.startswith("socks"):
                os.environ.pop(key, None)
                logger.info("Removed %s=%s (socks not supported by httpx)", key, val)

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    allowed_statuses = common.parse_statuses(args.allowed_statuses)
    fixed_price_only = not args.include_hourly
    tz_name = args.timezone or os.getenv("TIMEZONE", "Asia/Shanghai")

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    mode_label = "[DRY RUN] " if args.dry_run else ""
    night_label = "" if args.no_night_mode else f" [NIGHT {args.night_start:02d}-{args.night_end:02d}]"
    logger.info(
        "%sScheduler started:%s interval=%dm, threshold=%.1f, max_bids=%d, tz=%s",
        mode_label, night_label, args.interval, args.bid_threshold,
        args.max_bids_per_cycle, tz_name,
    )
    print(
        f"{mode_label}Scheduler started:{night_label} "
        f"interval={args.interval}m, threshold={args.bid_threshold}, "
        f"max_bids={args.max_bids_per_cycle}, tz={tz_name}"
    )

    try:
        return asyncio.run(_scheduler_loop(args, keywords, allowed_statuses, fixed_price_only, tz_name, logger))
    except KeyboardInterrupt:
        return 0


async def _scheduler_loop(args, keywords, allowed_statuses, fixed_price_only, tz_name, logger):
    cycle_count = 0
    while not _shutdown:
        cycle_count += 1
        night = not args.no_night_mode and _is_night(_get_local_hour(tz_name), args.night_start, args.night_end)
        hold = night and not args.night_instant_bid
        cycle_failed = False
        try:
            summary = await run_cycle(
                keywords=keywords, limit=args.limit, since_days=args.since_days,
                allowed_statuses=allowed_statuses, bid_threshold=args.bid_threshold,
                max_bids_per_cycle=args.max_bids_per_cycle, dry_run=args.dry_run,
                fixed_price_only=fixed_price_only, logger=logger, confirm_enabled=True,
                confirm_timeout=args.confirm_timeout, skip_bid=hold,
                weekly_report_enabled=args.weekly_report,
                weekly_report_since_days=args.weekly_report_since_days,
                weekly_report_output=args.weekly_report_output,
                weekly_report_sync_awards=args.weekly_report_sync_awards)
            print(f"Cycle {cycle_count}: {summary}", flush=True)
        except Exception as exc:
            cycle_failed = True
            logger.error('Cycle failed (%s); no submission from this cycle', type(exc).__name__)
        if args.once:
            return 1 if cycle_failed else 0
        # During the polling interval process only already-approved snapshots.
        for second in range(max(60, args.interval*60)):
            if _shutdown:
                break
            if not args.dry_run and not hold and second % 5 == 0:
                await _consume_approved(logger)
            await asyncio.sleep(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
