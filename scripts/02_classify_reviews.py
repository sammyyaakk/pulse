from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd
from dotenv import load_dotenv
from groq import Groq, RateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (
    BATCH_SIZE,
    CLASSIFIED_DB,
    CLASSIFY_BATCH_SIZE,
    CLASSIFY_FAILURES_LOG,
    DATA_DIR,
    FALLBACK_MODEL,
    LOGS_DIR,
    PRIMARY_MODEL,
    RAW_REVIEWS_CSV,
    TAXONOMY,
)

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
log = logging.getLogger("classify")


SYSTEM_PROMPT = f"""You classify short user reviews of a quick-commerce delivery app.

You must pick exactly ONE category from this fixed list. Do not invent new categories.
If the review is positive, neutral, or does not clearly match any other category,
use "Other / positive".

Allowed categories (verbatim):
{chr(10).join(f"- {c}" for c in TAXONOMY)}

Return ONLY a JSON object with keys:
  "category": one of the categories above, exact string
  "severity": integer 1-5 (1 = mild, 5 = severe / churn-inducing)
  "justification": one short sentence, under 25 words
No prose outside the JSON."""


BATCH_SYSTEM_PROMPT = f"""You classify short user reviews of a quick-commerce delivery app.

The user message contains a JSON array of reviews, each with a numeric id and text.
For each review, pick exactly ONE category from this fixed list. Do not invent new categories.
If a review is positive, neutral, or does not clearly match any other category, use "Other / positive".

Allowed categories (verbatim):
{chr(10).join(f"- {c}" for c in TAXONOMY)}

Return ONLY a JSON object shaped:
{{
  "results": [
    {{"id": <int>, "category": "<one of above>", "severity": <1-5>, "justification": "<one short sentence under 25 words>"}},
    ...
  ]
}}
Return exactly one result per input review, keyed by the same id. No prose outside the JSON."""


@dataclass
class Classification:
    review_id: str
    category: str
    severity: int
    justification: str
    model_used: str


def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(CLASSIFIED_DB)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS classifications (
            review_id     TEXT PRIMARY KEY,
            category      TEXT NOT NULL,
            severity      INTEGER NOT NULL,
            justification TEXT,
            model_used    TEXT,
            classified_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    return conn


def already_classified(conn: sqlite3.Connection) -> set[str]:
    cur = conn.execute("SELECT review_id FROM classifications")
    return {row[0] for row in cur.fetchall()}


def save_batch(conn: sqlite3.Connection, rows: Iterable[Classification]) -> None:
    conn.executemany(
        """
        INSERT OR REPLACE INTO classifications
            (review_id, category, severity, justification, model_used)
        VALUES (?, ?, ?, ?, ?)
        """,
        [(r.review_id, r.category, r.severity, r.justification, r.model_used) for r in rows],
    )
    conn.commit()


def log_failure(review_id: str, text: str, reason: str) -> None:
    with open(CLASSIFY_FAILURES_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"review_id": review_id, "text": text, "reason": reason}) + "\n")


@retry(
    reraise=True,
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(Exception),
)
def _call_groq(client: Groq, model: str, review_text: str) -> dict:
    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": review_text[:1500]},
        ],
    )
    content = resp.choices[0].message.content or "{}"
    return json.loads(content)


@retry(
    reraise=True,
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(Exception),
)
def _call_groq_batch(client: Groq, model: str, payload: list[dict]) -> dict:
    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": BATCH_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    )
    content = resp.choices[0].message.content or "{}"
    return json.loads(content)


def _parse_one_result(item: dict, review_id: str, text: str, model: str) -> Classification | None:
    category = item.get("category")
    if category not in TAXONOMY:
        log_failure(review_id, text, f"invalid category: {category!r}")
        return None
    try:
        severity = int(item.get("severity", 3))
    except (TypeError, ValueError):
        severity = 3
    severity = max(1, min(5, severity))
    justification = str(item.get("justification", ""))[:300]
    return Classification(review_id, category, severity, justification, model)


def classify_one(client: Groq, review_id: str, text: str) -> Classification | None:
    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        try:
            data = _call_groq(client, model, text)
        except RateLimitError as exc:
            log.warning("rate limit on %s (%s); trying fallback", model, exc)
            continue
        except Exception as exc:
            log_failure(review_id, text, f"{type(exc).__name__}: {exc}")
            return None
        result = _parse_one_result(data, review_id, text, model)
        if result is not None:
            return result
        return None

    log_failure(review_id, text, "rate-limited on both primary and fallback")
    return None


def classify_batch(client: Groq, reviews_batch: list[tuple[str, str]]) -> list[Classification]:
    """Classify a batch of reviews in a single API call.

    Falls back to per-review classify_one() calls if the batch response is
    malformed or under-sized, so quality never regresses relative to the
    sequential path.
    """
    if not reviews_batch:
        return []

    payload = [{"id": i, "text": text[:1500]} for i, (_, text) in enumerate(reviews_batch)]

    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        try:
            data = _call_groq_batch(client, model, payload)
        except RateLimitError as exc:
            log.warning("batch rate limit on %s (%s); trying fallback", model, exc)
            continue
        except Exception as exc:
            log.warning("batch call raised %s on %s; falling back to per-review",
                        type(exc).__name__, model)
            return _classify_batch_sequentially(client, reviews_batch)

        results = data.get("results")
        if not isinstance(results, list) or len(results) < len(reviews_batch):
            log.warning("batch under-returned (%d of %d) on %s; falling back to per-review",
                        len(results) if isinstance(results, list) else 0, len(reviews_batch), model)
            return _classify_batch_sequentially(client, reviews_batch)

        by_id = {}
        for item in results:
            if not isinstance(item, dict):
                continue
            try:
                idx = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            if 0 <= idx < len(reviews_batch):
                by_id[idx] = item

        out: list[Classification] = []
        missing = 0
        for idx, (rid, text) in enumerate(reviews_batch):
            item = by_id.get(idx)
            if item is None:
                missing += 1
                continue
            parsed = _parse_one_result(item, rid, text, model)
            if parsed is not None:
                out.append(parsed)

        if missing:
            log.warning("batch had %d missing ids; falling back to per-review for those",
                        missing)
            missing_reviews = [(rid, text) for idx, (rid, text) in enumerate(reviews_batch)
                               if idx not in by_id]
            out.extend(_classify_batch_sequentially(client, missing_reviews))

        return out

    for rid, text in reviews_batch:
        log_failure(rid, text, "rate-limited on both primary and fallback (batch)")
    return []


def _classify_batch_sequentially(client: Groq,
                                 reviews_batch: list[tuple[str, str]]) -> list[Classification]:
    out: list[Classification] = []
    for rid, text in reviews_batch:
        result = classify_one(client, rid, text)
        if result is not None:
            out.append(result)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    load_dotenv()
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        log.error("GROQ_API_KEY missing. Copy .env.example to .env and fill it in.")
        sys.exit(1)

    if not RAW_REVIEWS_CSV.exists():
        log.error("missing %s - run scripts/01_scrape_reviews.py first", RAW_REVIEWS_CSV)
        sys.exit(1)

    df = pd.read_csv(RAW_REVIEWS_CSV)
    df = df.dropna(subset=["review_id", "text"])
    log.info("loaded %d reviews from %s", len(df), RAW_REVIEWS_CSV)

    conn = init_db()
    done = already_classified(conn)
    remaining = df[~df["review_id"].isin(done)].reset_index(drop=True)
    log.info("%d already classified, %d remaining", len(done), len(remaining))

    if args.limit is not None:
        remaining = remaining.head(args.limit)
        log.info("--limit %d: classifying only the first %d", args.limit, len(remaining))

    client = Groq(api_key=api_key)

    pending: list[tuple[str, str]] = []
    write_buffer: list[Classification] = []
    processed = 0
    for row in remaining.itertuples(index=False):
        pending.append((str(row.review_id), str(row.text)))
        processed += 1

        if len(pending) >= CLASSIFY_BATCH_SIZE:
            write_buffer.extend(classify_batch(client, pending))
            pending.clear()

        if len(write_buffer) >= BATCH_SIZE:
            save_batch(conn, write_buffer)
            log.info("wrote batch - %d processed / %d remaining, %d in this run's failures.jsonl",
                     processed, len(remaining) - processed, _count_failures())
            write_buffer.clear()

    if pending:
        write_buffer.extend(classify_batch(client, pending))
        pending.clear()

    if write_buffer:
        save_batch(conn, write_buffer)
        log.info("wrote final batch - %d processed total", processed)

    conn.close()


def _count_failures() -> int:
    if not CLASSIFY_FAILURES_LOG.exists():
        return 0
    with open(CLASSIFY_FAILURES_LOG, "r", encoding="utf-8") as f:
        return sum(1 for _ in f)


if __name__ == "__main__":
    main()
