import sys
from pathlib import Path

# Play Store reviews carry emoji and non-Latin scripts (Hindi, Kannada, Arabic).
# Windows' default console codec is cp1252, which can't encode any of that, so
# any print() of review text raises UnicodeEncodeError. Reconfigure stdout and
# stderr to UTF-8 at import time so every script that reads from config gets
# safe printing without needing to be invoked with `python -X utf8`.
# No-op on POSIX (where stdout is already UTF-8) and when stdout is a piped or
# captured stream without a .reconfigure method.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass


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

MODEL_CHAIN: list[tuple[str, str]] = [
    ("openai/gpt-oss-20b", "qwen/qwen3.8-27b"),
    ("openai/gpt-oss-safeguard-20b", "openai/gpt-oss-20b"),
    ("openai/gpt-oss-120b", "groq/compound-mini"),
    ("qwen/qwen3.8-27b", "qwen/qwen3.6-27b"),
]

BATCH_SIZE = 25
CLASSIFY_BATCH_SIZE = 5
CLASSIFY_CONCURRENCY = 4
