"""Settings in one place. Every value can be overridden with an environment variable."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Where the announcement text (with the questionnaire links) lives.
ANNOUNCEMENTS_DATASET = os.environ.get("UQ_ANNOUNCEMENTS", "abigailhaddad/usajobs-scraping")
# Where the finished questionnaires are published.
HF_DATASET = os.environ.get("UQ_HF_DATASET", "abigailhaddad/usajobs-questionnaires")

# Politeness budget for fetching from the portals. Conservative on purpose.
WORKERS = int(os.environ.get("UQ_WORKERS", "2"))
MAX_REQUESTS_PER_DAY = int(os.environ.get("UQ_MAX_REQUESTS_PER_DAY", "3000"))
DELAY_MIN_SECONDS = float(os.environ.get("UQ_DELAY_MIN", "4"))
DELAY_MAX_SECONDS = float(os.environ.get("UQ_DELAY_MAX", "9"))
PAGE_TIMEOUT_MS = int(os.environ.get("UQ_PAGE_TIMEOUT_MS", "30000"))
# How long to wait for the app to replace its loading skeleton with the questionnaire.
RENDER_WAIT_MS = int(os.environ.get("UQ_RENDER_WAIT_MS", "30000"))

# Scope: questionnaires from announcements first seen in this year or later. Earlier years are not planned
# (see HANDOFF.md). `scripts/backfill.py --years ...` overrides it for a one-off look.
MIN_YEAR = int(os.environ.get("UQ_MIN_YEAR", "2025"))

# A plain, honest identifier for plain HTTP requests (the Monster preview pages).
# The USA Staffing pages are loaded with Playwright's own default Chromium, unmodified.
HTTP_USER_AGENT = os.environ.get(
    "UQ_USER_AGENT", "usajobs-questionnaires/0.1 (public-records archive; polite, rate-limited)"
)

STATE_FILE = Path(os.environ.get("UQ_STATE_FILE", ROOT / "state" / "attempts.jsonl"))
BUILD_DIR = Path(os.environ.get("UQ_BUILD_DIR", ROOT / "build"))
DATA_DIR = ROOT / "data"
