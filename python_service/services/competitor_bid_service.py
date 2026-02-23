"""
Competitor bid fetching, storage, and analysis service.

Provides functions to:
- Fetch competitor bids from Freelancer API and persist via upsert
- Batch-fetch with concurrency control
- Analyze competition (amount/period/reputation distributions)
- Suggest optimal bid amount and period
"""
from __future__ import annotations

import asyncio
import logging
import statistics
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from database.models import Bid, CompetitorBid, CompetitorBidContent, Project
from services.freelancer_client import FreelancerAPIError, get_freelancer_client

logger = logging.getLogger(__name__)

# Default concurrency for batch operations
_DEFAULT_CONCURRENCY = 10


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

def _ensure_competitor_bid_content_table(db: Session) -> None:
    """Create competitor_bid_contents table/indexes if they do not exist."""
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS competitor_bid_contents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bid_id INTEGER NOT NULL UNIQUE,
                project_id INTEGER NOT NULL,
                project_freelancer_id INTEGER NOT NULL,
                bidder_id INTEGER NOT NULL,
                description TEXT NOT NULL,
                fetched_at DATETIME
            )
            """
        )
    )
    db.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_competitor_bid_content_project "
            "ON competitor_bid_contents(project_freelancer_id)"
        )
    )
    db.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_competitor_bid_content_bidder "
            "ON competitor_bid_contents(bidder_id)"
        )
    )
    db.flush()


def _extract_bid_description(bid: Dict[str, Any]) -> Optional[str]:
    """Extract proposal text from varying API payload shapes."""
    for key in ("description", "bid_description", "proposal", "comment", "cover_letter"):
        value = bid.get(key)
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                return normalized
    return None


# ---------------------------------------------------------------------------
# Fetch & persist
# ---------------------------------------------------------------------------

async def fetch_and_save_bids(
    db: Session,
    project_freelancer_id: int,
) -> int:
    """Fetch competitor bids for a single project and upsert into DB.

    Returns:
        Number of bids upserted.
    """
    # Resolve internal project row
    project = (
        db.query(Project)
        .filter(Project.freelancer_id == project_freelancer_id)
        .first()
    )
    if project is None:
        logger.warning(
            "Project %s not found in DB, skipping bid fetch",
            project_freelancer_id,
        )
        return 0

    client = get_freelancer_client()
    try:
        raw_bids = await client.get_project_bids(project_freelancer_id)
    except FreelancerAPIError as exc:
        logger.error(
            "Failed to fetch bids for project %s: %s",
            project_freelancer_id,
            exc.message,
        )
        return 0

    _ensure_competitor_bid_content_table(db)
    upserted = 0
    for bid in raw_bids:
        bid_id = bid.get("id")
        if bid_id is None:
            continue

        existing = (
            db.query(CompetitorBid)
            .filter(CompetitorBid.bid_id == bid_id)
            .first()
        )

        amount = bid.get("amount")
        period = bid.get("period")
        retracted = bid.get("retracted", False)
        award_status = bid.get("award_status", "pending")
        reputation = bid.get("reputation")
        description = _extract_bid_description(bid)
        bidder_id = bid.get("bidder_id", 0)

        if existing:
            existing.amount = amount
            existing.period = period
            existing.retracted = retracted
            existing.award_status = award_status
            existing.reputation = reputation
        else:
            db.add(CompetitorBid(
                bid_id=bid_id,
                project_id=project.id,
                project_freelancer_id=project_freelancer_id,
                bidder_id=bidder_id,
                amount=amount,
                period=period,
                retracted=retracted,
                award_status=award_status,
                reputation=reputation,
            ))

        if description:
            content = (
                db.query(CompetitorBidContent)
                .filter(CompetitorBidContent.bid_id == bid_id)
                .first()
            )
            if content:
                content.bidder_id = bidder_id
                content.description = description
                content.fetched_at = datetime.utcnow()
            else:
                db.add(
                    CompetitorBidContent(
                        bid_id=bid_id,
                        project_id=project.id,
                        project_freelancer_id=project_freelancer_id,
                        bidder_id=bidder_id,
                        description=description,
                        fetched_at=datetime.utcnow(),
                    )
                )
        upserted += 1

    # 标记拉取时间，供增量策略使用
    if project is not None:
        project.competitor_bids_fetched_at = datetime.utcnow()
    db.commit()
    logger.info(
        "Upserted %d competitor bids for project %s",
        upserted,
        project_freelancer_id,
    )
    return upserted


async def batch_fetch_bids(
    db: Session,
    project_freelancer_ids: List[int],
    concurrency: int = _DEFAULT_CONCURRENCY,
) -> Dict[int, int]:
    """Batch-fetch competitor bids with semaphore-based concurrency control.

    Returns:
        Mapping of project_freelancer_id -> number of bids upserted.
    """
    sem = asyncio.Semaphore(concurrency)
    results: Dict[int, int] = {}

    async def _fetch_one(pid: int) -> None:
        async with sem:
            count = await fetch_and_save_bids(db, pid)
            results[pid] = count

    tasks = [_fetch_one(pid) for pid in project_freelancer_ids]
    await asyncio.gather(*tasks, return_exceptions=True)

    total = sum(results.values())
    logger.info(
        "Batch fetched bids for %d projects, total %d bids",
        len(project_freelancer_ids),
        total,
    )
    return results


# ---------------------------------------------------------------------------
# Sync by our bids
# ---------------------------------------------------------------------------

def get_bidded_project_ids(
    db: Session,
    since_days: Optional[int] = None,
) -> List[int]:
    """
    Return distinct project_freelancer_id values that we have bid on.
    """
    query = db.query(Bid.project_freelancer_id).distinct()
    if since_days is not None and since_days > 0:
        cutoff = datetime.utcnow() - timedelta(days=since_days)
        query = query.filter(Bid.created_at >= cutoff)
    rows = query.all()
    return [int(row[0]) for row in rows if row and row[0] is not None]


async def sync_bids_for_our_projects(
    db: Session,
    since_days: Optional[int] = None,
    concurrency: int = _DEFAULT_CONCURRENCY,
) -> Dict[int, int]:
    """
    Sync competitor bids for all projects that we have already bid on.
    """
    project_ids = get_bidded_project_ids(db, since_days=since_days)
    if not project_ids:
        logger.info("No bidded projects found for competitor sync")
        return {}

    logger.info(
        "Syncing competitor bids for %d bidded projects (since_days=%s)",
        len(project_ids),
        since_days,
    )
    return await batch_fetch_bids(db, project_ids, concurrency=concurrency)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyze_competition(
    db: Session,
    project_freelancer_id: int,
) -> Optional[Dict[str, Any]]:
    """Analyze competitor bids for a project.

    Returns:
        Analysis dict or None if no competitor data exists.
    """
    bids = (
        db.query(CompetitorBid)
        .filter(CompetitorBid.project_freelancer_id == project_freelancer_id)
        .all()
    )
    if not bids:
        return None

    total = len(bids)
    active_bids = [b for b in bids if not b.retracted]
    active_count = len(active_bids)

    # Amount statistics (active bids only)
    amounts = [
        float(b.amount) for b in active_bids
        if b.amount is not None and float(b.amount) > 0
    ]
    amount_stats = _compute_stats(amounts)

    # Period statistics
    periods = [b.period for b in active_bids if b.period is not None and b.period > 0]
    period_stats = _compute_stats(periods)

    # Reputation statistics
    reps = [b.reputation for b in active_bids if b.reputation is not None]
    rep_avg = round(statistics.mean(reps), 2) if reps else None
    top_bidders = sum(1 for r in reps if r >= 4.8)

    return {
        "total_bids": total,
        "active_bids": active_count,
        "amount": amount_stats,
        "period": period_stats,
        "reputation": {"avg": rep_avg, "top_bidders": top_bidders},
    }


def get_bid_suggestion(
    db: Session,
    project_freelancer_id: int,
    our_skills_match: float = 0.5,
) -> Optional[Dict[str, Any]]:
    """Suggest optimal bid amount and period based on competition analysis.

    Args:
        db: Database session
        project_freelancer_id: Freelancer project ID
        our_skills_match: 0.0-1.0 indicating how well our skills match

    Returns:
        Suggestion dict or None if insufficient data.
    """
    analysis = analyze_competition(db, project_freelancer_id)
    if analysis is None or not analysis["amount"]:
        return None

    amt = analysis["amount"]
    median = amt.get("median", 0)
    p25 = amt.get("p25", 0)

    # Strategy: bid below median, adjusted by skill match
    # High skill match -> bid closer to median (confidence premium)
    # Low skill match -> bid more aggressively below median
    # Newcomer-optimized: 10%-25% below median for better ranking
    discount = 0.10 + (1.0 - our_skills_match) * 0.15  # 10%-25% below median
    suggested_amount = round(median * (1.0 - discount), 2)
    # Allow going below p25 for newcomers: use min(p25, median*0.75) as floor
    floor = min(p25, median * 0.75) if median > 0 else p25
    suggested_amount = max(suggested_amount, floor)

    # Period: use median period
    period_stats = analysis.get("period", {})
    suggested_period = period_stats.get("median") or period_stats.get("avg") or 7

    return {
        **analysis,
        "suggested_amount": suggested_amount,
        "suggested_period": int(suggested_period),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_stats(values: List[float]) -> Dict[str, Any]:
    """Compute min/max/avg/median/p25/p75 for a list of numeric values."""
    if not values:
        return {}
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    return {
        "min": round(sorted_vals[0], 2),
        "max": round(sorted_vals[-1], 2),
        "avg": round(statistics.mean(sorted_vals), 2),
        "median": round(statistics.median(sorted_vals), 2),
        "p25": round(sorted_vals[max(0, n // 4 - 1)], 2) if n >= 4 else round(sorted_vals[0], 2),
        "p75": round(sorted_vals[min(n - 1, 3 * n // 4)], 2) if n >= 4 else round(sorted_vals[-1], 2),
    }
