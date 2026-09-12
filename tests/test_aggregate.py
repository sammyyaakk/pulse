"""Tests for the aggregation layer in scripts/03_aggregate.py.

Each aggregation function takes a joined DataFrame (raw reviews + their
classifications) and returns a dashboard-ready table. The tests build a
small synthetic joined frame with known counts and check that the numbers
come out of each aggregator correctly.
"""

from __future__ import annotations

import pandas as pd
import pytest

import aggregate  # loaded by conftest.py

from config import TAXONOMY


@pytest.fixture
def small_joined_df() -> pd.DataFrame:
    """A minimal joined frame mimicking what aggregate.load_joined() returns.

    Rows chosen so each aggregation has at least one interesting value to check.
    """
    rows = [
        # (date,        rating, category,                            severity)
        ("2026-06-05", 1, "Late/delayed delivery",              5),
        ("2026-06-15", 2, "Late/delayed delivery",              4),
        ("2026-06-20", 5, "Other / positive",                   1),
        ("2026-07-01", 1, "Customer service / refunds",         5),
        ("2026-07-10", 1, "Customer service / refunds",         4),
        ("2026-07-15", 3, "App bugs / payment failures",        3),
        ("2026-08-05", 5, "Other / positive",                   1),
        ("2026-08-08", 1, "Rider / delivery-person behavior",   5),
    ]
    df = pd.DataFrame(rows, columns=["date", "rating", "category", "severity"])
    df["date"] = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.to_period("M").dt.to_timestamp()
    df["is_low_star"] = df["rating"].isin([1, 2])
    return df


def test_monthly_volume_shape(small_joined_df):
    out = aggregate.monthly_volume(small_joined_df)
    # 3 months x 8 categories = 24 rows; missing (month, category) combos are
    # filled with 0 instead of dropped
    assert len(out) == 3 * len(TAXONOMY)
    assert list(out.columns) == ["month", "category", "review_count"]
    assert (out["review_count"] >= 0).all()


def test_monthly_volume_fills_missing_categories(small_joined_df):
    out = aggregate.monthly_volume(small_joined_df)
    # Stockouts appears in TAXONOMY but not in the fixture — should still show
    # up with 0 in every month
    stockouts = out[out["category"] == "Stockouts / item unavailability"]
    assert len(stockouts) == 3
    assert (stockouts["review_count"] == 0).all()


def test_monthly_volume_specific_counts(small_joined_df):
    out = aggregate.monthly_volume(small_joined_df)
    june = out[out["month"] == pd.Timestamp("2026-06-01")]
    assert june.loc[june["category"] == "Late/delayed delivery",
                    "review_count"].iloc[0] == 2
    assert june.loc[june["category"] == "Other / positive",
                    "review_count"].iloc[0] == 1
    july = out[out["month"] == pd.Timestamp("2026-07-01")]
    assert july.loc[july["category"] == "Customer service / refunds",
                    "review_count"].iloc[0] == 2


def test_low_star_share_sums_to_one(small_joined_df):
    out = aggregate.low_star_share(small_joined_df)
    # Fixture has 5 low-star reviews (1★ + 2★), so shares should sum to exactly 1
    assert abs(out["share_of_low_star"].sum() - 1.0) < 1e-9


def test_low_star_share_top_row(small_joined_df):
    out = aggregate.low_star_share(small_joined_df)
    # Late/delayed delivery and Customer service / refunds both have 2 low-star
    # reviews (tied at the top); whichever tie-breaker wins, top has count 2
    assert out.iloc[0]["low_star_count"] == 2
    assert out.iloc[0]["share_of_low_star"] == pytest.approx(0.4)


def test_low_star_share_covers_taxonomy(small_joined_df):
    out = aggregate.low_star_share(small_joined_df)
    assert set(out["category"]) == set(TAXONOMY)


def test_severity_weighted_shape(small_joined_df):
    out = aggregate.severity_weighted(small_joined_df)
    assert len(out) == len(TAXONOMY)
    assert list(out.columns) == [
        "category", "review_count", "avg_severity", "severity_weighted_score"
    ]


def test_severity_weighted_customer_service_math(small_joined_df):
    out = aggregate.severity_weighted(small_joined_df)
    cs = out[out["category"] == "Customer service / refunds"].iloc[0]
    # Two reviews with severity 5 and 4 → avg = 4.5, score = 4.5 * 2 = 9.0
    assert cs["review_count"] == 2
    assert cs["avg_severity"] == pytest.approx(4.5)
    assert cs["severity_weighted_score"] == pytest.approx(9.0)


def test_severity_weighted_ranked_descending(small_joined_df):
    out = aggregate.severity_weighted(small_joined_df)
    scores = out["severity_weighted_score"].to_list()
    assert scores == sorted(scores, reverse=True)


def test_severity_weighted_empty_category_stays_at_zero(small_joined_df):
    out = aggregate.severity_weighted(small_joined_df)
    # Stockouts isn't in the fixture — should be zero-filled, not dropped
    stockouts = out[out["category"] == "Stockouts / item unavailability"].iloc[0]
    assert stockouts["review_count"] == 0
    assert stockouts["avg_severity"] == 0
    assert stockouts["severity_weighted_score"] == 0


def test_rating_distribution_shape(small_joined_df):
    out = aggregate.rating_distribution(small_joined_df)
    # 8 categories x 5 star ratings = 40 rows, gaps filled with 0
    assert len(out) == len(TAXONOMY) * 5
    assert list(out.columns) == ["category", "rating", "review_count"]
    assert (out["review_count"] >= 0).all()


def test_rating_distribution_specific_count(small_joined_df):
    out = aggregate.rating_distribution(small_joined_df)
    row = out[(out["category"] == "Customer service / refunds")
              & (out["rating"] == 1)].iloc[0]
    assert row["review_count"] == 2


def test_rating_distribution_absent_combo_is_zero(small_joined_df):
    out = aggregate.rating_distribution(small_joined_df)
    # Nothing in the fixture at (App bugs, 5-star)
    row = out[(out["category"] == "App bugs / payment failures")
              & (out["rating"] == 5)].iloc[0]
    assert row["review_count"] == 0
