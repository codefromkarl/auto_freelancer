#!/usr/bin/env python3
"""
Fetch projects from Freelancer API and store in database.
"""
import argparse
import asyncio
import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))

import common
from database.models import Project
from services import project_service
from services.freelancer_client import FreelancerAPIError


DEFAULT_KEYWORDS = [
    "python automation",
    "n8n",
    "fastapi",
    "web scraping",
    "api integration",
]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Fetch projects and store in database.")
    parser.add_argument("--keywords", default=",".join(DEFAULT_KEYWORDS), help="Comma-separated keywords")
    parser.add_argument("--limit", type=int, default=20, help="Max results per keyword")
    parser.add_argument("--lock-file", default=str(common.DEFAULT_LOCK_FILE), help="Lock file path")
    args = parser.parse_args(argv)

    logger = common.setup_logging("manual_fetch")

    with common.file_lock(Path(args.lock_file), blocking=False) as acquired:
        if not acquired:
            print("Lock busy. Another workflow may be running.")
            return common.EXIT_LOCK_ERROR

        try:
            common.load_env()
            common.get_settings()
        except Exception as exc:
            print(f"Failed to load settings: {exc}")
            return common.EXIT_VALIDATION_ERROR

        keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
        if not keywords:
            print("No keywords provided.")
            return common.EXIT_VALIDATION_ERROR

        total_fetched = 0
        new_ids: set[int] = set()
        errors = 0

        with common.get_db_context() as db:
            for keyword in keywords:
                try:
                    results = asyncio.run(
                        project_service.search_projects(
                            db=db,
                            query=keyword,
                            limit=args.limit,
                            offset=0,
                        )
                    )
                    total_fetched += len(results)
                    for item in results:
                        project_id = item.get("id")
                        if project_id is not None:
                            new_ids.add(int(project_id))
                except FreelancerAPIError as exc:
                    logger.error(f"API error for keyword '{keyword}': {exc.message}")
                    errors += 1
                except Exception as exc:
                    logger.error(f"Fetch error for keyword '{keyword}': {exc}")
                    errors += 1

            if new_ids:
                db.query(Project).filter(Project.freelancer_id.in_(list(new_ids))).update(
                    {Project.status: "fetched"},
                    synchronize_session=False,
                )
                db.commit()

        print(f"Fetched {total_fetched} projects. {len(new_ids)} new added to DB.")
        if errors:
            return common.EXIT_API_ERROR
        return common.EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
