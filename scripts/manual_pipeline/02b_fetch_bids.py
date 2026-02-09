#!/usr/bin/env python3
"""
Fetch competitor bids for recently fetched projects.

Runs after 02_fetch and before 03_score.
Only fetches bids for projects with bid_count > 0 to conserve API quota.
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func

script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))

import common
from database.models import Project
from services import competitor_bid_service


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch competitor bids for recent projects.",
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=common.DEFAULT_LOOKBACK_DAYS,
        help="Only process projects from recent N days",
    )
    parser.add_argument(
        "--allowed-statuses",
        default=",".join(common.DEFAULT_BIDDABLE_STATUSES),
        help="Comma-separated allowed statuses",
    )
    parser.add_argument(
        "--include-hourly",
        action="store_true",
        help="Include hourly projects (default: fixed-price only)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Max concurrent API requests",
    )
    parser.add_argument(
        "--lock-file",
        default=str(common.DEFAULT_LOCK_FILE),
        help="Lock file path",
    )
    args = parser.parse_args(argv)

    logger = common.setup_logging("manual_fetch_bids")

    with common.file_lock(Path(args.lock_file), blocking=False) as acquired:
        if not acquired:
            print("Lock busy. Another workflow may be running.")
            return common.EXIT_LOCK_ERROR

        if args.since_days <= 0:
            print("--since-days must be greater than 0.")
            return common.EXIT_VALIDATION_ERROR

        try:
            common.load_env()
            common.get_settings()
        except Exception as exc:
            print(f"Failed to load settings: {exc}")
            return common.EXIT_VALIDATION_ERROR

        allowed_statuses = common.parse_statuses(
            args.allowed_statuses,
            default=list(common.DEFAULT_BIDDABLE_STATUSES),
        )
        cutoff_time = datetime.utcnow() - timedelta(days=args.since_days)

        with common.get_db_context() as db:
            query = (
                db.query(Project)
                .filter(func.lower(Project.status).in_(allowed_statuses))
                .filter(Project.created_at >= cutoff_time)
            )
            if not args.include_hourly:
                query = query.filter(Project.type_id == 1)

            projects = query.all()

            # Filter to projects with bid_count > 0
            eligible = []
            for p in projects:
                bid_stats = {}
                if p.bid_stats:
                    try:
                        bid_stats = json.loads(p.bid_stats)
                    except (json.JSONDecodeError, TypeError):
                        pass
                if bid_stats.get("bid_count", 0) > 0:
                    eligible.append(p.freelancer_id)

            if not eligible:
                print("No projects with bids to fetch.")
                return common.EXIT_SUCCESS

            logger.info(
                "Fetching competitor bids for %d projects (concurrency=%d)",
                len(eligible),
                args.concurrency,
            )

            results = asyncio.run(
                competitor_bid_service.batch_fetch_bids(
                    db,
                    eligible,
                    concurrency=args.concurrency,
                )
            )

            total_bids = sum(results.values())
            print(
                f"Fetched competitor bids for {len(eligible)} projects, "
                f"total {total_bids} bids stored."
            )

    return common.EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
