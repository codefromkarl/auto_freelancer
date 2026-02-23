#!/usr/bin/env python3
"""
Automated pipeline scheduler.

Runs a fetch → score → analyze → bid cycle every N minutes.
Only bids on new high-scoring projects that pass all quality gates.

Schedule modes:
    Day   (08:00-24:00): fetch → score → bid, 5-10 min random interval
    Night (00:00-08:00): fetch → score only, candidates accumulated;
                         at 08:00 batch-push to Telegram for notification, then auto-bid

Usage:
    python scheduler.py                          # default: 5-min interval
    python scheduler.py --interval 10            # 10-min interval
    python scheduler.py --dry-run                # preview only, no real bids
    python scheduler.py --once                   # single run then exit
    python scheduler.py --bid-threshold 7.5      # only bid on score >= 7.5
    python scheduler.py --night-start 0 --night-end 8  # night hours (default)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
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
_TELEGRAM_PROXY_ENV_KEYS = [
    "TELEGRAM_PROXY",
    "TELEGRAM_HTTPS_PROXY",
    "TELEGRAM_HTTP_PROXY",
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
]

# Graceful shutdown flag
_shutdown = False

# 夜间积累的候选项目（跨 cycle 持久化，8:00 统一通知并自动投标）
_night_candidates: List[Dict[str, Any]] = []


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


def _first_nonempty_env(keys: List[str]) -> Optional[str]:
    for key in keys:
        value = os.getenv(key)
        if value and value.strip():
            return value.strip()
    return None


def _build_telegram_proxies() -> Optional[Dict[str, str]]:
    """Build explicit Telegram proxy settings from env."""
    return common.get_telegram_proxies()


def _promote_telegram_proxy_env(logger: Optional[logging.Logger] = None) -> None:
    """
    Preserve a Telegram-specific proxy before global proxy cleanup.

    Scheduler usually clears global proxy variables for pipeline stability.
    Telegram requests are isolated to TELEGRAM_PROXY so notifications can still work.
    """
    # If already set, we are good
    if os.getenv("TELEGRAM_PROXY"):
        if logger:
            logger.debug("TELEGRAM_PROXY already set: %s", os.getenv("TELEGRAM_PROXY"))
        return

    # Look for any existing proxy to promote
    proxies = common.get_telegram_proxies()
    if proxies:
        proxy_url = proxies["https"]
        os.environ["TELEGRAM_PROXY"] = proxy_url
        if logger:
            logger.info("Promoted %s to TELEGRAM_PROXY", proxy_url)
    else:
        if logger:
            logger.debug("No proxy found to promote to TELEGRAM_PROXY")


# ============================================================================
# Core pipeline functions
# ============================================================================

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
                for item in results:
                    pid = item.get("id")
                    if pid is not None:
                        new_ids.add(int(pid))
            except Exception as exc:
                logger.error("Fetch error for keyword '%s': %s", keyword, exc)

    logger.info("Fetched %d unique project IDs", len(new_ids))
    return new_ids


async def _step_fetch_competitor_bids(
    since_days: int,
    allowed_statuses: List[str],
    fixed_price_only: bool,
    concurrency: int,
    logger: logging.Logger,
    skip_recently_fetched_minutes: int = 30,
) -> int:
    """Fetch competitor bids for market-active projects and all our bidded projects.

    Incremental strategy: skip projects whose competitor bids were fetched
    within the last ``skip_recently_fetched_minutes`` minutes.
    """
    from database.models import Project
    from services import competitor_bid_service

    cutoff = datetime.utcnow() - timedelta(days=since_days)
    freshness_cutoff = datetime.utcnow() - timedelta(minutes=skip_recently_fetched_minutes)

    with common.get_db_context() as db:
        query = (
            db.query(Project)
            .filter(func.lower(Project.status).in_(allowed_statuses))
            .filter(Project.created_at >= cutoff)
        )
        if fixed_price_only:
            query = query.filter(or_(Project.type_id == 1, Project.type_id.is_(None)))
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
        bidded_ids = competitor_bid_service.get_bidded_project_ids(db, since_days=None)
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
    from services.llm_scoring_service import get_scoring_service

    cutoff = datetime.utcnow() - timedelta(days=since_days)
    with common.get_db_context() as db:
        pending = (
            db.query(Project)
            .filter(Project.ai_score.is_(None))
            .filter(func.lower(Project.status).in_(allowed_statuses))
            .filter(Project.created_at >= cutoff)
            .order_by(Project.created_at.desc())
            .limit(50)
            .all()
        )
        if fixed_price_only:
            # Include type_id=1 (fixed) and type_id=None (unknown, likely fixed
            # since hourly projects are filtered out during API fetch)
            pending = [p for p in pending if getattr(p, "type_id", None) in (1, None)]

        if not pending:
            logger.info("No unscored projects found")
            return 0

        scoring_service = get_scoring_service()
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
    from database.models import Project, Bid

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
            .filter(Project.created_at >= cutoff)
            .filter(~Project.freelancer_id.in_(already_bid_subq))
        )
        if fixed_price_only:
            query = query.filter(or_(Project.type_id == 1, Project.type_id.is_(None)))

        candidates = (
            query.order_by(Project.ai_score.desc())
            .limit(max_candidates)
            .all()
        )

        # Detach-safe: convert to dicts with needed fields
        result = []
        for p in candidates:
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
        days = max(2, round(hours / 6))
        return min(days, 30)
    return 7  # default 7 days


async def _step_auto_bid(
    candidates: List[Dict[str, Any]],
    dry_run: bool,
    logger: logging.Logger,
) -> List[Dict[str, Any]]:
    """Execute bids on candidate projects. Returns list of bid results."""
    from database.models import Project
    from services import bid_service
    from services.freelancer_client import FreelancerAPIError

    bid_results: List[Dict[str, Any]] = []

    for i, candidate in enumerate(candidates):
        # 投标间短延迟（proposal 生成本身已有数秒延迟）
        if i > 0:
            _human_delay(1.0, 2.0)

        pid = candidate["freelancer_id"]
        amount = _determine_bid_amount(candidate)
        if amount is None:
            logger.warning("Cannot determine bid amount for project %s, skipping", pid)
            continue
        currency = candidate.get("currency_code") or "USD"

        period = _determine_bid_period(candidate)

        if dry_run:
            logger.info(
                "[DRY RUN] Would bid on project %s: %.2f %s, %d days (score=%.1f)",
                pid, amount, currency, period, candidate.get("ai_score", 0),
            )
            bid_results.append({
                "project_id": pid,
                "amount": amount,
                "currency": currency,
                "period": period,
                "status": "dry_run",
                "title": candidate.get("title", ""),
            })
            continue

        with common.get_db_context() as db:
            try:
                result = await bid_service.create_bid(
                    db,
                    project_id=pid,
                    amount=amount,
                    period=period,
                    description=None,  # Let ProposalService generate
                    validate_remote_status=True,
                )
                submitted_amount = float(result.get("amount", amount)) if isinstance(result, dict) else float(amount)
                # Mark project as bid_submitted
                project = db.query(Project).filter_by(freelancer_id=pid).first()
                if project:
                    project.status = "bid_submitted"
                    db.commit()

                logger.info(
                    "✅ Bid submitted: project=%s amount=%.2f %s period=%d",
                    pid, submitted_amount, currency, period,
                )
                bid_results.append({
                    "project_id": pid,
                    "amount": submitted_amount,
                    "currency": currency,
                    "period": period,
                    "status": "submitted",
                    "title": candidate.get("title", ""),
                })
            except FreelancerAPIError as exc:
                error_text = str(exc.message or "")
                logger.error("Bid API error for project %s: %s", pid, error_text)
                # Mark unbiddable projects to exclude from future cycles
                block_status = None
                if "SKILLS_REQUIREMENT_NOT_MET" in error_text:
                    block_status = "skills_blocked"
                elif "UNLISTED_NOT_PREFERRED" in error_text:
                    block_status = "preferred_only"
                elif "ESCROWCOM_ACCOUNT_UNLINKED" in error_text:
                    block_status = "escrow_required"
                if block_status:
                    try:
                        project = db.query(Project).filter_by(freelancer_id=pid).first()
                        if project:
                            project.status = block_status
                            db.commit()
                            logger.info("Marked project %s as '%s'", pid, block_status)
                    except Exception:
                        db.rollback()
                bid_results.append({
                    "project_id": pid,
                    "status": "error",
                    "error": error_text,
                })
            except Exception as exc:
                error_str = str(exc)
                logger.error("Bid error for project %s: %s", pid, exc)
                # Mark permanently unbiddable projects to prevent retry loops
                permanent_block = None
                if "Object doesn't exist" in error_str or "Project not found" in error_str:
                    permanent_block = "not_found"
                elif "not biddable now" in error_str:
                    permanent_block = "not_biddable"
                elif "outside the absolute allowed range" in error_str:
                    permanent_block = "amount_out_of_range"
                if permanent_block:
                    try:
                        project = db.query(Project).filter_by(freelancer_id=pid).first()
                        if project:
                            project.status = permanent_block
                            db.commit()
                            logger.info("Marked project %s as '%s'", pid, permanent_block)
                    except Exception:
                        db.rollback()
                bid_results.append({
                    "project_id": pid,
                    "status": "error",
                    "error": error_str,
                })

    return bid_results


def _send_telegram_notification(
    bid_results: List[Dict[str, Any]],
    logger: logging.Logger,
) -> None:
    """Send Telegram notification for submitted bids."""
    import requests

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        logger.debug("Telegram not configured, skipping notification")
        return

    submitted = [r for r in bid_results if r.get("status") == "submitted"]
    if not submitted:
        return

    lines = [f"🤖 *自动投标通知* ({len(submitted)} 个项目)\n"]
    for r in submitted:
        lines.append(
            f"• *{r.get('title', '')[:50]}*\n"
            f"  💰 {r['amount']:.0f} {r.get('currency', 'USD')} | ⏱ {r['period']}d\n"
            f"  🔗 https://www.freelancer.com/projects/{r['project_id']}\n"
        )

    text = "\n".join(lines)
    if len(text) > 4096:
        text = text[:4090] + "\n..."

    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        request_kwargs: Dict[str, Any] = {
            "json": {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            },
            "timeout": 15,
        }
        proxies = _build_telegram_proxies()
        if proxies:
            request_kwargs["proxies"] = proxies
        resp = requests.post(url, **request_kwargs)
        if resp.status_code == 200:
            logger.info("Telegram notification sent for %d bids", len(submitted))
        else:
            logger.warning("Telegram API returned %d", resp.status_code)
    except Exception as exc:
        logger.warning("Failed to send Telegram notification: %s", exc)


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

async def run_cycle(
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
    fetched_ids = await _step_fetch(
        keywords, limit, since_days, allowed_statuses, fixed_price_only, logger,
    )
    summary["fetched_projects"] = len(fetched_ids)

    # Step 2: Fetch competitor bids
    logger.info("── Step 2/4: Fetching competitor bids ──")
    comp_bids = await _step_fetch_competitor_bids(
        since_days, allowed_statuses, fixed_price_only, concurrency=10, logger=logger,
    )
    summary["competitor_bids_fetched"] = comp_bids

    # Step 3: Score unscored projects
    logger.info("── Step 3/4: Scoring projects ──")
    scored = await _step_score(
        since_days, allowed_statuses, fixed_price_only, batch_size=5, logger=logger,
    )
    summary["projects_scored"] = scored

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

        # Telegram 人工确认环节（可选）
        if confirm_enabled:
            bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
            chat_id = os.getenv("TELEGRAM_CHAT_ID")
            if bot_token and chat_id:
                from telegram_confirm import TelegramConfirm

                confirmer = TelegramConfirm(bot_token, chat_id, confirm_timeout)
                try:
                    msg_id = confirmer.send_candidates(candidates)
                    candidates = confirmer.wait_for_decisions(msg_id, candidates)
                except Exception as exc:
                    logger.error("Telegram confirmation failed: %s", exc)
                    candidates = []  # 安全默认：不投标

                if not candidates:
                    logger.info("No candidates approved, skipping bid")
                    summary["bids_submitted"] = 0
                    summary["bids_failed"] = 0
                    summary["confirm_result"] = "none_approved"
                    _attach_weekly_report()
                    return summary
                summary["confirm_result"] = f"{len(candidates)}_approved"
            else:
                logger.warning(
                    "--confirm enabled but TELEGRAM_BOT_TOKEN/CHAT_ID not set, "
                    "proceeding without confirmation"
                )

        bid_results = await _step_auto_bid(candidates, dry_run, logger)
        summary["bids_submitted"] = sum(
            1 for r in bid_results if r.get("status") in ("submitted", "dry_run")
        )
        summary["bids_failed"] = sum(
            1 for r in bid_results if r.get("status") == "error"
        )

        # 非确认模式下发送 Telegram 通知（确认模式下用户已知晓）
        if not dry_run and not confirm_enabled:
            _send_telegram_notification(bid_results, logger)
    else:
        logger.info("No qualifying candidates found (threshold=%.1f)", bid_threshold)
        summary["bids_submitted"] = 0
        summary["bids_failed"] = 0

    _attach_weekly_report()
    elapsed = time.monotonic() - cycle_start
    summary["elapsed_seconds"] = round(elapsed, 1)
    return summary


async def _morning_batch_bid(
    candidates: List[Dict[str, Any]],
    dry_run: bool,
    confirm_timeout: int,
    logger: logging.Logger,
    auto_approve: bool = True,
) -> Dict[str, Any]:
    """8:00 起床批次：将夜间积累的候选推送 Telegram 确认，等待用户决策后投标。"""
    summary: Dict[str, Any] = {}
    if not candidates:
        logger.info("Morning batch: no night candidates to process")
        summary["bids_submitted"] = 0
        return summary

    logger.info("🌅 Morning batch: %d candidates accumulated overnight", len(candidates))

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if bot_token and chat_id:
        try:
            from telegram_confirm import TelegramConfirm

            confirmer = TelegramConfirm(bot_token, chat_id, confirm_timeout)
            msg_id = confirmer.send_candidates(candidates)
            if not auto_approve:
                candidates = confirmer.wait_for_decisions(msg_id, candidates)
            logger.info(
                "Morning batch: %d/%d candidates approved via Telegram",
                len(candidates), len(candidates),
            )
        except Exception as exc:
            logger.error(
                "Morning batch Telegram confirmation failed: %s", exc,
            )
            candidates = []  # 安全默认：不投标
    else:
        logger.warning(
            "Morning batch: Telegram not configured, proceeding without confirmation",
        )

    if not candidates:
        logger.info("Morning batch: no candidates approved, skipping bid")
        summary["bids_submitted"] = 0
        summary["bids_failed"] = 0
        return summary

    logger.info("Morning batch: bidding on %d approved candidates...", len(candidates))
    bid_results = await _step_auto_bid(candidates, dry_run, logger)
    summary["bids_submitted"] = sum(
        1 for r in bid_results if r.get("status") in ("submitted", "dry_run")
    )
    summary["bids_failed"] = sum(
        1 for r in bid_results if r.get("status") == "error"
    )
    return summary


# ============================================================================
# Entry point
# ============================================================================

def main(argv=None) -> int:
    global _night_candidates

    parser = argparse.ArgumentParser(
        description="Automated pipeline scheduler: fetch → score → bid.",
    )
    parser.add_argument(
        "--interval", type=int, default=3,
        help="Base minutes between cycles (default: 3, actual 3-6 with jitter)",
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
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview mode: no real bids submitted",
    )
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
        help="Enable Telegram manual confirmation before bidding (default: off)",
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

    _promote_telegram_proxy_env(logger)

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

    cycle_count = 0
    was_night = False  # 追踪上一个 cycle 是否为夜间

    while not _shutdown:
        cycle_count += 1
        current_hour = _get_local_hour(tz_name)
        night_mode = (
            not args.no_night_mode
            and _is_night(current_hour, args.night_start, args.night_end)
        )

        # 夜间即时竞标模式：夜间仍然竞标，只是降低频率
        night_skip_bid = night_mode and not args.night_instant_bid

        # ── 夜间 → 白天切换：触发 8:00 起床批次（仅在积累模式下生效） ──
        if was_night and not night_mode and _night_candidates and not args.night_instant_bid:
            logger.info(
                "🌅 Night→Day transition at %02d:00, processing %d accumulated candidates",
                current_hour, len(_night_candidates),
            )
            try:
                batch_summary = asyncio.run(_morning_batch_bid(
                    candidates=_night_candidates,
                    dry_run=args.dry_run,
                    confirm_timeout=args.confirm_timeout,
                    logger=logger,
                ))
                logger.info(
                    "🌅 Morning batch done: %d bids submitted",
                    batch_summary.get("bids_submitted", 0),
                )
            except Exception as exc:
                logger.error("Morning batch failed: %s", exc, exc_info=True)
            _night_candidates = []

        was_night = night_mode
        mode_tag = "🌙 NIGHT" if night_mode else "☀️ DAY"
        logger.info(
            "═══ Cycle %d [%s] started at %s (local %02d:00) ═══",
            cycle_count, mode_tag, datetime.utcnow().isoformat(), current_hour,
        )

        try:
            summary = asyncio.run(run_cycle(
                keywords=keywords,
                limit=args.limit,
                since_days=args.since_days,
                allowed_statuses=allowed_statuses,
                bid_threshold=args.bid_threshold,
                max_bids_per_cycle=args.max_bids_per_cycle,
                dry_run=args.dry_run,
                fixed_price_only=fixed_price_only,
                logger=logger,
                confirm_enabled=args.confirm and not night_mode,
                confirm_timeout=args.confirm_timeout,
                skip_bid=night_skip_bid,
                weekly_report_enabled=args.weekly_report,
                weekly_report_since_days=args.weekly_report_since_days,
                weekly_report_output=args.weekly_report_output,
                weekly_report_sync_awards=args.weekly_report_sync_awards,
            ))

            # 夜间模式：仅在积累模式下积累候选
            if night_skip_bid:
                new_candidates = summary.get("night_candidates", [])
                if new_candidates:
                    _night_candidates = _dedup_candidates(_night_candidates, new_candidates)
                    logger.info(
                        "🌙 Night: +%d candidates this cycle, %d total accumulated",
                        len(new_candidates), len(_night_candidates),
                    )

            logger.info(
                "═══ Cycle %d completed: fetched=%d scored=%d candidates=%d bids=%d (%.1fs) ═══",
                cycle_count,
                summary.get("fetched_projects", 0),
                summary.get("projects_scored", 0),
                summary.get("bid_candidates", 0),
                summary.get("bids_submitted", 0),
                summary.get("elapsed_seconds", 0),
            )
            print(
                f"[Cycle {cycle_count} {mode_tag}] "
                f"fetched={summary.get('fetched_projects', 0)} "
                f"scored={summary.get('projects_scored', 0)} "
                f"candidates={summary.get('bid_candidates', 0)} "
                f"bids={summary.get('bids_submitted', 0)} "
                f"({summary.get('elapsed_seconds', 0):.1f}s)"
            )
        except Exception as exc:
            logger.error("Cycle %d failed: %s", cycle_count, exc, exc_info=True)
            print(f"[Cycle {cycle_count}] ERROR: {exc}")

        if args.once:
            break

        # ── 计算下次间隔 ──
        if night_mode:
            # 夜间：较长间隔 (8-12 min)，降低频率但不错过新项目
            base_seconds = 10 * 60
            jitter = random.uniform(-0.2, 0.2) * base_seconds
        else:
            # 白天：5-10 min 随机间隔
            base_seconds = args.interval * 60
            jitter = random.uniform(0, 1.0) * base_seconds  # interval ~ 2*interval

        sleep_seconds = max(60, int(base_seconds + jitter))
        logger.info("Sleeping %d seconds until next cycle...", sleep_seconds)
        for _ in range(sleep_seconds):
            if _shutdown:
                break
            time.sleep(1)

    logger.info("Scheduler stopped after %d cycles", cycle_count)
    print(f"Scheduler stopped after {cycle_count} cycles.")
    return common.EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
