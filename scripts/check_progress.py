from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import CLASSIFIED_DB, CLASSIFY_FAILURES_LOG

TOTAL_TARGET = 5000
WINDOW_MIN = 10
RATE_ALERT_BELOW = 8
FAILURE_ALERT_ABOVE = 10


def total_failure_count() -> int:
    if not CLASSIFY_FAILURES_LOG.exists():
        return 0
    with open(CLASSIFY_FAILURES_LOG, "r", encoding="utf-8") as f:
        return sum(1 for _ in f)


def failures_in_window(now: datetime, minutes: int) -> int:
    """Count failure log entries with logged_at within the last `minutes` minutes.

    Entries without a logged_at field (from before the timestamped-log
    change) are ignored — they can't be placed on the timeline.
    """
    if not CLASSIFY_FAILURES_LOG.exists():
        return 0
    cutoff = now - timedelta(minutes=minutes)
    count = 0
    with open(CLASSIFY_FAILURES_LOG, "r", encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = entry.get("logged_at")
            if not ts:
                continue
            try:
                logged = datetime.fromisoformat(ts).replace(tzinfo=None)
            except ValueError:
                continue
            if logged >= cutoff:
                count += 1
    return count


def main() -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(minutes=WINDOW_MIN)

    with sqlite3.connect(CLASSIFIED_DB) as conn:
        total = conn.execute("SELECT COUNT(*) FROM classifications").fetchone()[0]
        row = conn.execute("SELECT MAX(classified_at) FROM classifications").fetchone()
        last = datetime.fromisoformat(row[0]) if row and row[0] else None
        recent_rows = conn.execute(
            "SELECT model_used FROM classifications WHERE classified_at >= ?",
            (cutoff.isoformat(sep=" ", timespec="seconds"),),
        ).fetchall()

    rate_per_min = len(recent_rows) / WINDOW_MIN
    remaining = TOTAL_TARGET - total
    eta_min = remaining / rate_per_min if rate_per_min > 0 else float("inf")

    by_model_recent: dict[str, int] = {}
    for (m,) in recent_rows:
        by_model_recent[m] = by_model_recent.get(m, 0) + 1

    fails_total = total_failure_count()
    fails_recent = failures_in_window(now, WINDOW_MIN)

    print(f"SUMMARY: {total}/{TOTAL_TARGET} ({total/TOTAL_TARGET:.1%}) | "
          f"rate {rate_per_min:.1f}/min (last {WINDOW_MIN}m, {len(recent_rows)} rows) | "
          f"ETA {eta_min:.0f} min" + (f" ({eta_min/60:.1f} h)" if eta_min != float('inf') else "") +
          f" | failures {fails_total} total, {fails_recent} in last {WINDOW_MIN}m")

    if by_model_recent:
        print(f"models (last {WINDOW_MIN}m): {by_model_recent}")

    if last:
        stale_s = (now - last).total_seconds()
        print(f"last write: {last} UTC ({stale_s:.0f}s ago)")

    alerts: list[str] = []
    if total < TOTAL_TARGET and rate_per_min < RATE_ALERT_BELOW:
        alerts.append(
            f"ALERT: rate {rate_per_min:.1f}/min is below threshold {RATE_ALERT_BELOW}/min"
        )
    if fails_recent > FAILURE_ALERT_ABOVE:
        alerts.append(
            f"ALERT: {fails_recent} failures in last {WINDOW_MIN}m "
            f"(threshold >{FAILURE_ALERT_ABOVE})"
        )
    for a in alerts:
        print(a)


if __name__ == "__main__":
    main()
