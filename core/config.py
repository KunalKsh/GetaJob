"""Environment, paths and defaults. Every secret comes from environment variables (or .env locally)."""
from __future__ import annotations

import copy
import os
import secrets
import sys
from datetime import timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _default_data_dir() -> Path:
    if os.getenv("GETAJOB_DATA"):
        return Path(os.environ["GETAJOB_DATA"])
    if sys.platform.startswith("win") and os.getenv("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "GetaJob" / "data"
    return ROOT / "data"


DATA_DIR = _default_data_dir()
CACHE_DIR = DATA_DIR / "cache"
CONFIG_DIR = ROOT / "config"
FIXTURES_DIR = ROOT / "fixtures"
EMPLOYERS_PATH = CONFIG_DIR / "employers.yaml"


def database_url() -> str:
    """Postgres in production (DATABASE_URL from Neon/Render), SQLite file for local use and tests."""
    url = os.getenv("DATABASE_URL") or f"sqlite:///{(DATA_DIR / 'getajob.db').as_posix()}"
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


ADMIN_EMAIL = (os.getenv("ADMIN_EMAIL") or "kunalkaushal1120@gmail.com").strip().lower()
PUBLIC_URL = (os.getenv("PUBLIC_URL") or "").rstrip("/")
COOKIE_SECURE = (os.getenv("COOKIE_SECURE") or ("1" if PUBLIC_URL.startswith("https") else "0")) == "1"
APP_NAME = "GetaJob"

IST = timezone(timedelta(hours=5, minutes=30))  # India has no DST
USER_AGENT = ("GetaJob/1.0 (job discovery for individual job seekers; respects robots.txt; "
              "max 1 request/second per site)")

MAX_RESUMES = 5
MAX_RESUME_BYTES = 5 * 1024 * 1024
MAX_RESUME_PAGES = 6


def cron_secret() -> str:
    return os.getenv("CRON_SECRET") or ""


def secret_key() -> str:
    """SECRET_KEY from the environment; locally a random key is created once and kept in the data folder."""
    if os.getenv("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = DATA_DIR / "secret.key"
    try:
        return path.read_text().strip()
    except OSError:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        key = secrets.token_urlsafe(48)
        path.write_text(key)
        return key


API_KEYS = {
    "Adzuna": ["ADZUNA_APP_ID", "ADZUNA_APP_KEY"],
    "Jooble": ["JOOBLE_KEY"],
    "JSearch (RapidAPI)": ["RAPIDAPI_KEY"],
    "SerpAPI (Google Jobs)": ["SERPAPI_KEY"],
    "Anthropic (fit summaries)": ["ANTHROPIC_API_KEY"],
    "Email (SMTP)": ["SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"],
}


def key_status() -> dict[str, bool]:
    return {name: all(os.getenv(k) for k in keys) for name, keys in API_KEYS.items()}


# Per-user preferences (each person sets their own on the Profile page).
DEFAULT_PREFS: dict = {
    "confirmed": False,
    "profile": {},
    "families": [],            # job families chosen on the profile page (empty: worked out from the roles)
    "roles": [],
    "salary_min_lpa": None,
    "salary_max_lpa": None,
    "salary_hard_filter": False,
    "seniority_bands": None,   # None: no level filter (set on the profile page from years of experience)
    "role_types": ["Full-time"],
    "work_modes": [],          # onsite / hybrid / remote; empty means any
    "prefer_industries": [],
    "avoid_industries": [],
    "prefer_companies": [],
    "notice_period": "Immediate joiner",
    "exclude_companies": [],
    "exclude_title_words": [],
    "primary_cities": None,    # None: Delhi NCR (older profiles: their ncr_cities)
    "secondary_cities": None,
    "use_llm_summary": False,
}

# Site-wide settings (the admin changes these on the Admin page).
DEFAULT_SETTINGS: dict = {
    "max_age_days": 30,
    "bucket_size": 50,
    "refresh_hours": 12,
    "auto_refresh": True,
    "google_jobs_every_hours": 24,
    "api_budget": {"adzuna": 80, "jooble": 60, "jsearch": 8, "serpapi": 8},
    "verify_limit": 500,
    "max_query_roles": 14,
    "demo_mode": False,
}


def merged(defaults: dict, saved: dict | None) -> dict:
    out = copy.deepcopy(defaults)
    for k, v in (saved or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def ensure_dirs() -> None:
    for d in (DATA_DIR, CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)
