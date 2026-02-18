#!/usr/bin/env python3
"""
Weekly bid outcome report.

Closed loop:
1) Optionally sync competitor bid results (award status).
2) Analyze won/lost/pending outcomes for recent bids.
3) Generate attribution-focused weekly markdown report.
"""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = ROOT / "python_service" / "data" / "freelancer.db"
DEFAULT_OUTPUT_PATH = ROOT / "logs" / "bid_outcome_weekly_report.md"


def compute_percentile_rank(
    values: List[Optional[float]],
    target: Optional[float],
    *,
    lower_is_better: bool = True,
) -> Optional[float]:
    """Return percentile rank (0-100)."""
    if target is None:
        return None
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return None

    target_f = float(target)
    if lower_is_better:
        rank_count = sum(1 for v in clean if v <= target_f)
    else:
        rank_count = sum(1 for v in clean if v >= target_f)
    return round(rank_count * 100.0 / len(clean), 1)


def infer_loss_reasons(
    *,
    my_amount: Optional[float],
    winner_amount: Optional[float],
    my_period: Optional[int],
    winner_period: Optional[int],
    my_price_percentile: Optional[float],
    my_period_percentile: Optional[float],
) -> List[str]:
    """Infer likely loss reasons from numeric comparisons."""
    reasons: List[str] = []

    if my_amount is not None and winner_amount is not None and winner_amount > 0:
        if my_amount >= winner_amount * 1.15:
            reasons.append("报价显著高于中标价")
        elif my_amount <= winner_amount * 0.85:
            reasons.append("低价仍未中标（可能受信誉/文案/历史影响）")

    if my_period is not None and winner_period is not None:
        if my_period >= winner_period + 2:
            reasons.append("工期明显长于中标者")
        elif my_period + 2 <= winner_period:
            reasons.append("工期更短但仍未中标（可能受其他因素影响）")

    if my_price_percentile is not None and my_price_percentile >= 80:
        reasons.append("价格分位偏高（报价偏贵）")
    if my_period_percentile is not None and my_period_percentile >= 80:
        reasons.append("工期分位偏高（周期偏长）")

    if not reasons:
        reasons.append("缺少明确差异信号（需补充客户侧反馈）")
    return list(dict.fromkeys(reasons))


def summarize_outcomes(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(rows)
    won = sum(1 for row in rows if row.get("outcome") == "won")
    lost = sum(1 for row in rows if row.get("outcome") == "lost")
    pending = sum(1 for row in rows if row.get("outcome") == "pending")

    reason_counter: Counter[str] = Counter()
    for row in rows:
        if row.get("outcome") != "lost":
            continue
        for reason in row.get("reasons", []):
            reason_counter[reason] += 1

    top_reasons = [
        {"reason": reason, "count": count}
        for reason, count in reason_counter.most_common()
    ]

    coverage = sum(
        1
        for row in rows
        if row.get("competitor_count", 0) > 0
    )

    return {
        "total": total,
        "won": won,
        "lost": lost,
        "pending": pending,
        "with_competitor_data": coverage,
        "top_reasons": top_reasons,
    }


def _run_query(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
    cur = conn.execute(sql, params)
    return cur.fetchall()


def _get_recent_bids(conn: sqlite3.Connection, since_days: int) -> List[Dict[str, Any]]:
    rows = _run_query(
        conn,
        """
        SELECT
            b.project_freelancer_id,
            b.freelancer_bid_id,
            b.bidder_id,
            CAST(b.amount AS REAL) AS amount,
            b.period,
            b.created_at,
            p.title,
            p.status AS project_status
        FROM bids b
        LEFT JOIN projects p ON p.freelancer_id = b.project_freelancer_id
        WHERE datetime(b.created_at) >= datetime('now', ?)
        ORDER BY datetime(b.created_at) DESC
        """,
        (f"-{since_days} day",),
    )
    return [dict(row) for row in rows]


def _get_competitors(
    conn: sqlite3.Connection,
    project_freelancer_id: int,
) -> List[Dict[str, Any]]:
    rows = _run_query(
        conn,
        """
        SELECT
            bidder_id,
            CAST(amount AS REAL) AS amount,
            period,
            award_status,
            retracted,
            reputation
        FROM competitor_bids
        WHERE project_freelancer_id = ?
          AND retracted = 0
          AND amount IS NOT NULL
          AND CAST(amount AS REAL) > 0
        """,
        (project_freelancer_id,),
    )
    return [dict(row) for row in rows]


def _choose_winner(competitors: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    winners = [
        row for row in competitors
        if str(row.get("award_status") or "").strip().lower() == "awarded"
    ]
    if not winners:
        return None
    winners.sort(key=lambda row: float(row.get("amount") or 0))
    return winners[0]


def build_outcome_rows(conn: sqlite3.Connection, since_days: int) -> List[Dict[str, Any]]:
    recent_bids = _get_recent_bids(conn, since_days=since_days)
    rows: List[Dict[str, Any]] = []

    for bid in recent_bids:
        pid = int(bid["project_freelancer_id"])
        my_bidder_id = int(bid["bidder_id"])
        my_amount = bid.get("amount")
        my_period = bid.get("period")

        competitors = _get_competitors(conn, pid)
        peer_rows = [
            row for row in competitors
            if int(row.get("bidder_id") or 0) != my_bidder_id
        ]
        competitor_amounts = [row.get("amount") for row in peer_rows if row.get("amount") is not None]
        competitor_periods = [row.get("period") for row in peer_rows if row.get("period") is not None]

        winner = _choose_winner(competitors)
        if winner is None:
            outcome = "pending"
            reasons: List[str] = []
        elif int(winner["bidder_id"]) == my_bidder_id:
            outcome = "won"
            reasons = []
        else:
            outcome = "lost"
            reasons = infer_loss_reasons(
                my_amount=my_amount,
                winner_amount=winner.get("amount"),
                my_period=my_period,
                winner_period=winner.get("period"),
                my_price_percentile=compute_percentile_rank(
                    competitor_amounts, my_amount, lower_is_better=True
                ),
                my_period_percentile=compute_percentile_rank(
                    competitor_periods, my_period, lower_is_better=True
                ),
            )

        rows.append(
            {
                "project_freelancer_id": pid,
                "title": bid.get("title") or "",
                "project_status": bid.get("project_status") or "",
                "my_amount": my_amount,
                "my_period": my_period,
                "created_at": bid.get("created_at"),
                "competitor_count": len(peer_rows),
                "winner_bidder_id": winner.get("bidder_id") if winner else None,
                "winner_amount": winner.get("amount") if winner else None,
                "winner_period": winner.get("period") if winner else None,
                "my_price_percentile": compute_percentile_rank(
                    competitor_amounts, my_amount, lower_is_better=True
                ),
                "my_period_percentile": compute_percentile_rank(
                    competitor_periods, my_period, lower_is_better=True
                ),
                "outcome": outcome,
                "reasons": reasons,
            }
        )

    return rows


def _format_top_reasons(top_reasons: List[Dict[str, Any]]) -> List[str]:
    if not top_reasons:
        return ["- 无（当前没有可归因的落标样本）"]
    return [f"- {item['reason']}: {item['count']}" for item in top_reasons[:8]]


def render_markdown_report(
    *,
    since_days: int,
    summary: Dict[str, Any],
    rows: List[Dict[str, Any]],
    sync_info: Optional[Dict[str, Any]],
) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: List[str] = []
    lines.append("# 投标结果周报（落标归因）")
    lines.append("")
    lines.append(f"- 生成时间: {now}")
    lines.append(f"- 统计窗口: 近 {since_days} 天")
    lines.append(f"- 样本总数: {summary['total']}")
    if sync_info:
        lines.append(
            f"- award 同步: 检查 {sync_info.get('projects_checked', 0)} 个项目，"
            f"拉取/更新竞品出价 {sync_info.get('bids_upserted', 0)} 条"
        )
    lines.append("")
    lines.append("## 总览")
    lines.append("")
    lines.append(f"- 中标: {summary['won']}")
    lines.append(f"- 落标: {summary['lost']}")
    lines.append(f"- 待定: {summary['pending']}")
    lines.append(f"- 有竞品数据: {summary['with_competitor_data']}")
    lines.append("")
    lines.append("## 高频落标原因")
    lines.append("")
    lines.extend(_format_top_reasons(summary.get("top_reasons", [])))
    lines.append("")
    lines.append("## 落标样本明细")
    lines.append("")
    lines.append("| 项目ID | 标题 | 我方报价 | 中标价 | 我方工期 | 中标工期 | 原因 |")
    lines.append("|---|---|---:|---:|---:|---:|---|")

    lost_rows = [row for row in rows if row.get("outcome") == "lost"]
    if not lost_rows:
        lines.append("| - | - | - | - | - | - | 当前无落标结果数据 |")
    else:
        for row in lost_rows[:20]:
            lines.append(
                "| {pid} | {title} | {my_amt} | {win_amt} | {my_p} | {win_p} | {reasons} |".format(
                    pid=row.get("project_freelancer_id"),
                    title=str(row.get("title") or "").replace("|", " "),
                    my_amt=row.get("my_amount"),
                    win_amt=row.get("winner_amount"),
                    my_p=row.get("my_period"),
                    win_p=row.get("winner_period"),
                    reasons="; ".join(row.get("reasons", [])),
                )
            )
    lines.append("")
    lines.append("## 备注")
    lines.append("")
    lines.append("- 若中标/落标状态为空，通常表示平台尚未决标或本地未拉到 award 字段。")
    lines.append("- 本报告仅基于结构化字段（金额/工期/award），不包含客户私聊文本反馈。")
    return "\n".join(lines) + "\n"


def _append_python_service_path() -> None:
    py_service = ROOT / "python_service"
    if str(py_service) not in sys.path:
        sys.path.insert(0, str(py_service))


async def sync_awards(since_days: int) -> Dict[str, int]:
    """Sync competitor bids for recently bidded projects."""
    _append_python_service_path()
    from database.connection import SessionLocal  # type: ignore
    from services.competitor_bid_service import sync_bids_for_our_projects  # type: ignore

    session = SessionLocal()
    try:
        synced = await sync_bids_for_our_projects(
            session,
            since_days=since_days if since_days > 0 else None,
            concurrency=5,
        )
        return {
            "projects_checked": len(synced),
            "bids_upserted": sum(synced.values()),
        }
    finally:
        session.close()


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate weekly bid outcome attribution report.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="SQLite DB path")
    parser.add_argument("--since-days", type=int, default=7, help="Lookback days")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="Markdown output path")
    parser.add_argument(
        "--sync-awards",
        dest="sync_awards",
        action="store_true",
        help="Sync award/competitor data before analysis",
    )
    parser.add_argument(
        "--no-sync-awards",
        dest="sync_awards",
        action="store_false",
        help="Skip award sync",
    )
    parser.set_defaults(sync_awards=True)
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    db_path = Path(args.db_path).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return 1

    sync_info: Optional[Dict[str, Any]] = None
    if args.sync_awards:
        if db_path != DEFAULT_DB_PATH.resolve():
            sync_info = {
                "projects_checked": 0,
                "bids_upserted": 0,
                "warning": "sync_skipped_non_default_db_path",
            }
        else:
            sync_info = asyncio.run(sync_awards(args.since_days))

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = build_outcome_rows(conn, since_days=args.since_days)
        summary = summarize_outcomes(rows)
        report = render_markdown_report(
            since_days=args.since_days,
            summary=summary,
            rows=rows,
            sync_info=sync_info,
        )
    finally:
        conn.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")

    print(
        f"Report generated: {output_path}\n"
        f"total={summary['total']} won={summary['won']} lost={summary['lost']} pending={summary['pending']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
