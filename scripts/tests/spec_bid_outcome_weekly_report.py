import importlib.util
import sqlite3
from pathlib import Path


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_percentile_rank_low_to_high():
    module = _load_module(
        Path("scripts/utils/bid_outcome_weekly_report.py"),
        "bid_outcome_weekly_report",
    )

    pct = module.compute_percentile_rank([100, 200, 300], 200, lower_is_better=True)
    assert pct == 66.7


def test_infer_loss_reasons_high_price_and_long_period():
    module = _load_module(
        Path("scripts/utils/bid_outcome_weekly_report.py"),
        "bid_outcome_weekly_report_reasons",
    )

    reasons = module.infer_loss_reasons(
        my_amount=800,
        winner_amount=500,
        my_period=12,
        winner_period=7,
        my_price_percentile=90.0,
        my_period_percentile=88.0,
    )

    assert "报价显著高于中标价" in reasons
    assert "工期明显长于中标者" in reasons


def test_summarize_outcomes_counts_reason_frequency():
    module = _load_module(
        Path("scripts/utils/bid_outcome_weekly_report.py"),
        "bid_outcome_weekly_report_summary",
    )

    rows = [
        {"outcome": "lost", "reasons": ["报价显著高于中标价", "工期明显长于中标者"]},
        {"outcome": "pending", "reasons": []},
        {"outcome": "won", "reasons": []},
        {"outcome": "lost", "reasons": ["低价仍未中标（可能受信誉/文案/历史影响）"]},
    ]

    summary = module.summarize_outcomes(rows)

    assert summary["total"] == 4
    assert summary["won"] == 1
    assert summary["lost"] == 2
    assert summary["pending"] == 1
    assert summary["top_reasons"][0]["reason"] == "报价显著高于中标价"
    assert summary["top_reasons"][0]["count"] == 1


def test_build_outcome_rows_marks_won_when_awarded_to_us():
    module = _load_module(
        Path("scripts/utils/bid_outcome_weekly_report.py"),
        "bid_outcome_weekly_report_won",
    )

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE bids (
            project_freelancer_id INTEGER,
            freelancer_bid_id INTEGER,
            bidder_id INTEGER,
            amount REAL,
            period INTEGER,
            created_at TEXT
        );
        CREATE TABLE projects (
            freelancer_id INTEGER,
            title TEXT,
            status TEXT
        );
        CREATE TABLE competitor_bids (
            project_freelancer_id INTEGER,
            bidder_id INTEGER,
            amount REAL,
            period INTEGER,
            award_status TEXT,
            retracted INTEGER,
            reputation REAL
        );
        """
    )
    conn.execute(
        "INSERT INTO bids VALUES (?,?,?,?,?,datetime('now'))",
        (12345, 999, 111, 500.0, 5),
    )
    conn.execute(
        "INSERT INTO projects VALUES (?,?,?)",
        (12345, "Demo Project", "bid_submitted"),
    )
    conn.execute(
        "INSERT INTO competitor_bids VALUES (?,?,?,?,?,?,?)",
        (12345, 111, 500.0, 5, "awarded", 0, 4.9),
    )
    conn.execute(
        "INSERT INTO competitor_bids VALUES (?,?,?,?,?,?,?)",
        (12345, 222, 520.0, 6, "", 0, 4.6),
    )
    conn.commit()

    rows = module.build_outcome_rows(conn, since_days=7)
    assert len(rows) == 1
    assert rows[0]["outcome"] == "won"
