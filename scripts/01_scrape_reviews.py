"""Phase 1 — pull Play Store reviews for the target app.

Two-step approach:
  1. Scrape as many reviews as Play Store will serve (up to SCRAPE_TARGET),
     newest-first. Write the FULL pull to `data/raw_reviews_full.csv` — this is
     the immutable checkpoint. Later phases do not re-scrape.
  2. Downsample uniformly at random to CLASSIFY_TARGET rows and write to
     `data/raw_reviews.csv`. Uniform-random preserves the true per-day volume
     distribution, so the resulting trend lines aren't fake.

Why the split: Play Store paginates newest-first with no date filter and hits
throughput of ~300-1,700 reviews/day depending on app. To span months instead
of days at a 5k classification budget, we have to scrape wide and sample.

Run:
    python scripts/01_scrape_reviews.py
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from google_play_scraper import Sort, reviews

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (  # noqa: E402
    APP_COUNTRY,
    APP_LANG,
    APP_NAME,
    APP_PACKAGE,
    CLASSIFY_TARGET,
    DATA_DIR,
    DOWNSAMPLE_SEED,
    LOGS_DIR,
    RAW_REVIEWS_CSV,
    RAW_REVIEWS_FULL_CSV,
    SCRAPE_LOG,
    SCRAPE_TARGET,
    WINDOW_MONTHS,
)

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(SCRAPE_LOG, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("scrape")


def scrape() -> pd.DataFrame:
    cutoff = datetime.now(timezone.utc) - timedelta(days=WINDOW_MONTHS * 30)
    log.info("scraping %s (%s) up to %d reviews or cutoff %s",
             APP_NAME, APP_PACKAGE, SCRAPE_TARGET, cutoff.date())

    collected: list[dict] = []
    seen_ids: set[str] = set()
    token = None
    page = 0
    empty_pages = 0
    last_progress_bucket = -1

    while len(collected) < SCRAPE_TARGET:
        page += 1
        try:
            batch, token = reviews(
                APP_PACKAGE,
                lang=APP_LANG,
                country=APP_COUNTRY,
                sort=Sort.NEWEST,
                count=200,
                continuation_token=token,
            )
        except Exception as exc:
            log.warning("page %d failed (%s); sleeping 5s and retrying", page, exc)
            time.sleep(5)
            continue

        if not batch:
            empty_pages += 1
            log.info("empty batch on page %d (empty_pages=%d)", page, empty_pages)
            if empty_pages >= 3 or token is None:
                log.info("Play Store served no more reviews; stopping")
                break
            time.sleep(2)
            continue
        empty_pages = 0

        stop = False
        for r in batch:
            rid = r.get("reviewId")
            if not rid or rid in seen_ids:
                continue
            at = r.get("at")
            if at is not None and at.replace(tzinfo=timezone.utc) < cutoff:
                stop = True
                continue
            seen_ids.add(rid)
            collected.append(
                {
                    "review_id": rid,
                    "text": (r.get("content") or "").strip(),
                    "rating": r.get("score"),
                    "date": at.isoformat() if at else None,
                    "thumbs_up": r.get("thumbsUpCount", 0),
                }
            )
            if len(collected) >= SCRAPE_TARGET:
                break

        bucket = len(collected) // 2000
        if bucket > last_progress_bucket:
            oldest = min((r["date"] for r in collected if r["date"]), default="?")
            log.info("progress: %d reviews / %d pages, oldest so far %s",
                     len(collected), page, oldest)
            last_progress_bucket = bucket

        if token is None or stop:
            log.info("stopping: %s", "hit cutoff" if stop else "no continuation token")
            break

        time.sleep(0.5)

    df = pd.DataFrame(collected)
    before = len(df)
    df = df[df["text"].str.len() > 0].reset_index(drop=True)
    log.info("collected %d reviews (%d dropped as empty)", len(df), before - len(df))
    return df


def downsample(df: pd.DataFrame, target: int) -> pd.DataFrame:
    """Uniform-random sample. Preserves per-day density → trend lines stay honest."""
    if len(df) <= target:
        log.info("scraped only %d — using full set (no downsample needed)", len(df))
        return df.copy()
    return df.sample(n=target, random_state=DOWNSAMPLE_SEED).sort_values("date").reset_index(drop=True)


def _describe(df: pd.DataFrame, label: str) -> None:
    if df.empty:
        log.info("%s: EMPTY", label)
        return
    dates = pd.to_datetime(df["date"])
    log.info("%s: %d rows, %s → %s (%d days)",
             label, len(df), dates.min().date(), dates.max().date(),
             (dates.max() - dates.min()).days)


def main() -> None:
    df = scrape()
    if df.empty:
        log.error("no reviews collected; aborting write")
        sys.exit(1)

    df.to_csv(RAW_REVIEWS_FULL_CSV, index=False, encoding="utf-8")
    log.info("wrote %s (%d rows)", RAW_REVIEWS_FULL_CSV, len(df))
    _describe(df, "full scrape")

    sample = downsample(df, CLASSIFY_TARGET)
    sample.to_csv(RAW_REVIEWS_CSV, index=False, encoding="utf-8")
    log.info("wrote %s (%d rows)", RAW_REVIEWS_CSV, len(sample))
    _describe(sample, "downsampled")


if __name__ == "__main__":
    main()
