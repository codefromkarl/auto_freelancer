#!/usr/bin/env python3
"""
One-click manual pipeline runner (stop before bid).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple


PROXY_ENV_KEYS = [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
]


def _build_steps(args: argparse.Namespace, script_dir: Path) -> List[Tuple[str, List[str]]]:
    python_bin = sys.executable
    include_hourly_args = ["--include-hourly"] if args.include_hourly else []
    return [
        (
            "check_env",
            [python_bin, str(script_dir / "01_check_env.py")],
        ),
        (
            "fetch",
            [
                python_bin,
                str(script_dir / "02_fetch.py"),
                "--keywords",
                args.keywords,
                "--limit",
                str(args.limit),
                "--since-days",
                str(args.since_days),
                "--allowed-statuses",
                args.allowed_statuses,
                *include_hourly_args,
            ],
        ),
        (
            "fetch_bids",
            [
                python_bin,
                str(script_dir / "02b_fetch_bids.py"),
                "--since-days",
                str(args.since_days),
                "--allowed-statuses",
                args.allowed_statuses,
                *include_hourly_args,
            ],
        ),
        (
            "score",
            [
                python_bin,
                str(script_dir / "03_score_concurrent.py"),
                "--since-days",
                str(args.since_days),
                "--allowed-statuses",
                args.allowed_statuses,
                *include_hourly_args,
            ],
        ),
        (
            "review",
            [
                python_bin,
                str(script_dir / "04_review.py"),
                "--threshold",
                str(args.threshold),
                "--output",
                args.output,
                "--since-days",
                str(args.since_days),
                "--allowed-statuses",
                args.allowed_statuses,
                *include_hourly_args,
            ],
        ),
    ]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run manual pipeline until bid step.")
    parser.add_argument(
        "--keywords",
        default="python automation,fastapi,web scraping,api integration",
        help="Comma-separated fetch keywords for step 02",
    )
    parser.add_argument("--limit", type=int, default=20, help="Fetch limit per keyword for step 02")
    parser.add_argument("--since-days", type=int, default=7, help="Only keep projects in recent N days")
    parser.add_argument(
        "--allowed-statuses",
        default="open,active,open_for_bidding",
        help="Comma-separated allowed statuses",
    )
    parser.add_argument("--threshold", type=float, default=6.0, help="Review threshold for step 04")
    parser.add_argument("--output", default="review_report.txt", help="Review output path")
    parser.add_argument(
        "--keep-proxy",
        action="store_true",
        help="Keep proxy environment variables (default: unset proxies for stability)",
    )
    parser.add_argument(
        "--include-hourly",
        action="store_true",
        help="Include hourly projects (default: fixed-price only)",
    )
    args = parser.parse_args(argv)
    if args.since_days <= 0:
        print("--since-days must be greater than 0.", flush=True)
        return 2

    script_dir = Path(__file__).resolve().parent
    steps = _build_steps(args, script_dir)

    run_env = os.environ.copy()
    if not args.keep_proxy:
        for key in PROXY_ENV_KEYS:
            run_env.pop(key, None)

    total = len(steps)
    for idx, (name, cmd) in enumerate(steps, start=1):
        print(f"[{idx}/{total}] Running {name}: {' '.join(cmd)}", flush=True)
        result = subprocess.run(cmd, check=False, env=run_env)
        if result.returncode != 0:
            print(f"Step failed: {name} (exit={result.returncode})", flush=True)
            return int(result.returncode)

    print("Pipeline completed until bid step.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
