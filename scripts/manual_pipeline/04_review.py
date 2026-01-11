#!/usr/bin/env python3
"""
Review high-scoring projects and generate a report.
"""
import argparse
import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))

import common
from database.models import Project


def main(argv=None) -> int:
    default_report = Path(__file__).resolve().parents[2] / "review_report.txt"

    parser = argparse.ArgumentParser(description="Review projects above a score threshold.")
    parser.add_argument("--threshold", type=float, default=7.0, help="Minimum score threshold")
    parser.add_argument("--output", default=str(default_report), help="Report output file")
    parser.add_argument("--lock-file", default=str(common.DEFAULT_LOCK_FILE), help="Lock file path")
    args = parser.parse_args(argv)

    logger = common.setup_logging("manual_review")

    with common.file_lock(Path(args.lock_file), blocking=False) as acquired:
        if not acquired:
            print("Lock busy. Another workflow may be running.")
            return common.EXIT_LOCK_ERROR

        with common.get_db_context() as db:
            projects = (
                db.query(Project)
                .filter(Project.ai_score >= args.threshold)
                .order_by(Project.ai_score.desc())
                .all()
            )

            headers = ["ID", "Title", "Budget", "Score", "Reason"]
            rows = []
            for project in projects:
                budget_min = float(project.budget_minimum) if project.budget_minimum else 0.0
                budget_max = float(project.budget_maximum) if project.budget_maximum else 0.0
                budget = f"{budget_min:.0f}-{budget_max:.0f} {project.currency_code or ''}".strip()
                title = (project.title or "")[:60]
                reason = (project.ai_reason or "")[:80]
                score = f"{project.ai_score:.1f}" if project.ai_score is not None else "0.0"
                rows.append([str(project.freelancer_id), title, budget, score, reason])

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
        report_header = f"Threshold: {args.threshold}\nTotal: {len(rows)}\n"
        report_path.write_text(report_header + "\n" + table_text + "\n", encoding="utf-8")
        logger.info(f"Report written to {report_path}")

        return common.EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
