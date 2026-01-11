#!/usr/bin/env python3
"""
Interactive bid submission script.
"""
import argparse
import asyncio
import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))

import common
from database.models import Project
from services import bid_service
from services.freelancer_client import FreelancerAPIError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Submit a bid for a project.")
    parser.add_argument("--project-id", type=int, help="Freelancer project ID")
    parser.add_argument("--amount", type=float, help="Bid amount")
    parser.add_argument("--period", type=int, default=7, help="Delivery period in days")
    parser.add_argument("--proposal", type=str, help="Proposal text (defaults to AI draft)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without submitting")
    parser.add_argument("--lock-file", default=str(common.DEFAULT_LOCK_FILE), help="Lock file path")
    args = parser.parse_args(argv)

    logger = common.setup_logging("manual_bid")

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

        project_id = args.project_id
        if project_id is None:
            raw = input("Project ID: ").strip()
            if not raw:
                print("Missing project ID.")
                return common.EXIT_VALIDATION_ERROR
            try:
                project_id = int(raw)
            except ValueError:
                print("Invalid project ID.")
                return common.EXIT_VALIDATION_ERROR

        with common.get_db_context() as db:
            project = db.query(Project).filter(Project.freelancer_id == project_id).first()
            if not project:
                print(f"Project {project_id} not found in DB.")
                return common.EXIT_VALIDATION_ERROR

            if project.status == "bid_submitted":
                print(f"Project {project_id} already marked as bid_submitted.")
                return common.EXIT_SUCCESS

            amount = args.amount
            if amount is None:
                if project.suggested_bid is not None:
                    amount = float(project.suggested_bid)
                elif project.budget_maximum:
                    amount = float(project.budget_maximum)
                elif project.budget_minimum:
                    amount = float(project.budget_minimum)
                else:
                    raw_amount = input("Bid amount: ").strip()
                    if not raw_amount:
                        print("Missing bid amount.")
                        return common.EXIT_VALIDATION_ERROR
                    try:
                        amount = float(raw_amount)
                    except ValueError:
                        print("Invalid bid amount.")
                        return common.EXIT_VALIDATION_ERROR

            proposal = args.proposal or project.ai_proposal_draft
            if not proposal:
                proposal = input("Proposal text: ").strip()
            if not proposal:
                print("Missing proposal text.")
                return common.EXIT_VALIDATION_ERROR

            print("\nBid Preview")
            print("-" * 40)
            print(f"Project ID: {project.freelancer_id}")
            print(f"Title: {project.title}")
            print(f"Amount: {amount} {project.currency_code}")
            print(f"Period: {args.period} days")
            print("Proposal:")
            print(proposal)
            print("-" * 40)

            confirm = input("Submit bid? [y/N]: ").strip().lower()
            if confirm != "y":
                print("Cancelled.")
                return common.EXIT_SUCCESS

            if args.dry_run:
                print("[Dry Run] Bid not submitted.")
                return common.EXIT_SUCCESS

            try:
                asyncio.run(
                    bid_service.create_bid(
                        db,
                        project_id=project.freelancer_id,
                        amount=amount,
                        period=args.period,
                        description=proposal,
                    )
                )
                project.status = "bid_submitted"
                db.commit()
                print("Bid submitted.")
                return common.EXIT_SUCCESS
            except FreelancerAPIError as exc:
                logger.error(f"Bid API error: {exc.message}")
                print(f"Bid API error: {exc.message}")
                return common.EXIT_API_ERROR
            except Exception as exc:
                logger.error(f"Bid error: {exc}")
                print(f"Bid error: {exc}")
                return common.EXIT_API_ERROR


if __name__ == "__main__":
    sys.exit(main())
