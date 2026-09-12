"""Standalone progress check for the Phase 2 classifier.

Fixes an earlier bug: the previous check anchored its 10-minute window on the
last-written row, so batch writes (25 rows landing within ~1 second) always
looked like "1,500 reviews/minute" and masked real stalls. This version
anchors the window on wall-clock now, so a stalled classifier reports a
low rate even if its last write was recent.

Prints a one-line SUMMARY and, if any threshold trips, one or more ALERT lines.

Thresholds:
    rate below 8/min over last 10 min  -> ALERT
    failures growing by 10+ in last 10 min  -> ALERT
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import CLASSIFIED_DB, CLASSIFY_FAILURES_LOG  # noqa: E402

TOTAL_TARGET = 5000
WINDOW_MIN = 10
RATE_ALERT_BELOW = 8         # reviews/min
FAILURE_ALERT_ABOVE = 10     # failures newly logged inside the window

# Cache the failure-log line-count between runs so we can detect deltas even
# though individual entries don't carry timestamps.
STATE_FILE = Path(__file__).resolve().parent.parent / "logs" / "check_state.json"


def load_prev_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def failure_count() -> int:
    if not CLASSIFY_FAILURES_LOG.exists():
        return 0
    with open(CLASSIFY_FAILURES_LOG, "r", encoding="utf-8") as f:
        return sum(1 for _ in f)


def main() -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)  # SQLite CURRENT_TIMESTAMP is naive UTC
    cutoff = now - timedelta(minutes=WINDOW_MIN)

    with sqlite3.connect(CLASSIFIED_DB) as conn:
        total = conn.execute("SELECT COUNT(*) FROM classifications").fetchone()[0]
        row = conn.execute("SELECT MAX(classified_at) FROM classifications").fetchone()
        last = datetime.fromisoformat(row[0]) if row and row[0] else None
        recent_rows = conn.execute(
            "SELECT model_used FROM classifications WHERE classified_at >= ?",
            (cutoff.isoformat(sep=" ", timespec="seconds"),),
        ).fetchall()

    # wall-clock-anchored rate: count rows landed in the last WINDOW_MIN minutes,
    # divide by WINDOW_MIN. NOT by (last - first) inside the window.
    rate_per_min = len(recent_rows) / WINDOW_MIN
    remaining = TOTAL_TARGET - total
    eta_min = remaining / rate_per_min if rate_per_min > 0 else float("inf")

    by_model_recent: dict[str, int] = {}
    for (m,) in recent_rows:
        by_model_recent[m] = by_model_recent.get(m, 0) + 1

    now_fails = failure_count()
    prev = load_prev_state()
    prev_fails = int(prev.get("failure_count", 0))
    prev_ts = prev.get("checked_at")
    fail_delta = now_fails - prev_fails

    # How long since last check — used to normalize the failure delta.
    if prev_ts:
        try:
            gap_min = max((now - datetime.fromisoformat(prev_ts)).total_seconds() / 60, 1e-6)
        except Exception:
            gap_min = None
    else:
        gap_min = None

    print(f"SUMMARY: {total}/{TOTAL_TARGET} ({total/TOTAL_TARGET:.1%}) | "
          f"rate {rate_per_min:.1f}/min (last {WINDOW_MIN}m, {len(recent_rows)} rows) | "
          f"ETA {eta_min:.0f} min" + (f" ({eta_min/60:.1f} h)" if eta_min != float('inf') else "") +
          f" | failures {now_fails} (+{fail_delta} since last check" +
          (f" ~{gap_min:.0f}m ago" if gap_min else "") + ")")

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
    # Only alert on failure growth measured in a comparable window
    if fail_delta > FAILURE_ALERT_ABOVE:
        alerts.append(
            f"ALERT: {fail_delta} new failures since last check "
            f"(threshold >{FAILURE_ALERT_ABOVE})"
        )
    for a in alerts:
        print(a)

    save_state({"failure_count": now_fails, "checked_at": now.isoformat()})


if __name__ == "__main__":
    main()
