"""Posted-date parsing (absolute and relative) in Asia/Kolkata time, plus freshness tiers.

Rule: never guess. If a value can't be read as a date, the result is (None, "unknown").
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime

from .config import IST

EXACT, RELATIVE, AGGREGATOR, USER, UNKNOWN = "exact", "relative", "aggregator", "user", "unknown"
CONFIDENCE_RANK = {EXACT: 4, USER: 4, RELATIVE: 3, AGGREGATOR: 2, UNKNOWN: 0}

_WORDNUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
            "eight": 8, "nine": 9, "ten": 10, "few": 2, "several": 3}
_REL_RE = re.compile(
    r"(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|few|several)\s*(\+)?\s*"
    r"(minute|min|hour|hr|day|week|wk|month|mo)s?\b\s*(?:ago)?", re.I)


def today_ist(now: datetime | None = None) -> date:
    return (now or datetime.now(IST)).astimezone(IST).date()


def _to_ist_date(dt: datetime) -> date:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(IST).date()


def parse_posted(value, now: datetime | None = None) -> tuple[date | None, str]:
    """Return (date in IST, confidence)."""
    now = now or datetime.now(IST)
    today = today_ist(now)
    if value is None or value == "":
        return None, UNKNOWN
    if isinstance(value, datetime):
        return _to_ist_date(value), EXACT
    if isinstance(value, date):
        return value, EXACT
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:  # milliseconds
            ts /= 1000
        if ts < 9e8:  # before 1998: not a real posting timestamp
            return None, UNKNOWN
        return datetime.fromtimestamp(ts, IST).date(), EXACT

    s = str(value).strip()
    low = s.lower()
    if re.fullmatch(r"\d{10,13}", s):
        return parse_posted(int(s), now)

    # ISO forms: 2026-10-14, 2026-10-14T03:53:37-04:00, 2026-10-14T03:53:37.000Z
    m = re.match(r"^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)\s*(Z|[+-]\d{2}:?\d{2})?)?$", s)
    if m:
        if not m.group(2):
            try:
                return date.fromisoformat(m.group(1)), EXACT
            except ValueError:
                return None, UNKNOWN
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return _to_ist_date(dt), EXACT
        except ValueError:
            return None, UNKNOWN

    # Relative forms
    if re.search(r"\b(just (?:now|posted)|today|few (?:minutes|hours)|an? hour|hours? ago|minutes? ago)\b", low) \
            and "+" not in low:
        if not re.search(r"\d+\s*(day|week|month)", low):
            return today, RELATIVE
    if "yesterday" in low:
        return today - timedelta(days=1), RELATIVE
    m = _REL_RE.search(low)
    if m and ("ago" in low or "posted" in low or "+" in low or low.strip().startswith(m.group(0).strip())):
        n_raw, plus, unit = m.group(1), m.group(2), m.group(3)
        n = int(n_raw) if n_raw.isdigit() else _WORDNUM.get(n_raw, 1)
        unit = unit[:2]
        if unit in ("mi", "ho", "hr"):
            days = 0
        elif unit == "da":
            days = n
        elif unit in ("we", "wk"):
            days = 7 * n
        else:
            days = 30 * n
        if plus:  # "30+ days ago": strictly older than n days
            days += 1
        return today - timedelta(days=days), RELATIVE

    # RFC 2822 (email headers, RSS)
    try:
        dt = parsedate_to_datetime(s)
        if dt:
            return _to_ist_date(dt), EXACT
    except (TypeError, ValueError, IndexError):
        pass

    # Written dates: "14 Oct 2026", "Oct 14, 2026", "14/10/2026" (Indian day-first order)
    cleaned = re.sub(r"^(posted|published|date posted)\s*(on)?\s*[:\-]?\s*", "", s, flags=re.I).strip().rstrip(".")
    cleaned = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", cleaned)
    for fmt in ("%d %b %Y", "%d %B %Y", "%d %b, %Y", "%d %B, %Y", "%b %d, %Y", "%B %d, %Y", "%b %d %Y",
                "%B %d %Y", "%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date(), EXACT
        except ValueError:
            continue
    return None, UNKNOWN


def age_days(d: date | str | None, today: date | None = None) -> int | None:
    if not d:
        return None
    if isinstance(d, str):
        try:
            d = date.fromisoformat(d[:10])
        except ValueError:
            return None
    return ((today or today_ist()) - d).days


TIERS = [(1, 3, "≤3 days"), (2, 7, "≤7 days"), (3, 15, "≤15 days"), (4, 30, "≤30 days")]


def tier_for_age(age: int | None, max_age: int = 30) -> int | None:
    """1..4, or None when unknown or older than max_age."""
    if age is None or age > max_age:
        return None
    for tier, limit, _ in TIERS:
        if age <= limit:
            return tier
    return 4


def humanize_age(age: int | None) -> str:
    if age is None:
        return "date unknown"
    if age <= 0:
        return "today"
    if age == 1:
        return "yesterday"
    return f"{age} days ago"
