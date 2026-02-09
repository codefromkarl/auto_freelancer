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
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import CompetitorBid, Project
from services.freelancer_client import FreelancerAPIError, get_freelancer_client

logger = logging.getLogger(__name__)

# Default concurrency for batch operations
_DEFAULT_CONCURRENCY = 5


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
                bidder_id=bid.get("bidder_id", 0),
                amount=amount,
                period=period,
                retracted=retracted,
                award_status=award_status,
                reputation=reputation,
            ))
        upserted += 1

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

    # Strategy: bid slightly below median, adjusted by skill match
    # High skill match -> bid closer to median (confidence premium)
    # Low skill match -> bid closer to p25 (competitive pricing)
    discount = 0.05 + (1.0 - our_skills_match) * 0.15  # 5%-20% below median
    suggested_amount = round(median * (1.0 - discount), 2)
    suggested_amount = max(suggested_amount, p25)  # Never go below p25

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
