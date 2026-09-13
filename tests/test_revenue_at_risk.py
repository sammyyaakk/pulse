"""Tests for scripts/04_revenue_at_risk.py.

The three things worth testing:
  1. load_one_star_counts() only counts 1-star reviews, joins raw against
     the classifications DB, and zero-fills every category in the taxonomy.
  2. load_severity_and_volume() returns per-category totals from the DB.
  3. main() applies the revenue-at-risk formula correctly, ranks by
     revenue at risk descending, and writes the CSV.

All three touch the filesystem (CSV + SQLite), so each test uses tmp_path
and monkeypatch to redirect the module's path constants at fixture builds.
"""

from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

import revenue  # loaded by conftest.py

from config import TAXONOMY


def _write_fixture(raw_csv_path, db_path):
    """Six reviews across three categories with a mix of ratings and severities."""
    raw = pd.DataFrame({
        "review_id": ["r1", "r2", "r3", "r4", "r5", "r6"],
        "text":      ["a", "b", "c", "d", "e", "f"],
        "rating":    [1, 1, 1, 2, 1, 5],
        "date":      ["2026-06-01T00:00:00"] * 6,
        "thumbs_up": [0] * 6,
    })
    raw.to_csv(raw_csv_path, index=False)

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE classifications (
            review_id     TEXT PRIMARY KEY,
            category      TEXT NOT NULL,
            severity      INTEGER NOT NULL,
            justification TEXT,
            model_used    TEXT,
            classified_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    rows = [
        ("r1", "Customer service / refunds",   5, "x", "test-model"),
        ("r2", "Customer service / refunds",   4, "x", "test-model"),
        ("r3", "Late/delayed delivery",         5, "x", "test-model"),
        ("r4", "Late/delayed delivery",         3, "x", "test-model"),
        ("r5", "Late/delayed delivery",         4, "x", "test-model"),
        ("r6", "Other / positive",              1, "x", "test-model"),
    ]
    conn.executemany(
        "INSERT INTO classifications "
        "(review_id, category, severity, justification, model_used) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


@pytest.fixture
def fake_pipeline(tmp_path, monkeypatch):
    """Redirect revenue module paths at fake CSV + SQLite in tmp_path.

    Contents (hand-picked for testable numbers):
      Customer service / refunds:   r1 (1★, sev 5), r2 (1★, sev 4)
      Late/delayed delivery:         r3 (1★, sev 5), r4 (2★, sev 3), r5 (1★, sev 4)
      Other / positive:              r6 (5★, sev 1)
    So one-star counts are: Customer service 2, Late/delayed 2, everything else 0.
    """
    raw_csv = tmp_path / "raw_reviews.csv"
    db_path = tmp_path / "classified_reviews.db"
    out_csv = tmp_path / "revenue_at_risk.csv"
    _write_fixture(raw_csv, db_path)

    monkeypatch.setattr(revenue, "RAW_REVIEWS_CSV", raw_csv)
    monkeypatch.setattr(revenue, "CLASSIFIED_DB", db_path)
    monkeypatch.setattr(revenue, "REVENUE_AT_RISK_CSV", out_csv)
    return tmp_path


def test_load_one_star_counts_shape(fake_pipeline):
    df = revenue.load_one_star_counts()
    # Every category from the taxonomy should show up exactly once
    assert list(df["category"]) == list(TAXONOMY)
    assert list(df.columns) == ["category", "one_star_reviews"]


def test_load_one_star_counts_specific_numbers(fake_pipeline):
    df = revenue.load_one_star_counts().set_index("category")["one_star_reviews"]
    assert df["Customer service / refunds"] == 2
    assert df["Late/delayed delivery"] == 2
    assert df["Other / positive"] == 0
    assert df["Stockouts / item unavailability"] == 0
    assert df["Rider / delivery-person behavior"] == 0


def test_load_one_star_counts_ignores_two_star(fake_pipeline):
    """r4 is a 2-star Late/delayed review and must not be counted."""
    df = revenue.load_one_star_counts().set_index("category")["one_star_reviews"]
    # 3 late/delayed rows in the fixture but only 2 are 1-star
    assert df["Late/delayed delivery"] == 2


def test_load_severity_and_volume_shape(fake_pipeline):
    df = revenue.load_severity_and_volume()
    # Only categories present in the DB — Late/delayed, Customer service, Other
    assert set(df["category"]) == {
        "Customer service / refunds",
        "Late/delayed delivery",
        "Other / positive",
    }
    assert set(df.columns) == {"category", "review_count", "avg_severity"}


def test_load_severity_and_volume_math(fake_pipeline):
    df = revenue.load_severity_and_volume().set_index("category")
    # Customer service: 2 rows, severities 5 and 4 → avg 4.5
    assert df.loc["Customer service / refunds", "review_count"] == 2
    assert df.loc["Customer service / refunds", "avg_severity"] == pytest.approx(4.5)
    # Late/delayed: 3 rows, severities 5, 3, 4 → avg 4.0
    assert df.loc["Late/delayed delivery", "review_count"] == 3
    assert df.loc["Late/delayed delivery", "avg_severity"] == pytest.approx(4.0)


def test_main_writes_csv_with_full_taxonomy(fake_pipeline, capsys):
    revenue.main()
    out = pd.read_csv(fake_pipeline / "revenue_at_risk.csv")
    assert set(out["category"]) == set(TAXONOMY)
    assert list(out.columns) == [
        "category",
        "one_star_reviews",
        "review_count",
        "avg_severity",
        "severity_weighted_score",
        "revenue_at_risk_inr",
    ]


def test_main_revenue_arithmetic(fake_pipeline):
    revenue.main()
    out = pd.read_csv(fake_pipeline / "revenue_at_risk.csv").set_index("category")
    # 2 one-star reviews * 0.40 churn * 600 AOV * 24 orders = 11,520
    expected = 2 * revenue.ASSUMED_CHURN_RATE \
             * revenue.ASSUMED_AVG_ORDER_VALUE_INR \
             * revenue.ASSUMED_ORDER_FREQUENCY_MULTIPLIER
    assert out.loc["Customer service / refunds", "revenue_at_risk_inr"] == round(expected)
    assert out.loc["Late/delayed delivery", "revenue_at_risk_inr"] == round(expected)


def test_main_severity_weighted_arithmetic(fake_pipeline):
    revenue.main()
    out = pd.read_csv(fake_pipeline / "revenue_at_risk.csv").set_index("category")
    # Customer service: avg 4.5 * 2 rows = 9.0
    assert out.loc["Customer service / refunds", "severity_weighted_score"] == pytest.approx(9.0)
    # Late/delayed: avg 4.0 * 3 rows = 12.0
    assert out.loc["Late/delayed delivery", "severity_weighted_score"] == pytest.approx(12.0)


def test_main_zero_revenue_for_empty_theme(fake_pipeline):
    """Themes with 0 one-star reviews must produce ₹0 at risk."""
    revenue.main()
    out = pd.read_csv(fake_pipeline / "revenue_at_risk.csv").set_index("category")
    assert out.loc["Other / positive", "revenue_at_risk_inr"] == 0
    assert out.loc["Stockouts / item unavailability", "revenue_at_risk_inr"] == 0
    assert out.loc["Rider / delivery-person behavior", "revenue_at_risk_inr"] == 0


def test_main_ranked_descending(fake_pipeline):
    revenue.main()
    out = pd.read_csv(fake_pipeline / "revenue_at_risk.csv")
    revenues = out["revenue_at_risk_inr"].to_list()
    assert revenues == sorted(revenues, reverse=True)


def test_assumptions_are_named_constants():
    """Guards against someone re-inlining the assumption numbers in code."""
    assert isinstance(revenue.ASSUMED_CHURN_RATE, float)
    assert isinstance(revenue.ASSUMED_AVG_ORDER_VALUE_INR, int)
    assert isinstance(revenue.ASSUMED_ORDER_FREQUENCY_MULTIPLIER, int)
    assert 0 < revenue.ASSUMED_CHURN_RATE < 1
