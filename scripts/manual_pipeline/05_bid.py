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

    text = (
        "# Bid Preview Archive\n\n"
        f"- Timestamp: {datetime.now().isoformat(timespec='seconds')}\n"
        f"- Project ID: {project_id}\n"
        f"- Title: {title}\n"
        f"- Amount: {amount} {currency}\n"
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
    parser = argparse.ArgumentParser(description="Submit a bid for a project.")
    parser.add_argument("--project-id", type=int, help="Freelancer project ID")
    parser.add_argument("--amount", type=float, help="Bid amount")
    parser.add_argument("--period", type=int, default=7, help="Delivery period in days")
    parser.add_argument("--proposal", type=str, help="Manual proposal text (requires --allow-manual-proposal)")
    parser.add_argument(
        "--allow-manual-proposal",
        action="store_true",
        help="Allow manual proposal and bypass automatic proposal generation (not recommended)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without submitting")
    parser.add_argument(
        "--keep-proxy",
        action="store_true",
        help="Keep proxy env vars (default: unset for better SDK/LLM compatibility)",
    )
    parser.add_argument(
        "--allowed-statuses",
        default=",".join(common.DEFAULT_BIDDABLE_STATUSES),
        help="Comma-separated allowed statuses for bidding",
    )
    parser.add_argument(
        "--preview-archive-dir",
        default="logs/bid_previews",
        help="Directory to archive bid preview markdown files",
    )
    parser.add_argument(
        "--no-save-preview",
        action="store_true",
        help="Do not save preview content to archive files",
    )
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
            if not args.keep_proxy:
                for key in PROXY_ENV_KEYS:
                    os.environ.pop(key, None)
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

            existing_bid = (
                db.query(Bid)
                .filter(Bid.project_freelancer_id == project_id)
                .filter(Bid.status != "withdrawn")
                .first()
            )
            if existing_bid is not None:
                print(
                    f"Project {project_id} already has local bid record "
                    f"(bid_id={getattr(existing_bid, 'freelancer_bid_id', 'unknown')}, "
                    f"status={getattr(existing_bid, 'status', 'unknown')})."
                )
                return common.EXIT_VALIDATION_ERROR

            # 实时校验远端项目状态，避免对已冻结/关闭项目继续预览或投标
            try:
                is_biddable_now, reason = asyncio.run(
                    bid_service.validate_project_biddable_now(db, project)
                )
            except Exception as exc:
                print(f"Failed to validate remote project status: {exc}")
                return common.EXIT_API_ERROR

            if not is_biddable_now:
                print(f"Project {project_id} is not biddable now: {reason}")
                return common.EXIT_VALIDATION_ERROR

            allowed_statuses = common.parse_statuses(
                args.allowed_statuses,
                default=list(common.DEFAULT_BIDDABLE_STATUSES),
            )
            current_status = (project.status or "").lower()
            if current_status not in allowed_statuses:
                print(
                    f"Project {project_id} status is '{project.status}', "
                    f"not in bid-able statuses: {', '.join(allowed_statuses)}"
                )
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

            if args.proposal and not args.allow_manual_proposal:
                print(
                    "Manual proposal is disabled by default for compliance. "
                    "Use --allow-manual-proposal to override."
                )
                return common.EXIT_VALIDATION_ERROR

            if args.allow_manual_proposal:
                proposal = (args.proposal or "").strip()
                if not proposal:
                    print("Missing manual proposal text.")
                    return common.EXIT_VALIDATION_ERROR
                proposal_source = "manual_override"
            else:
                print("Generating proposal via ProposalService...")
                proposal_service = get_proposal_service()
                used_fallback = False
                score_data = {
                    "suggested_bid": float(amount),
                    "estimated_hours": int(project.estimated_hours)
                    if getattr(project, "estimated_hours", None) is not None
                    else None,
                }
                try:
                    proposal_result = asyncio.run(
                        proposal_service.generate_proposal(
                            project,
                            score_data=score_data,
                            db=db,
                        )
                    )
                except Exception as exc:
                    logger.error(f"Proposal generation error: {exc}")
                    print(f"Proposal generation error: {exc}")
                    return common.EXIT_API_ERROR

                proposal = (proposal_result.get("proposal") or "").strip()
                validation_passed = proposal_result.get("validation_passed")
                validation_issues = proposal_result.get("validation_issues") or []
                error_code = proposal_result.get("error")

                # 文案验证失败：禁止 fallback，要求后续继续优化后重试
                if error_code == "proposal_validation_failed" or (
                    validation_passed is False and validation_issues
                ):
                    issues_text = "；".join(str(i) for i in validation_issues) or "unknown"
                    print(
                        "Generated proposal failed validation. "
                        f"Please refine prompt/config and retry. issues={issues_text}"
                    )
                    return common.EXIT_VALIDATION_ERROR

                if (
                    not proposal_result.get("success")
                    or not proposal
                ):
                    logger.warning(
                        "Primary proposal generation failed; using fallback template. "
                        "error=%s validation_passed=%s",
                        proposal_result.get("error"),
                        validation_passed,
                    )
                    proposal = proposal_service.generate_fallback_proposal(project).strip()
                    used_fallback = True

                if not proposal:
                    print(
                        "Proposal generation failed. "
                        f"error={proposal_result.get('error') or 'unknown'}"
                    )
                    return common.EXIT_API_ERROR

                proposal = _align_proposal_with_amount(
                    proposal,
                    float(amount),
                    project.currency_code or "USD",
                )

                content_safe, risk_reason = bid_service.check_content_risk(proposal, project)
                if not content_safe:
                    print(f"Generated proposal blocked by content risk check: {risk_reason}")
                    return common.EXIT_VALIDATION_ERROR
                proposal_source = "fallback_draft" if used_fallback else "llm_final"

            print("\nBid Preview")
            print("-" * 40)
            print(f"Project ID: {project.freelancer_id}")
            print(f"Title: {project.title}")
            print(f"Amount: {amount} {project.currency_code}")
            print(f"Period: {args.period} days")
            print(f"Proposal Source: {proposal_source}")
            print("Proposal:")
            print(proposal)
            print("-" * 40)

            if not args.no_save_preview:
                try:
                    archive_path = _save_preview_archive(
                        Path(args.preview_archive_dir),
                        project_id=project.freelancer_id,
                        title=project.title or "",
                        amount=float(amount),
                        currency=project.currency_code or "USD",
                        period=args.period,
                        proposal_source=proposal_source,
                        proposal=proposal,
                    )
                    print(f"Preview archived: {archive_path}")
                except Exception as exc:
                    logger.warning("Failed to archive preview: %s", exc)
                    print(f"Warning: failed to archive preview: {exc}")

            confirm = input("Submit bid? [y/N]: ").strip().lower()
            if confirm != "y":
                print("Cancelled.")
                return common.EXIT_SUCCESS

            if args.dry_run:
                print("[Dry Run] Bid not submitted.")
                return common.EXIT_SUCCESS

            if proposal_source == "fallback_draft":
                print(
                    "Submission blocked: generated proposal is fallback draft, "
                    "not a final proposal. Re-run later or use --allow-manual-proposal."
                )
                return common.EXIT_VALIDATION_ERROR

            try:
                asyncio.run(
                    bid_service.create_bid(
                        db,
                        project_id=project.freelancer_id,
                        amount=amount,
                        period=args.period,
                        description=proposal,
                        validate_remote_status=False,
                    )
                )
                project.status = "bid_submitted"
                db.commit()
                print("Bid submitted.")
                return common.EXIT_SUCCESS
            except FreelancerAPIError as exc:
                error_text = str(exc.message or "")
                if "SKILLS_REQUIREMENT_NOT_MET" in error_text:
                    try:
                        project.status = "skills_blocked"
                        db.commit()
                        print(
                            f"Project {project_id} marked as skills_blocked "
                            "due to platform skills requirement."
                        )
                    except Exception:
                        db.rollback()
                else:
                    db.rollback()
                logger.error(f"Bid API error: {exc.message}")
                print(f"Bid API error: {exc.message}")
                return common.EXIT_API_ERROR
            except Exception as exc:
                db.rollback()
                logger.error(f"Bid error: {exc}")
                print(f"Bid error: {exc}")
                return common.EXIT_API_ERROR


if __name__ == "__main__":
    sys.exit(main())
