# Pulse — Review Mining for Quick-Commerce Churn Root-Cause Analysis

Pulse pulls Play Store reviews for Swiggy (Instamart is inside the same app), classifies each one into a fixed complaint taxonomy using Groq's hosted models, and rolls the results up into dashboard-ready tables plus a per-theme revenue-at-risk estimate.

**The question I wanted to answer:** which operational issues actually drive negative reviews on a quick-commerce app, and how much revenue is at risk from each one if it doesn't get fixed?

## Why Swiggy and not Blinkit

The original scope named Blinkit. I switched after a quick probe: Blinkit gets around 900 Play Store reviews a day, which means a 5,000-review budget covers about five days. That's too narrow for any trend analysis, and Play Store's newest-first pagination doesn't give you a way around it — you scrape recent reviews or nothing.

Swiggy's review rate is closer to 335/day. A 5,000-review sample naturally spans ~2 weeks; if I scrape wide (~30-40k) and downsample, I can cover roughly three months, which is enough for the analysis to say something real. The full write-up on this decision (and everything else that went sideways) is in [LESSONS_LEARNED.md](LESSONS_LEARNED.md).

---

## Pipeline

| Phase | Script | Output |
|---|---|---|
| 1. Scrape | `scripts/01_scrape_reviews.py` | `data/raw_reviews_full.csv` (the full 40k pull, immutable) and `data/raw_reviews.csv` (5k downsampled slice, fed to Phase 2) |
| 2. Classify | `scripts/02_classify_reviews.py` | `data/classified_reviews.db` |
| 3. Aggregate | `scripts/03_aggregate.py` | `exports/*.csv`, `exports/pulse_dashboard_tables.xlsx` |
| 4. Revenue-at-risk | `scripts/04_revenue_at_risk.py` | `data/revenue_at_risk.csv` |

Each stage reads the previous stage's checkpoint, so a crash or a rate-limit hiccup never costs more than one batch of work.

Phase 1 does two things in sequence: scrape as many reviews as Play Store will serve (up to `SCRAPE_TARGET`), then uniform-random downsample to `CLASSIFY_TARGET` rows for classification. Uniform-random matters because it preserves the true per-day density, so the trend charts reflect real review volume instead of a flat sampling artefact.

Phase 2 is the interesting one operationally. It:

- Sends `CLASSIFY_BATCH_SIZE` reviews per Groq API call (default 5), so RPM usage on the free tier is one-fifth of what a naïve per-review loop would use.
- Runs `CLASSIFY_CONCURRENCY` batches in flight at once via `asyncio` and `AsyncGroq`, so wall-clock throughput sits near the RPM ceiling instead of well below it.
- Walks a `MODEL_CHAIN` of `(primary, fallback)` pairs. When both models in the current pair start returning 429s in tandem — which happens on Groq's free tier once a per-model daily TPD cap kicks in — the classifier advances to the next pair on its own and keeps going. No manual restart needed.
- Writes to SQLite every 25 successful classifications, and skips any `review_id` already in the table on restart, so a crash or a `Ctrl+C` costs at most one checkpoint of work.
- Ends every run with a two-line `RUN SUMMARY` in the log naming rows written, failures, elapsed time, chain advances, and the per-model breakdown for that run.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # PowerShell / cmd
# source .venv/bin/activate      # bash

pip install -r requirements.txt

copy .env.example .env           # then fill in GROQ_API_KEY
```

Free Groq API key: https://console.groq.com/keys.

## Running

```bash
# Phase 1: scrape ~40k Swiggy reviews and downsample to 5k.
python scripts/01_scrape_reviews.py

# Phase 2: run a 20-review smoke test first, then the full classification.
python scripts/02_classify_reviews.py --limit 20
python scripts/02_classify_reviews.py

# Phase 3: build the four flat dashboard tables + xlsx bundle.
python scripts/03_aggregate.py

# Phase 4: revenue-at-risk ranking.
python scripts/04_revenue_at_risk.py
```

Phase 2 is idempotent. It skips any `review_id` already in the SQLite table, so if it dies mid-run, just restart it.

## Tests

Small pytest suite for the aggregation and revenue-at-risk layers, which are the two places where a silent arithmetic regression would produce wrong dashboard numbers without any visible error.

```bash
python -m pytest tests/
```

24 tests, runs in under a second. Uses tmp fixtures for the CSV + SQLite paths, so no test touches production data.

## Taxonomy

Every review is assigned exactly one of:

1. Late/delayed delivery
2. Stockouts / item unavailability
3. Pricing / hidden charges
4. App bugs / payment failures
5. Rider / delivery-person behavior
6. Customer service / refunds
7. Product quality
8. Other / positive

The taxonomy is fixed in `scripts/config.py`. The model is told not to invent categories and to default to "Other / positive" when nothing else fits.

## Dashboard tables (`exports/`)

- **monthly_theme_volume.csv** — `(month, category, review_count)`. Trend lines.
- **low_star_theme_share.csv** — each theme's share of 1-2 star reviews.
- **severity_weighted_score.csv** — `avg_severity × volume` per theme. Ranking metric.
- **rating_distribution_by_theme.csv** — `(category, rating, review_count)`. Distribution charts.
- **pulse_dashboard_tables.xlsx** — all four as tabs, for one-click Power BI or Tableau import.

## Revenue-at-risk assumptions

```
revenue_at_risk_inr =
    (1-star review count for theme)
  * ASSUMED_CHURN_RATE
  * ASSUMED_AVG_ORDER_VALUE_INR
  * ASSUMED_ORDER_FREQUENCY_MULTIPLIER
```

Values live at the top of `scripts/04_revenue_at_risk.py`:

| Constant | Value | Source |
|---|---|---|
| `ASSUMED_CHURN_RATE` | 0.40 | Assumption. A 1-star review on a delivery app is a strong dissatisfaction signal. Industry rules of thumb range 25-60%; I picked the middle. |
| `ASSUMED_AVG_ORDER_VALUE_INR` | ₹600 | Rounded down from Blinkit's ~₹617 AOV reported in Zomato's Q4 FY24 investor deck. Using it as a conservative proxy for Swiggy since no public Swiggy AOV number was sourced. |
| `ASSUMED_ORDER_FREQUENCY_MULTIPLIER` | 24 | Assumption. ~2 orders/month for an active user over a 12-month churn horizon → 24 forgone orders per churned user. |

The output is a directional ranking of themes by revenue at risk, not an audited GMV forecast. What matters is the ordering, not the absolute rupee figure.

## Recommendation memo

The full memo is at [`exports/recommendation_memo.md`](exports/recommendation_memo.md). It picks the top complaint theme, quotes the revenue-at-risk figure, and proposes an operational fix backed by the ranking.

## Lessons learned

The build did not go to plan. Deprecated models, tighter free-tier rate limits than I estimated, an app whose review firehose was too big for the requested time window, and a monitoring bug that quietly reported healthy numbers during a stall — the full postmortem, and what I'd do differently on a rebuild, is in [LESSONS_LEARNED.md](LESSONS_LEARNED.md).

## Results (from the run in this repo)

- **Sample:** 5,000 reviews spanning 2026-06-14 to 2026-09-10 (87 days). Uniform-random downsample of a 40,000-review pull.
- **Top theme by revenue-at-risk:** Customer service / refunds. 402 one-star reviews, average severity 4.37 / 5, ≈ ₹23.2 lakh at risk.
- **Full ranking:** [`data/revenue_at_risk.csv`](data/revenue_at_risk.csv).

## Model provenance (Phase 2)

Groq's free-tier rate limits are per-model, so no single model can carry a 5k run without hitting a daily cap. The classifier's `MODEL_CHAIN` is a list of `(primary, fallback)` pairs; when both models in the current pair start 429-ing together, `_ChainState` advances to the next pair on its own. Every row records which model actually produced it in the `model_used` column.

Ordered so the fastest fresh combo is tried first:

| Rank | Primary | Fallback |
|---|---|---|
| 1 | openai/gpt-oss-20b | qwen/qwen3.8-27b |
| 2 | openai/gpt-oss-safeguard-20b | openai/gpt-oss-20b |
| 3 | openai/gpt-oss-120b | groq/compound-mini |
| 4 | qwen/qwen3.8-27b | qwen/qwen3.6-27b |

The initial 5k run in this repo cycled through most of these pairs as buckets throttled. The final per-model split (from `data/classified_reviews.db`):

| Model | Rows | Share |
|---|---|---|
| openai/gpt-oss-120b | 1,509 | 30.2% |
| openai/gpt-oss-20b | 1,502 | 30.0% |
| openai/gpt-oss-safeguard-20b | 999 | 20.0% |
| qwen/qwen3.8-27b | 894 | 17.9% |
| qwen/qwen3.6-27b | 95 | 1.9% |
| groq/compound-mini | 1 | ~0% |

The label schema (`category`, `severity`, `justification`) is identical across every model. Any row whose category wasn't in the taxonomy is rejected and re-classified rather than silently accepted, so the mixed provenance doesn't leak into the analysis. The full write-up of how the rotation played out and what I'd design differently is in the lessons doc.

## Repo layout

```
pulse/
  scripts/
    config.py                    # taxonomy, paths, model chain, batch/concurrency knobs
    01_scrape_reviews.py
    02_classify_reviews.py       # async + batched + chain-rotating classifier
    03_aggregate.py
    04_revenue_at_risk.py
    check_progress.py            # standalone monitor for a live Phase 2 run
  tests/
    conftest.py                  # loads the numbered scripts as importable modules
    test_aggregate.py            # 13 tests for the aggregation layer
    test_revenue_at_risk.py      # 11 tests for the revenue-at-risk arithmetic
  data/                          # CSV / SQLite checkpoints (gitignored)
  exports/                       # dashboard tables + memo
  logs/                          # scrape log, classification failures with timestamps
  requirements.txt
  .env.example
```
