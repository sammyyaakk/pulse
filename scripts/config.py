"""Shared constants for the Pulse pipeline.

Kept in one place so every stage agrees on paths, the taxonomy, and the target app.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
EXPORTS_DIR = PROJECT_ROOT / "exports"

RAW_REVIEWS_FULL_CSV = DATA_DIR / "raw_reviews_full.csv"  # every review the scraper pulled
RAW_REVIEWS_CSV = DATA_DIR / "raw_reviews.csv"            # downsampled slice fed to classification
CLASSIFIED_DB = DATA_DIR / "classified_reviews.db"
REVENUE_AT_RISK_CSV = DATA_DIR / "revenue_at_risk.csv"

CLASSIFY_FAILURES_LOG = LOGS_DIR / "classify_failures.jsonl"
SCRAPE_LOG = LOGS_DIR / "scrape.log"

# ---------------------------------------------------------------------------
# Target app
# ---------------------------------------------------------------------------
# Swiggy: chosen over Blinkit/Zomato because its lower daily review volume lets
# 5k reviews cover ~3 months instead of ~5 days — actual trend analysis possible.
# Instamart is inside the main Swiggy app, so reviews cover both food + quick-commerce.
APP_PACKAGE = "in.swiggy.android"
APP_NAME = "Swiggy"
APP_COUNTRY = "in"
APP_LANG = "en"

# ---------------------------------------------------------------------------
# Scrape parameters
# ---------------------------------------------------------------------------
# Scrape wide, then downsample. Play Store paginates newest-first with no
# date-range filter, so this is the only way to get a sample that spans months
# instead of days.
SCRAPE_TARGET = 40000              # upper bound; stops earlier if Play Store runs out
CLASSIFY_TARGET = 5000             # downsampled row count written to raw_reviews.csv
WINDOW_MONTHS = 18                 # safety cutoff — will not be hit in practice
DOWNSAMPLE_SEED = 42               # keep sampling reproducible

# Back-compat alias (some earlier code referenced TARGET_REVIEWS)
TARGET_REVIEWS = SCRAPE_TARGET

# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------
# Fixed taxonomy. Do NOT let the model invent new categories.
TAXONOMY = [
    "Late/delayed delivery",
    "Stockouts / item unavailability",
    "Pricing / hidden charges",
    "App bugs / payment failures",
    "Rider / delivery-person behavior",
    "Customer service / refunds",
    "Product quality",
    "Other / positive",
]

# The brief named llama-3.3-70b-versatile / llama-3.1-8b-instant; Groq deprecated
# the whole Llama 3.x family before this project ran.
#
# Model journey during Phase 2 (all recorded per-row in the `model_used` column):
#   1. openai/gpt-oss-120b — sharp labels, but Groq free-tier daily quota
#      throttled it to ~8-17 rpm.
#   2. openai/gpt-oss-20b — faster; ran ~975 rows before that bucket also hit
#      TPD/RPD caps and both gpt-oss models started returning 429s in tandem.
#   3. qwen/qwen3.8-27b + qwen/qwen3.6-27b — separate rate-limit bucket;
#      hit ~3500 rows before that pair also throttled.
#   4. openai/gpt-oss-safeguard-20b + openai/gpt-oss-20b — ran the classifier
#      from ~3,520 to ~4,520 before that pair started throttling too.
#   5. openai/gpt-oss-120b + groq/compound-mini — carried the run from
#      ~4,520 to ~4,756 before the 120b family throttled again (compound is a
#      120b agent under the hood; it shares the same bucket).
#   6. openai/gpt-oss-20b + qwen/qwen3.8-27b (current) — used as the mop-up
#      pair for the final 244 reviews. Both buckets showed fresh capacity in
#      a live probe after the 120b family throttled.
# The mixed-model provenance is a defensible design choice given Groq's
# per-model rate limits; the label schema is identical across all models.
PRIMARY_MODEL = "openai/gpt-oss-20b"
FALLBACK_MODEL = "qwen/qwen3.8-27b"
BATCH_SIZE = 25  # Classify this many reviews before writing to SQLite
