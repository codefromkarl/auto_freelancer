#!/usr/bin/env python3
"""
Concurrent AI scoring for fetched projects with multiple LLM providers.
"""
import argparse
import asyncio
import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))

import common
from database.models import Project
from services.llm_scoring_service import get_scoring_service


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Score projects with LLM (concurrent).")
    parser.add_argument("--batch-size", type=int, default=5, help="Concurrent batch size")
    parser.add_argument("--limit", type=int, default=50, help="Max projects to score")
    parser.add_argument("--max-retries", type=int, default=2, help="Retry attempts per project")
    parser.add_argument("--lock-file", default=str(common.DEFAULT_LOCK_FILE), help="Lock file path")
    args = parser.parse_args(argv)

    logger = common.setup_logging("manual_score_concurrent")

    with common.file_lock(Path(args.lock_file), blocking=False) as acquired:
        if not acquired:
            print("Lock busy. Another workflow may be running.")
            return common.EXIT_LOCK_ERROR

        try:
            common.load_env()
            settings = common.get_settings()
        except Exception as exc:
            print(f"Failed to load settings: {exc}")
            return common.EXIT_VALIDATION_ERROR

        # Get enabled LLM providers
        from config import settings as config_settings
        providers = config_settings.get_enabled_llm_providers()

        if not providers:
            print("No enabled LLM providers found. Please configure at least one provider in .env")
            print("Available providers: OPENAI_ENABLED, ZHIPU_ENABLED, ANTHROPIC_ENABLED, DEEPSEEK_ENABLED")
            return common.EXIT_VALIDATION_ERROR

        print(f"Using {len(providers)} LLM provider(s): {[p['name'] for p in providers]}")

        with common.get_db_context() as db:
            # Get pending projects (not scored yet)
            pending = (
                db.query(Project)
                .filter(Project.ai_score.is_(None))
                .order_by(Project.created_at.desc())
                .limit(args.limit)
                .all()
            )

            if not pending:
                print("Scored 0 projects. No un-scored projects found.")
                return common.EXIT_SUCCESS

            print(f"Found {len(pending)} projects to score...")

            # Use concurrent scoring service
            scoring_service = get_scoring_service()

            async def run_scoring():
                total_scored, errors, top_score, top_id = await scoring_service.score_projects_concurrent(
                    projects=pending,
                    db=db,
                    batch_size=args.batch_size,
                    max_retries=args.max_retries
                )
                return total_scored, errors, top_score, top_id

            total_scored, errors, top_score, top_id = asyncio.run(run_scoring())

            top_label = top_id if top_id is not None else "N/A"
            print(f"\n{'='*60}")
            print(f"Scored {total_scored} projects successfully.")
            print(f"Errors: {errors}")
            print(f"Top Score: {top_score:.1f} (Project ID: {top_label})")
            print(f"{'='*60}")

            return common.EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
