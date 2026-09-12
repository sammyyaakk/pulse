from __future__ import annotations

import argparse
import asyncio
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
from groq import AsyncGroq, RateLimitError
from tenacity import (
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (
    BATCH_SIZE,
    CLASSIFIED_DB,
    CLASSIFY_BATCH_SIZE,
    CLASSIFY_CONCURRENCY,
    CLASSIFY_FAILURES_LOG,
    DATA_DIR,
    LOGS_DIR,
    MODEL_CHAIN,
    RAW_REVIEWS_CSV,
    TAXONOMY,
)


class _ChainState:
    """Tracks which (primary, fallback) pair in MODEL_CHAIN is currently in use.

    Shared across concurrent workers. `advance_from(idx)` is idempotent — if
    two workers both hit exhaustion on the same pair, only one advance takes
    effect. Safe under asyncio because index reads/writes never straddle an
    await.
    """

    def __init__(self) -> None:
        self.index = 0

    def current(self) -> tuple[str, str] | None:
        if self.index >= len(MODEL_CHAIN):
            return None
        return MODEL_CHAIN[self.index]

    def advance_from(self, from_index: int) -> None:
        if self.index == from_index and self.index < len(MODEL_CHAIN):
            self.index += 1
            new = self.current()
            if new is not None:
                log.warning("chain: advancing to pair %d = %s / %s",
                            self.index, new[0], new[1])
            else:
                log.warning("chain: exhausted after %d pairs", self.index)


chain_state = _ChainState()

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
    retry=retry_if_not_exception_type(RateLimitError),
)
async def _call_groq(client: AsyncGroq, model: str, review_text: str) -> dict:
    resp = await client.chat.completions.create(
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
    retry=retry_if_not_exception_type(RateLimitError),
)
async def _call_groq_batch(client: AsyncGroq, model: str, payload: list[dict]) -> dict:
    resp = await client.chat.completions.create(
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


async def _try_pair_one(client: AsyncGroq,
                        primary: str,
                        fallback: str,
                        review_id: str,
                        text: str) -> tuple[Classification | None, bool, bool]:
    """One review through one chain pair.

    Returns (result, both_rate_limited, gave_up_on_review):
      - result != None: success
      - both_rate_limited=True: signal to advance the chain
      - gave_up_on_review=True: per-review failure, already logged, don't advance
    """
    both_rate_limited = True
    for model in (primary, fallback):
        try:
            data = await _call_groq(client, model, text)
        except RateLimitError as exc:
            log.warning("rate limit on %s (%s); trying next", model, exc)
            continue
        except Exception as exc:
            log_failure(review_id, text, f"{type(exc).__name__}: {exc}")
            return None, False, True
        both_rate_limited = False
        result = _parse_one_result(data, review_id, text, model)
        return result, False, result is None
    return None, both_rate_limited, False


async def classify_one(client: AsyncGroq, review_id: str, text: str) -> Classification | None:
    for _ in range(len(MODEL_CHAIN) + 1):
        idx = chain_state.index
        pair = chain_state.current()
        if pair is None:
            break
        primary, fallback = pair
        result, rate_limited_both, gave_up = await _try_pair_one(
            client, primary, fallback, review_id, text
        )
        if result is not None:
            return result
        if gave_up:
            return None
        if rate_limited_both:
            chain_state.advance_from(idx)
            continue
        return None

    log_failure(review_id, text, "model chain exhausted")
    return None


async def _try_pair_batch(client: AsyncGroq,
                          primary: str,
                          fallback: str,
                          reviews_batch: list[tuple[str, str]]
                          ) -> tuple[list[Classification], bool, bool]:
    """One batch through one chain pair.

    Returns (results, both_rate_limited, malformed):
      - results with items: partial or full success (missing ids handled by caller)
      - both_rate_limited=True: advance the chain
      - malformed=True: caller should fall back to sequential (per-review) path
                       without advancing (the batch prompt shape may just be
                       tripping this model)
    """
    payload = [{"id": i, "text": text[:1500]} for i, (_, text) in enumerate(reviews_batch)]
    both_rate_limited = True

    for model in (primary, fallback):
        try:
            data = await _call_groq_batch(client, model, payload)
        except RateLimitError as exc:
            log.warning("batch rate limit on %s (%s); trying next", model, exc)
            continue
        except Exception as exc:
            log.warning("batch call raised %s on %s; will fall back to sequential",
                        type(exc).__name__, model)
            return [], False, True

        both_rate_limited = False
        results = data.get("results")
        if not isinstance(results, list) or len(results) < len(reviews_batch):
            log.warning("batch under-returned (%d of %d) on %s; will fall back to sequential",
                        len(results) if isinstance(results, list) else 0,
                        len(reviews_batch), model)
            return [], False, True

        by_id: dict[int, dict] = {}
        for item in results:
            if not isinstance(item, dict):
                continue
            try:
                iid = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            if 0 <= iid < len(reviews_batch):
                by_id[iid] = item

        out: list[Classification] = []
        for idx, (rid, text) in enumerate(reviews_batch):
            item = by_id.get(idx)
            if item is None:
                continue
            parsed = _parse_one_result(item, rid, text, model)
            if parsed is not None:
                out.append(parsed)

        classified = {c.review_id for c in out}
        missing = [(rid, text) for rid, text in reviews_batch if rid not in classified]
        if missing:
            log.warning("batch missed %d ids on %s; retrying those sequentially",
                        len(missing), model)
            out.extend(await _classify_batch_sequentially(client, missing))

        return out, False, False

    return [], both_rate_limited, False


async def classify_batch(client: AsyncGroq,
                         reviews_batch: list[tuple[str, str]]) -> list[Classification]:
    """Classify a batch of reviews, walking MODEL_CHAIN as pairs get exhausted."""
    if not reviews_batch:
        return []

    for _ in range(len(MODEL_CHAIN) + 1):
        idx = chain_state.index
        pair = chain_state.current()
        if pair is None:
            break
        primary, fallback = pair
        results, rate_limited_both, malformed = await _try_pair_batch(
            client, primary, fallback, reviews_batch
        )
        if results:
            return results
        if malformed:
            return await _classify_batch_sequentially(client, reviews_batch)
        if rate_limited_both:
            chain_state.advance_from(idx)
            continue
        break

    for rid, text in reviews_batch:
        log_failure(rid, text, "model chain exhausted (batch)")
    return []


async def _classify_batch_sequentially(client: AsyncGroq,
                                       reviews_batch: list[tuple[str, str]]
                                       ) -> list[Classification]:
    out: list[Classification] = []
    for rid, text in reviews_batch:
        result = await classify_one(client, rid, text)
        if result is not None:
            out.append(result)
    return out


def _chunks(rows: list[tuple[str, str]], n: int) -> list[list[tuple[str, str]]]:
    return [rows[i:i + n] for i in range(0, len(rows), n)]


async def run_async(client: AsyncGroq,
                    remaining_rows: list[tuple[str, str]],
                    conn: sqlite3.Connection) -> None:
    batches = _chunks(remaining_rows, CLASSIFY_BATCH_SIZE)
    total = len(remaining_rows)
    log.info("running with concurrency=%d over %d batches (%d reviews, batch=%d)",
             CLASSIFY_CONCURRENCY, len(batches), total, CLASSIFY_BATCH_SIZE)

    sem = asyncio.Semaphore(CLASSIFY_CONCURRENCY)

    async def bounded(batch: list[tuple[str, str]]) -> list[Classification]:
        async with sem:
            return await classify_batch(client, batch)

    tasks = [asyncio.create_task(bounded(b)) for b in batches]

    write_buffer: list[Classification] = []
    completed_batches = 0

    for done_task in asyncio.as_completed(tasks):
        results = await done_task
        write_buffer.extend(results)
        completed_batches += 1
        processed = min(completed_batches * CLASSIFY_BATCH_SIZE, total)

        if len(write_buffer) >= BATCH_SIZE:
            save_batch(conn, write_buffer)
            log.info("wrote checkpoint - %d processed / %d remaining, %d failures",
                     processed, max(total - processed, 0), _count_failures())
            write_buffer.clear()

    if write_buffer:
        save_batch(conn, write_buffer)
        log.info("wrote final checkpoint - %d processed total", total)


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

    remaining_rows = [(str(r.review_id), str(r.text))
                      for r in remaining.itertuples(index=False)]

    async def _entry() -> None:
        client = AsyncGroq(api_key=api_key)
        try:
            await run_async(client, remaining_rows, conn)
        finally:
            await client.close()

    asyncio.run(_entry())
    conn.close()


def _count_failures() -> int:
    if not CLASSIFY_FAILURES_LOG.exists():
        return 0
    with open(CLASSIFY_FAILURES_LOG, "r", encoding="utf-8") as f:
        return sum(1 for _ in f)


if __name__ == "__main__":
    main()
