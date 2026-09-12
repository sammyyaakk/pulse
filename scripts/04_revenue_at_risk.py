"""Phase 4 — estimate revenue at risk per complaint theme.

Formula (stated explicitly per the brief):
    revenue_at_risk =
        (1-star review count for theme)
        * ASSUMED_CHURN_RATE
        * ASSUMED_AVG_ORDER_VALUE_INR
        * ASSUMED_ORDER_FREQUENCY_MULTIPLIER

Every assumed input below is a named constant with a comment saying where the
number came from. If you disagree with a number, change it in one place and
re-run — the memo assumptions section in the README should update alongside.

Run:
    python scripts/04_revenue_at_risk.py
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import CLASSIFIED_DB, RAW_REVIEWS_CSV, REVENUE_AT_RISK_CSV, TAXONOMY  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("revenue")

# ---------------------------------------------------------------------------
# Assumptions — every number here MUST have a citation or an "assumption" tag.
# Keep these in sync with the README's Assumptions section.
# ---------------------------------------------------------------------------

# Share of 1-star reviewers assumed to churn from the app entirely within a year.
# Assumption (not a cited figure): 40%. A 1-star review on a delivery app is a
# strong dissatisfaction signal; industry rules-of-thumb range 25-60%.
ASSUMED_CHURN_RATE = 0.40

# Blinkit average order value in INR.
# Source: Zomato Q4 FY24 investor deck reported Blinkit AOV around ₹617 for
# the quarter ending Mar-2024. Rounded down conservatively.
# Ref: https://b.zmtcdn.com/investor-relations/Zomato_Q4FY24.pdf
ASSUMED_AVG_ORDER_VALUE_INR = 600

# Assumed annualized order-frequency multiplier for the "churned" cohort — i.e.
# how many orders the app loses per churned user over the churn horizon.
# Public estimates put an active Blinkit user at ~2-3 orders / month. Assuming
# these users would have averaged 2 orders / month over a 12-month horizon,
# that is 24 orders forgone per churned user.
# Assumption (based on public commentary, not audited).
ASSUMED_ORDER_FREQUENCY_MULTIPLIER = 24


def load_one_star_counts() -> pd.DataFrame:
    if not RAW_REVIEWS_CSV.exists():
        raise SystemExit(f"missing {RAW_REVIEWS_CSV} — run Phase 1 first")
    if not CLASSIFIED_DB.exists():
        raise SystemExit(f"missing {CLASSIFIED_DB} — run Phase 2 first")

    raw = pd.read_csv(RAW_REVIEWS_CSV)
    with sqlite3.connect(CLASSIFIED_DB) as conn:
        cls = pd.read_sql_query(
            "SELECT review_id, category, severity FROM classifications", conn
        )
    df = raw.merge(cls, on="review_id", how="inner")

    one_star = df[df["rating"] == 1]
    per_theme = one_star.groupby("category").size().reindex(TAXONOMY, fill_value=0)
    return per_theme.reset_index(name="one_star_reviews")


def load_severity_and_volume() -> pd.DataFrame:
    with sqlite3.connect(CLASSIFIED_DB) as conn:
        return pd.read_sql_query(
            """
            SELECT category,
                   COUNT(*)        AS review_count,
                   AVG(severity)   AS avg_severity
            FROM classifications
            GROUP BY category
            """,
            conn,
        )


def main() -> None:
    one_star = load_one_star_counts()
    stats = load_severity_and_volume()

    df = one_star.merge(stats, on="category", how="left").fillna(
        {"review_count": 0, "avg_severity": 0}
    )

    df["revenue_at_risk_inr"] = (
        df["one_star_reviews"]
        * ASSUMED_CHURN_RATE
        * ASSUMED_AVG_ORDER_VALUE_INR
        * ASSUMED_ORDER_FREQUENCY_MULTIPLIER
    ).round(0)

    df["severity_weighted_score"] = (df["avg_severity"] * df["review_count"]).round(1)

    df = df[
        [
            "category",
            "one_star_reviews",
            "review_count",
            "avg_severity",
            "severity_weighted_score",
            "revenue_at_risk_inr",
        ]
    ].sort_values("revenue_at_risk_inr", ascending=False).reset_index(drop=True)

    df.to_csv(REVENUE_AT_RISK_CSV, index=False, encoding="utf-8")
    log.info("wrote %s", REVENUE_AT_RISK_CSV)

    print("\n=== Revenue-at-risk ranking (INR) ===")
    print(df.to_string(index=False))
    print(
        f"\nAssumptions: churn={ASSUMED_CHURN_RATE:.0%}, "
        f"AOV=INR {ASSUMED_AVG_ORDER_VALUE_INR}, "
        f"orders/churner={ASSUMED_ORDER_FREQUENCY_MULTIPLIER}"
    )


if __name__ == "__main__":
    main()
