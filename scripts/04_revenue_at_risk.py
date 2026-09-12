from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import CLASSIFIED_DB, RAW_REVIEWS_CSV, REVENUE_AT_RISK_CSV, TAXONOMY

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("revenue")

ASSUMED_CHURN_RATE = 0.40
ASSUMED_AVG_ORDER_VALUE_INR = 600
ASSUMED_ORDER_FREQUENCY_MULTIPLIER = 24


def load_one_star_counts() -> pd.DataFrame:
    if not RAW_REVIEWS_CSV.exists():
        raise SystemExit(f"missing {RAW_REVIEWS_CSV} - run Phase 1 first")
    if not CLASSIFIED_DB.exists():
        raise SystemExit(f"missing {CLASSIFIED_DB} - run Phase 2 first")

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
