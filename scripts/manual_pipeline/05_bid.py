#!/usr/bin/env python3
"""
Interactive bid submission script.
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime
import re

script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))

import common
from database.models import Project, Bid
from services import bid_service
from services.freelancer_client import FreelancerAPIError
from services.proposal_service import get_proposal_service

PROXY_ENV_KEYS = [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
]
NUMERIC_PATTERN = re.compile(
    r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?",
    re.IGNORECASE,
)
QUOTE_CANDIDATE_PATTERNS = [
    # $80 / $ 80.50
    re.compile(
        r"\$\s*((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)",
        re.IGNORECASE,
    ),
    # 80 USD / 80 usd
    re.compile(
        r"((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(?:usd|eur|gbp|cad|aud|sgd|cny)\b",
        re.IGNORECASE,
    ),
    # budget ... 80 / quote ... 80 / bid ... 80
    re.compile(
        r"(?:budget|quote|bid|price)[^0-9\n]{0,80}((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)",
        re.IGNORECASE,
    ),
]


def _safe_float(raw: str) -> float | None:
    try:
        return float((raw or "").replace(",", ""))
    except Exception:
        return None


def _extract_numbers(segment: str) -> list[float]:
    values: list[float] = []
    for m in NUMERIC_PATTERN.finditer(segment or ""):
        number = _safe_float(m.group(0))
        if number is None:
            continue
        values.append(number)
    return values


def _extract_budget_context_candidates(proposal: str) -> list[float]:
    values: list[float] = []
    for m in re.finditer(r"\bbudget\b[^\n]{0,120}", proposal or "", re.IGNORECASE):
        values.extend(_extract_numbers(m.group(0)))
    return values


def _dedupe_values(values: list[float]) -> list[float]:
    deduped: list[float] = []
    for value in values:
        if any(abs(value - existing) < 0.01 for existing in deduped):
            continue
        deduped.append(value)
    return deduped


LEGACY_QUOTE_CANDIDATE_PATTERN = re.compile(
    r"(?:budget|quote|bid|price|\$|usd|eur|gbp|cad|aud|sgd|cny)\D{0,80}((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)",
    re.IGNORECASE,
)


def _slugify(value: str) -> str:
    """Create a filesystem-safe slug."""
    text = (value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text[:60] or "untitled"


def _save_preview_archive(
    archive_dir: Path,
    *,
    project_id: int,
    title: str,
    amount: float,
    currency: str,
    input_amount: float | None = None,
    input_currency: str | None = None,
    period: int,
    proposal_source: str,
    proposal: str,
) -> Path:
    """Persist bid preview content to a markdown archive file."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    title_slug = _slugify(title)
    filename = f"{ts}_p{project_id}_{proposal_source}_{title_slug}.md"
    path = archive_dir / filename

    solution_summary = _extract_solution_summary(proposal)
    milestones = _build_milestones(period, proposal)
    milestone_lines = "\n".join([f"{idx}. {item}" for idx, item in enumerate(milestones, start=1)])

    amount_meta_lines = []
    if (
        input_amount is not None
        and input_currency
        and abs(float(input_amount) - float(amount)) > 0.01
    ):
        amount_meta_lines.append(f"- Input Amount: {float(input_amount):.2f} {input_currency}")
    amount_meta_lines.append(f"- Submission Amount: {float(amount):.2f} {currency}")
    amount_meta_text = "\n".join(amount_meta_lines)

    text = (
        "# Bid Preview Archive\n\n"
        f"- Timestamp: {datetime.now().isoformat(timespec='seconds')}\n"
        f"- Project ID: {project_id}\n"
        f"- Title: {title}\n"
        f"{amount_meta_text}\n"
        f"- Period: {period} days\n"
        f"- Proposal Source: {proposal_source}\n\n"
        "## Structured Bid Summary\n\n"
        f"- Bid Amount: {amount:.2f} {currency}\n"
        f"- Expected Completion: {period} days\n"
        f"- Solution Summary: {solution_summary}\n"
        "- Milestones:\n"
        f"{milestone_lines}\n\n"
        "## Proposal\n\n"
        f"{proposal}\n"
    )
    path.write_text(text, encoding="utf-8")
    return path


def _extract_solution_summary(proposal: str, max_len: int = 260) -> str:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", proposal or "") if p.strip()]
    if not paragraphs:
        return "Proposal generated. See full text below."
    summary = paragraphs[0]
    summary = re.sub(r"\s+", " ", summary).strip()
    if len(summary) > max_len:
        summary = summary[: max_len - 3].rstrip() + "..."
    return summary


def _normalize_milestone_line(text: str, max_len: int = 180) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    cleaned = re.sub(r"^[\-\*\d\.\)\s]+", "", cleaned)
    if not cleaned:
        return ""
    if len(cleaned) > max_len:
        cleaned = cleaned[: max_len - 3].rstrip() + "..."
    return cleaned


def _build_milestones(period_days: int, proposal: str) -> list[str]:
    lines = [line.strip() for line in (proposal or "").splitlines() if line.strip()]
    keywords = ("milestone", "phase", "week", "day", "timeline", "schedule")
    extracted: list[str] = []
    for line in lines:
        low = line.lower()
        if not any(k in low for k in keywords):
            continue
        normalized = _normalize_milestone_line(line)
        if normalized:
            extracted.append(normalized)
        if len(extracted) >= 4:
            break
    if len(extracted) >= 2:
        return extracted[:4]

    total = max(2, int(period_days))
    first_end = max(1, round(total * 0.3))
    second_start = min(total, first_end + 1)
    second_end = max(second_start, round(total * 0.75))
    third_start = min(total, second_end + 1)
    if third_start <= second_end:
        return [
            "Day 1: Requirement confirmation, data/interface mapping, and implementation plan lock.",
            f"Day {min(total, 2)}: Core implementation, integration, and iterative validation.",
            f"Final delivery window (by Day {total}): QA, deployment/readme handover, and acceptance support.",
        ]
    return [
        f"Day 1-Day {first_end}: Requirement confirmation, data/interface mapping, and implementation plan lock.",
        f"Day {second_start}-Day {second_end}: Core implementation, integration, and iterative validation.",
        f"Day {third_start}-Day {total}: Final QA, deployment/readme handover, and acceptance support.",
    ]


def _extract_quote_candidates(proposal: str) -> list[float]:
    values: list[float] = []
    text = proposal or ""
    for pattern in QUOTE_CANDIDATE_PATTERNS:
        for match in pattern.finditer(text):
            number = _safe_float(match.group(1))
            if number is None:
                continue
            values.append(number)

    # Fallback: extract numbers in nearby budget contexts, e.g. "budget for this trial is 200 USD"
    if not values:
        values.extend(_extract_budget_context_candidates(text))

    # Compatibility fallback for legacy pattern coverage
    if not values:
        for match in LEGACY_QUOTE_CANDIDATE_PATTERN.finditer(text):
            number = _safe_float(match.group(1))
            if number is None:
                continue
            values.append(number)

    return _dedupe_values(values)


def _align_proposal_with_amount(proposal: str, amount: float, currency: str) -> str:
    """
    Ensure final proposal explicitly matches the bid amount if prior quote looks inconsistent.
    """
    candidates = _extract_quote_candidates(proposal)
    if not candidates:
        return proposal

    tolerance = max(1.0, float(amount) * 0.12)
    if any(abs(v - float(amount)) <= tolerance for v in candidates):
        return proposal

    alignment_line = (
        f"\n\nFinal bid amount for this proposal: {float(amount):.2f} {currency}."
    )
    return proposal.rstrip() + alignment_line


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Prepare a frozen bid or submit under the configured authorization mode")
    parser.add_argument('--project-id', type=int)
    parser.add_argument('--amount', type=float)
    parser.add_argument('--amount-currency')
    parser.add_argument('--period', type=int, default=7)
    parser.add_argument('--proposal')
    parser.add_argument('--approval-id')
    parser.add_argument('--submit', action='store_true')
    parser.add_argument('--dry-run', action='store_true', help='Prepare only; never submit')
    args = parser.parse_args(argv)
    from services.approved_bids import prepare_bid, submit_approved_bid
    from services.qqbot_service import QQBotConfig, QQBotClient
    from services.qqbot_store import QQBotStore
    from services.qqbot_events import notify_snapshot, preview_text
    try:
        settings = common.get_settings()
        config = QQBotConfig.from_env()
        store = QQBotStore(config.state_path)
        with common.get_db_context() as db:
            if args.submit:
                if args.dry_run:
                    raise ValueError('--submit cannot use --dry-run')
                identity = args.approval_id
                if not identity:
                    if settings.BID_APPROVAL_MODE != 'automatic' or not args.project_id or args.amount is None:
                        raise ValueError('--submit requires a snapshot ID or an automatic-mode project and amount')
                    if not settings.BID_SUBMISSION_ENABLED:
                        raise ValueError('真实投标开关未开启')
                    record = asyncio.run(prepare_bid(db, args.project_id, args.amount, args.period,
                        args.proposal, args.amount_currency, store))
                    identity = record['id']
                result = asyncio.run(submit_approved_bid(db, identity, store))
                print(f"Submitted confirmed bid ID: {result['bid_id']}")
            else:
                if not args.project_id or args.amount is None:
                    raise ValueError('Preparing a snapshot requires --project-id and --amount')
                record = asyncio.run(prepare_bid(db, args.project_id, args.amount, args.period,
                    args.proposal, args.amount_currency, store))
                print(preview_text(record))
                if not args.dry_run and settings.BID_APPROVAL_MODE == 'qq':
                    notify_snapshot(QQBotClient(config), store, record)
                print('Prepared only. No Freelancer bid was submitted.')
    except Exception as exc:
        print(f'Bid operation blocked: {type(exc).__name__}: {exc}')
        return common.EXIT_VALIDATION_ERROR
    return common.EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
