from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
EXPORTS_DIR = PROJECT_ROOT / "exports"

RAW_REVIEWS_FULL_CSV = DATA_DIR / "raw_reviews_full.csv"
RAW_REVIEWS_CSV = DATA_DIR / "raw_reviews.csv"
CLASSIFIED_DB = DATA_DIR / "classified_reviews.db"
REVENUE_AT_RISK_CSV = DATA_DIR / "revenue_at_risk.csv"

CLASSIFY_FAILURES_LOG = LOGS_DIR / "classify_failures.jsonl"
SCRAPE_LOG = LOGS_DIR / "scrape.log"

APP_PACKAGE = "in.swiggy.android"
APP_NAME = "Swiggy"
APP_COUNTRY = "in"
APP_LANG = "en"

SCRAPE_TARGET = 40000
CLASSIFY_TARGET = 5000
WINDOW_MONTHS = 18
DOWNSAMPLE_SEED = 42
TARGET_REVIEWS = SCRAPE_TARGET

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

PRIMARY_MODEL = "openai/gpt-oss-20b"
FALLBACK_MODEL = "qwen/qwen3.8-27b"
BATCH_SIZE = 25
CLASSIFY_BATCH_SIZE = 5
