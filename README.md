# Pulse — Review Mining for Quick-Commerce Churn Root-Cause Analysis

Pulse pulls Play Store reviews for Swiggy (which includes Instamart, its quick-commerce arm), classifies each into a fixed complaint taxonomy using Groq's Llama models, and rolls the results up into dashboard-ready tables plus a per-theme revenue-at-risk estimate.

## App choice

Original scope named Blinkit. Switched to Swiggy after empirical probing showed Blinkit gets ~900 Play Store reviews/day, meaning 5k reviews cover only ~5 days — too narrow for the trend analysis in the deliverable. Swiggy's rate is ~335/day, so 5k reviews naturally cover ~2 weeks, and scraping wide (~30-40k) covers ~3 months. This is documented so the app swap is defensible in an interview.

**Business question:** *Which operational issues drive negative reviews of a quick-commerce app, and how much revenue is at risk from each if left unaddressed?*

---

## Pipeline

| Phase | Script | Output |
|---|---|---|
| 1. Scrape | `scripts/01_scrape_reviews.py` | `data/raw_reviews_full.csv` (full pull, immutable) + `data/raw_reviews.csv` (5k downsampled slice fed to Phase 2) |
| 2. Classify | `scripts/02_classify_reviews.py` | `data/classified_reviews.db` |
| 3. Aggregate | `scripts/03_aggregate.py` | `exports/*.csv`, `exports/pulse_dashboard_tables.xlsx` |
| 4. Revenue-at-risk | `scripts/04_revenue_at_risk.py` | `data/revenue_at_risk.csv` |

Every stage reads from the previous stage's checkpoint file, so a crash or rate limit never costs more than one batch.

Phase 1 scrapes up to `SCRAPE_TARGET` reviews newest-first, then uniform-random downsamples to `CLASSIFY_TARGET` rows for classification. Uniform-random preserves the true per-day review density, so the resulting trend charts reflect real volume rather than a flat sampling artefact.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # PowerShell / cmd
# source .venv/bin/activate      # bash

pip install -r requirements.txt

copy .env.example .env           # then fill in GROQ_API_KEY
```

Get a free Groq API key at https://console.groq.com/keys.

## Running

```bash
# Phase 1 — scrape 3-5k Blinkit reviews from the last 18 months.
python scripts/01_scrape_reviews.py

# Phase 2 — smoke test on 20 reviews first, then run the full classification.
python scripts/02_classify_reviews.py --limit 20
python scripts/02_classify_reviews.py

# Phase 3 — build the four flat dashboard tables.
python scripts/03_aggregate.py

# Phase 4 — revenue-at-risk ranking.
python scripts/04_revenue_at_risk.py
```

Phase 2 is idempotent — it skips any `review_id` already in the SQLite table, so if it dies mid-run, just re-run it.

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

The taxonomy is fixed in `scripts/config.py`. The model is instructed not to invent categories and to default to "Other / positive" when nothing else fits.

## Dashboard tables (`exports/`)

- **monthly_theme_volume.csv** — `(month, category, review_count)`. Trend lines.
- **low_star_theme_share.csv** — each theme's share of 1-2 star reviews.
- **severity_weighted_score.csv** — `avg_severity * volume` per theme. Ranking metric.
- **rating_distribution_by_theme.csv** — `(category, rating, review_count)`. Distribution charts.
- **pulse_dashboard_tables.xlsx** — all four as tabs, for one-click Power BI / Tableau import.

## Revenue-at-risk assumptions

```
revenue_at_risk_inr =
    (1-star review count for theme)
    * ASSUMED_CHURN_RATE
    * ASSUMED_AVG_ORDER_VALUE_INR
    * ASSUMED_ORDER_FREQUENCY_MULTIPLIER
```

Current values (edit at the top of `scripts/04_revenue_at_risk.py`):

| Constant | Value | Source |
|---|---|---|
| `ASSUMED_CHURN_RATE` | 0.40 | Assumption. A 1-star review on a delivery app is a strong dissatisfaction signal; industry rules-of-thumb range 25-60%. |
| `ASSUMED_AVG_ORDER_VALUE_INR` | ₹600 | Rounded down from Blinkit AOV of ~₹617 reported in Zomato's Q4 FY24 investor deck (quarter ending Mar-2024). |
| `ASSUMED_ORDER_FREQUENCY_MULTIPLIER` | 24 | Assumption. Assumes an active user places ~2 orders/month and the churn horizon is 12 months → 24 orders forgone per churned user. |

The output is a directional ranking of themes by revenue at risk, not an audited GMV forecast. The value of the number is the **relative ordering** it produces, not the absolute rupee figure.

## Recommendation memo

The recommendation memo lives at [`exports/recommendation_memo.md`](exports/recommendation_memo.md). It ranks the top complaint theme, cites the revenue-at-risk figure, and proposes an operational fix.

## Retrospective — issues, fixes, and lessons

The full build did not go to plan. Deprecated models, tighter free-tier rate limits than expected, a target app whose review firehose was too big for the requested time window, and a progress-monitoring bug that quietly reported healthy numbers during a stall — all documented, with what we did about them and what a rebuild should do differently, in [`LESSONS_LEARNED.md`](LESSONS_LEARNED.md).

## Results (from the run in this repo)

- **Sample:** 5,000 reviews, 2026-06-14 → 2026-09-10 (87 days), uniform-random downsample of a 40,000-review scrape.
- **Top theme by revenue-at-risk:** Customer service / refunds — 402 one-star reviews, average severity 4.37 / 5, ≈ ₹23.2 lakh at risk.
- **Full ranking:** see [`data/revenue_at_risk.csv`](data/revenue_at_risk.csv).

## Model provenance (Phase 2)

Groq's free-tier per-model rate limits meant no single model could carry the full 5k. The classifier was rotated across models as buckets throttled; every row records which model classified it in the `model_used` column. Final split:

| Model | Rows | Share |
|---|---|---|
| openai/gpt-oss-120b | 1,509 | 30.2% |
| openai/gpt-oss-20b | 1,502 | 30.0% |
| openai/gpt-oss-safeguard-20b | 999 | 20.0% |
| qwen/qwen3.8-27b | 894 | 17.9% |
| qwen/qwen3.6-27b | 95 | 1.9% |
| groq/compound-mini | 1 | ~0% |

The label schema (`category`, `severity`, `justification`) is identical across all models and validated post-hoc against the fixed taxonomy — any row whose category was not in the taxonomy was rejected and re-classified rather than silently accepted. The mixed-model provenance is a design choice, not a defect: it's what enabled the full 5k to be labeled on the free tier.

## Repo layout

```
pulse/
  scripts/
    config.py                    # taxonomy, paths, model IDs — shared
    01_scrape_reviews.py
    02_classify_reviews.py
    03_aggregate.py
    04_revenue_at_risk.py
  data/                          # CSV / SQLite checkpoints (gitignored)
  exports/                       # dashboard-ready outputs (gitignored)
  logs/                          # scrape log + classification failures
  requirements.txt
  .env.example
```
