#!/usr/bin/env python3
"""
Review high-scoring projects and generate a report.
"""
import argparse
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta

from sqlalchemy import func

script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))

import common
from database.models import Project
from services import bid_service
from services import competitor_bid_service


async def _refresh_remote_status_and_filter(db, projects, logger):
    """
    Refresh project status from remote API and filter out unbiddable projects.
    """
    kept = []
    filtered = 0

    for project in projects:
        try:
            is_biddable, reason = await bid_service.validate_project_biddable_now(db, project)
        except Exception as exc:
            is_biddable, reason = False, f"remote_status_check_failed: {exc}"

        if is_biddable:
            kept.append(project)
            continue

        filtered += 1
        logger.info(
            "Filtered project after remote status refresh. project_id=%s reason=%s",
            project.freelancer_id,
            reason,
        )

    return kept, filtered


def main(argv=None) -> int:
    default_report = Path(__file__).resolve().parents[2] / "review_report.txt"

    parser = argparse.ArgumentParser(description="Review projects above a score threshold.")
    parser.add_argument("--threshold", type=float, default=7.0, help="Minimum score threshold")
    parser.add_argument(
        "--since-days",
        type=int,
        default=common.DEFAULT_LOOKBACK_DAYS,
        help="Only review projects from recent N days",
    )
    parser.add_argument(
        "--allowed-statuses",
        default=",".join(common.DEFAULT_BIDDABLE_STATUSES),
        help="Comma-separated allowed statuses",
    )
    parser.add_argument(
        "--include-hourly",
        action="store_true",
        help="Include hourly projects in review (default: fixed-price only)",
    )
    parser.add_argument("--output", default=str(default_report), help="Report output file")
    parser.add_argument("--lock-file", default=str(common.DEFAULT_LOCK_FILE), help="Lock file path")
    args = parser.parse_args(argv)

    logger = common.setup_logging("manual_review")

    with common.file_lock(Path(args.lock_file), blocking=False) as acquired:
        if not acquired:
            print("Lock busy. Another workflow may be running.")
            return common.EXIT_LOCK_ERROR

        if args.since_days <= 0:
            print("--since-days must be greater than 0.")
            return common.EXIT_VALIDATION_ERROR

        allowed_statuses = common.parse_statuses(
            args.allowed_statuses,
            default=list(common.DEFAULT_BIDDABLE_STATUSES),
        )
        cutoff_time = datetime.utcnow() - timedelta(days=args.since_days)

        with common.get_db_context() as db:
            projects = (
                db.query(Project)
                .filter(Project.ai_score >= args.threshold)
                .filter(func.lower(Project.status).in_(allowed_statuses))
                .filter(Project.created_at >= cutoff_time)
                .order_by(Project.ai_score.desc())
                .all()
            )
            if not args.include_hourly:
                projects = [p for p in projects if getattr(p, "type_id", None) == 1]
            projects, remote_filtered = asyncio.run(
                _refresh_remote_status_and_filter(db, projects, logger)
            )

            headers = ["ID", "Title", "Budget", "Score", "Reason", "Competition"]
            rows = []
            competition_details = []
            for project in projects:
                budget_min = float(project.budget_minimum) if project.budget_minimum else 0.0
                budget_max = float(project.budget_maximum) if project.budget_maximum else 0.0
                budget = f"{budget_min:.0f}-{budget_max:.0f} {project.currency_code or ''}".strip()
                title = (project.title or "")[:60]
                reason = (project.ai_reason or "")[:80]
                score = f"{project.ai_score:.1f}" if project.ai_score is not None else "0.0"

                # Competition analysis summary
                analysis = competitor_bid_service.analyze_competition(db, project.freelancer_id)
                if analysis:
                    amt = analysis.get("amount", {})
                    comp_summary = (
                        f"{analysis['active_bids']}bids "
                        f"${amt.get('median', 0):.0f}med"
                    )
                    competition_details.append((project.freelancer_id, analysis))
                else:
                    comp_summary = "N/A"

                rows.append([str(project.freelancer_id), title, budget, score, reason, comp_summary])

        col_widths = [len(h) for h in headers]
        for row in rows:
            for idx, value in enumerate(row):
                col_widths[idx] = max(col_widths[idx], len(value))

        table_lines = []
        header_line = " | ".join(headers[idx].ljust(col_widths[idx]) for idx in range(len(headers)))
        table_lines.append(header_line)
        table_lines.append("-+-".join("-" * w for w in col_widths))
        for row in rows:
            line = " | ".join(row[idx].ljust(col_widths[idx]) for idx in range(len(row)))
            table_lines.append(line)

        table_text = "\n".join(table_lines)

        if rows:
            print(table_text)
        else:
            print("No projects found above threshold.")

        report_path = Path(args.output)
        report_header = (
            f"Threshold: {args.threshold}\n"
            f"Total: {len(rows)}\n"
            f"Filtered by remote status: {remote_filtered}\n"
        )

        # Build competition analysis appendix
        comp_lines = []
        if competition_details:
            comp_lines.append("\n--- Competition Analysis ---\n")
            for pid, analysis in competition_details:
                amt = analysis.get("amount", {})
                per = analysis.get("period", {})
                rep = analysis.get("reputation", {})
                comp_lines.append(
                    f"Project {pid}: "
                    f"bids={analysis['active_bids']}/{analysis['total_bids']} "
                    f"amount=[${amt.get('min', 0):.0f}-${amt.get('max', 0):.0f}, "
                    f"med=${amt.get('median', 0):.0f}, avg=${amt.get('avg', 0):.0f}] "
                    f"period=[{per.get('min', '?')}-{per.get('max', '?')}d, "
                    f"med={per.get('median', '?')}d] "
                    f"rep_avg={rep.get('avg', 'N/A')} "
                    f"top_bidders={rep.get('top_bidders', 0)}"
                )
        comp_text = "\n".join(comp_lines)

        report_path.write_text(
            report_header + "\n" + table_text + "\n" + comp_text + "\n",
            encoding="utf-8",
        )
        logger.info(f"Report written to {report_path}")

        return common.EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
