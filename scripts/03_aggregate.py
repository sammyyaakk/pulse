from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (
    CLASSIFIED_DB,
    EXPORTS_DIR,
    RAW_REVIEWS_CSV,
    TAXONOMY,
)

EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("aggregate")


def load_joined() -> pd.DataFrame:
    if not RAW_REVIEWS_CSV.exists():
        raise SystemExit(f"missing {RAW_REVIEWS_CSV} - run Phase 1 first")
    if not CLASSIFIED_DB.exists():
        raise SystemExit(f"missing {CLASSIFIED_DB} - run Phase 2 first")

    raw = pd.read_csv(RAW_REVIEWS_CSV, parse_dates=["date"])
    with sqlite3.connect(CLASSIFIED_DB) as conn:
        cls = pd.read_sql_query(
            "SELECT review_id, category, severity FROM classifications", conn
        )

    df = raw.merge(cls, on="review_id", how="inner")
    df["month"] = df["date"].dt.to_period("M").dt.to_timestamp()
    df["is_low_star"] = df["rating"].isin([1, 2])
    log.info("joined %d classified reviews (of %d raw)", len(df), len(raw))
    return df


def monthly_volume(df: pd.DataFrame) -> pd.DataFrame:
    months = pd.date_range(df["month"].min(), df["month"].max(), freq="MS")
    idx = pd.MultiIndex.from_product([months, TAXONOMY], names=["month", "category"])
    out = (
        df.groupby(["month", "category"])
        .size()
        .reindex(idx, fill_value=0)
        .reset_index(name="review_count")
    )
    return out


def low_star_share(df: pd.DataFrame) -> pd.DataFrame:
    low = df[df["is_low_star"]]
    total = len(low)
    counts = low.groupby("category").size().reindex(TAXONOMY, fill_value=0)
    out = counts.reset_index(name="low_star_count")
    out["share_of_low_star"] = out["low_star_count"] / total if total else 0.0
    return out.sort_values("low_star_count", ascending=False).reset_index(drop=True)


def severity_weighted(df: pd.DataFrame) -> pd.DataFrame:
    grouped = df.groupby("category").agg(
        review_count=("severity", "size"),
        avg_severity=("severity", "mean"),
    )
    grouped["severity_weighted_score"] = grouped["avg_severity"] * grouped["review_count"]
    out = grouped.reindex(TAXONOMY).fillna(
        {"review_count": 0, "avg_severity": 0, "severity_weighted_score": 0}
    )
    return out.reset_index().sort_values("severity_weighted_score", ascending=False).reset_index(drop=True)


def rating_distribution(df: pd.DataFrame) -> pd.DataFrame:
    stars = [1, 2, 3, 4, 5]
    idx = pd.MultiIndex.from_product([TAXONOMY, stars], names=["category", "rating"])
    out = (
        df.groupby(["category", "rating"])
        .size()
        .reindex(idx, fill_value=0)
        .reset_index(name="review_count")
    )
    return out


def main() -> None:
    df = load_joined()

    outputs = {
        "monthly_theme_volume.csv": monthly_volume(df),
        "low_star_theme_share.csv": low_star_share(df),
        "severity_weighted_score.csv": severity_weighted(df),
        "rating_distribution_by_theme.csv": rating_distribution(df),
    }

    for name, table in outputs.items():
        path = EXPORTS_DIR / name
        table.to_csv(path, index=False, encoding="utf-8")
        log.info("wrote %s (%d rows)", path, len(table))

    xlsx_path = EXPORTS_DIR / "pulse_dashboard_tables.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        for name, table in outputs.items():
            sheet = name.replace(".csv", "")[:31]
            table.to_excel(writer, sheet_name=sheet, index=False)
    log.info("wrote %s", xlsx_path)


if __name__ == "__main__":
    main()
