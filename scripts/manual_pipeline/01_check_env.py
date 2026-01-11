#!/usr/bin/env python3
"""
Environment and connection verification script.
"""
import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

from sqlalchemy import text

script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))

import common
from services.freelancer_client import FreelancerAPIError, get_freelancer_client


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check environment, API, and database connections.")
    parser.add_argument("--lock-file", default=str(common.DEFAULT_LOCK_FILE), help="Lock file path")
    args = parser.parse_args(argv)

    logger = common.setup_logging("manual_check_env")

    with common.file_lock(Path(args.lock_file), blocking=False) as acquired:
        if not acquired:
            print("Lock busy. Another workflow may be running.")
            return common.EXIT_LOCK_ERROR

        try:
            env_file = common.load_env()
        except FileNotFoundError as exc:
            print(f"Missing env file: {exc}")
            return common.EXIT_VALIDATION_ERROR

        env = dict(os.environ)
        required = [
            "FREELANCER_OAUTH_TOKEN",
            "FREELANCER_USER_ID",
            "PYTHON_API_KEY",
            "DATABASE_PATH",
            "LLM_PROVIDER",
            "LLM_MODEL",
        ]
        validators = {"FREELANCER_USER_ID": lambda v: str(v).isdigit()}

        provider = env.get("LLM_PROVIDER", "openai")
        if provider == "openai":
            required.append("LLM_API_KEY")

        ok, missing, invalid = common.validate_env(env, required, validators)
        if not ok:
            if missing:
                print(f"Missing env vars: {', '.join(missing)}")
            if invalid:
                print(f"Invalid env vars: {', '.join(invalid)}")
            return common.EXIT_VALIDATION_ERROR

        try:
            settings = common.get_settings()
        except Exception as exc:
            print(f"Failed to load settings: {exc}")
            return common.EXIT_VALIDATION_ERROR

        logger.info(f"Loaded env file: {env_file}")
        logger.info(f"LLM Provider: {settings.LLM_PROVIDER}")
        logger.info(f"DB Path: {settings.DATABASE_PATH}")

        try:
            start = time.monotonic()
            client = get_freelancer_client()
            asyncio.run(client.search_projects(query="python", limit=1))
            latency_ms = int((time.monotonic() - start) * 1000)
        except FreelancerAPIError as exc:
            print(f"Freelancer API error: {exc.message}")
            return common.EXIT_API_ERROR
        except Exception as exc:
            print(f"Freelancer API error: {exc}")
            return common.EXIT_API_ERROR

        try:
            with common.get_db_context() as db:
                db.execute(text("SELECT 1"))
                db.execute(text("CREATE TEMP TABLE IF NOT EXISTS manual_pipeline_write_test (id INTEGER)"))
                db.execute(text("INSERT INTO manual_pipeline_write_test (id) VALUES (1)"))
        except Exception as exc:
            print(f"Database error: {exc}")
            return common.EXIT_DB_ERROR

        print(f"Environment OK. API Latency: {latency_ms}ms")

        # Refresh currency rates
        try:
            from utils.currency_converter import get_currency_converter
            converter = get_currency_converter()
            if not converter.is_cache_valid():
                print("Currency rates cache expired, refreshing from API...")
                asyncio.run(converter.update_rates())
                print(f"Updated {len(converter.rates)} currency rates.")
            else:
                print("Currency rates cache is still valid.")
        except Exception as exc:
            print(f"Failed to refresh currency rates: {exc}")
            # Non-critical, continue

        return common.EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
