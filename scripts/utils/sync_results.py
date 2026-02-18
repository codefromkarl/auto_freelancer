import asyncio
import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON_SERVICE_ROOT = REPO_ROOT / "python_service"
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from database.connection import SessionLocal
from database.models import CompetitorBid
from services.competitor_bid_service import sync_bids_for_our_projects

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sync_results")

async def sync_awarded_results(since_days: int | None = None, concurrency: int = 5):
    """
    Sync final results for projects you bid on.
    Check who won and at what price.
    """
    session = SessionLocal()

    try:
        synced = await sync_bids_for_our_projects(
            session,
            since_days=since_days,
            concurrency=concurrency,
        )
        logger.info(
            "Synced competitor bids for %d bidded projects (since_days=%s)",
            len(synced),
            since_days,
        )

        for project_id in sorted(synced.keys()):
            winner = session.query(CompetitorBid).filter(
                CompetitorBid.project_freelancer_id == project_id,
                CompetitorBid.award_status == 'awarded'
            ).first()
            if winner:
                logger.info(
                    "🏆 Found winner for %s: bidder=%s amount=%s rep=%s",
                    project_id,
                    winner.bidder_id,
                    winner.amount,
                    winner.reputation,
                )
            else:
                logger.info("No winner found yet for %s", project_id)
    finally:
        session.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Sync awarded results for bidded projects."
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=None,
        help="Only sync projects that were bidded within N days (default: all).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Max concurrent project bid sync requests.",
    )
    args = parser.parse_args()
    asyncio.run(sync_awarded_results(since_days=args.since_days, concurrency=args.concurrency))
