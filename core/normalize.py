"""One schema for every posting, plus salary / experience / work-mode / portal parsing."""
from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime
from urllib.parse import urlparse

from .config import IST
from .dates import parse_posted
from .locations import map_location
from .skills import extract_skills

PORTALS = ["LinkedIn", "Naukri", "Indeed", "IIMJobs/Hirist", "Instahyre", "Foundit", "Company/ATS"]
_PORTAL_DOMAINS = [
    ("LinkedIn", ("linkedin.com", "lnkd.in")),
    ("Naukri", ("naukri.com",)),
    ("Indeed", ("indeed.com", "indeed.co.in", "in.indeed.com")),
    ("IIMJobs/Hirist", ("iimjobs.com", "hirist.com", "hirist.tech", "updazz.com")),
    ("Instahyre", ("instahyre.com",)),
    ("Foundit", ("foundit.in", "monsterindia.com", "foundit.com")),
]
_PORTAL_NAMES = {
    "linkedin": "LinkedIn", "naukri": "Naukri", "indeed": "Indeed", "iimjobs": "IIMJobs/Hirist",
    "hirist": "IIMJobs/Hirist", "instahyre": "Instahyre", "foundit": "Foundit", "monster": "Foundit",
}

FIELDS = [
    "id", "title", "company", "city", "location_raw", "work_mode", "salary_text", "salary_min_lpa",
    "salary_max_lpa", "posted_date", "posted_date_confidence", "source_portal", "source_url", "apply_url",
    "description", "skills_extracted", "experience_required", "first_seen", "last_verified", "status",
]


def portal_from_url(url: str | None) -> str:
    host = (urlparse(url or "").hostname or "").lower()
    for portal, domains in _PORTAL_DOMAINS:
        if any(host == d or host.endswith("." + d) for d in domains):
            return portal
    return "Company/ATS"


def portal_from_name(name: str | None) -> str | None:
    low = (name or "").lower()
    for k, v in _PORTAL_NAMES.items():
        if k in low:
            return v
    return None


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>|</div>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "\n• ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


# ---------------------------------------------------------------- salary
_NUM = r"(\d+(?:[.,]\d+)*)"


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def parse_salary(text: str | None) -> tuple[float | None, float | None]:
    """Salary in lakhs per annum (LPA). Only INR; anything unclear returns (None, None)."""
    if not text:
        return None, None
    t = text.lower().replace("₹", " inr ").replace("rs.", " inr ").replace("–", "-").replace("—", "-")
    if re.search(r"\$|usd|eur|€|£|gbp|php|₱", t) or re.search(r"not disclosed|competitive|as per", t):
        return None, None
    per_month = bool(re.search(r"per month|/\s*month|a month|monthly|p\.?m\b|/mo\b", t))
    nums = re.findall(_NUM + r"\s*(lpa|lakhs?|lacs?|l\b|cr|crores?|k\b)?", t)
    vals = []
    for n, unit in nums:
        try:
            v = _num(n)
        except ValueError:
            continue
        unit = (unit or "").strip()
        if unit in ("cr", "crore", "crores"):
            v *= 100
        elif unit in ("lpa", "lakh", "lakhs", "lac", "lacs", "l"):
            pass
        elif unit == "k":
            v = v * 1000 / 1e5
        elif v >= 10000:  # plain rupees
            v = v / 1e5
        else:
            if not re.search(r"lpa|lakh|lac|\bl\b|ctc", t):
                continue  # bare small number with no unit: years, counts, etc.
        if per_month:
            v *= 12
        if 0.5 <= v <= 500:
            vals.append(round(v, 2))
    if not vals:
        return None, None
    if len(vals) == 1:
        return vals[0], vals[0]
    lo, hi = vals[0], vals[1]
    return (min(lo, hi), max(lo, hi))


# ---------------------------------------------------------------- experience
_EXP_RE = [
    re.compile(r"(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\s*\+?\s*(?:years?|yrs?)", re.I),
    re.compile(r"(?:minimum|min\.?|at least|atleast)\s*(?:of\s*)?(\d{1,2})\s*\+?\s*(?:years?|yrs?)", re.I),
    re.compile(r"(\d{1,2})\s*\+\s*(?:years?|yrs?)", re.I),
    re.compile(r"(\d{1,2})\s*(?:years?|yrs?)\s*(?:of\s*)?(?:relevant\s*|professional\s*|work\s*|total\s*)?experience", re.I),
]


def parse_experience(text: str | None) -> tuple[float | None, float | None, str]:
    if not text:
        return None, None, ""
    for i, rx in enumerate(_EXP_RE):
        m = rx.search(text)
        if not m:
            continue
        if i == 0:
            lo, hi = int(m.group(1)), int(m.group(2))
            if lo <= hi <= 30:
                return float(lo), float(hi), m.group(0)
        else:
            lo = int(m.group(1))
            if lo <= 30:
                return float(lo), None, m.group(0)
    return None, None, ""


def detect_work_mode(*texts: str | None) -> str:
    blob = " ".join(t or "" for t in texts).lower()
    if re.search(r"\bhybrid\b", blob):
        return "hybrid"
    if re.search(r"\bfully remote\b|\bremote\b|\bwork from home\b|\bwfh\b", blob):
        return "remote"
    if re.search(r"\bon-?site\b|\bin-?office\b|\bwork from office\b|\bwfo\b", blob):
        return "onsite"
    return "unknown"


def make_id(*parts: str) -> str:
    return hashlib.sha1("|".join(p or "" for p in parts).encode("utf-8")).hexdigest()[:16]


def make_job(*, source_name: str, native_id: str, title: str, company: str, location_raw: str,
             posted_raw=None, source_url: str, apply_url: str | None = None, description: str = "",
             salary_text: str | None = None, salary_min_lpa: float | None = None,
             salary_max_lpa: float | None = None, source_portal: str | None = None,
             links: list[dict] | None = None, extra: dict | None = None, work_mode: str | None = None,
             date_confidence: str | None = None, employer_industry: str | None = None,
             now: datetime | None = None) -> dict:
    """Build a normalized posting. posted_raw is parsed here so every adapter dates jobs the same way."""
    now = now or datetime.now(IST)
    desc = strip_html(description)
    posted, conf = parse_posted(posted_raw, now)
    if date_confidence and posted:
        conf = date_confidence
    if salary_min_lpa is None and salary_max_lpa is None:
        salary_min_lpa, salary_max_lpa = parse_salary(salary_text)
    exp_min, exp_max, exp_text = parse_experience(desc)
    loc = map_location(location_raw or "")
    portal = source_portal or portal_from_url(apply_url or source_url)
    all_links = links or [{"portal": portal, "url": source_url, "source": source_name}]
    return {
        "id": make_id(source_name, native_id or source_url),
        "native_id": native_id,
        "source_name": source_name,
        "title": re.sub(r"\s+", " ", (title or "").strip()),
        "company": re.sub(r"\s+", " ", (company or "").strip()) or "",
        "city": loc["city"],
        "cities": loc["cities"],
        "bucket": loc["bucket"],
        "location_raw": (location_raw or "").strip(),
        "work_mode": work_mode or detect_work_mode(location_raw, title, desc[:3000]),
        "salary_text": (salary_text or "").strip(),
        "salary_min_lpa": salary_min_lpa,
        "salary_max_lpa": salary_max_lpa,
        "posted_date": posted.isoformat() if posted else None,
        "posted_date_confidence": conf,
        "posted_raw": str(posted_raw) if posted_raw is not None else "",
        "source_portal": portal,
        "source_url": source_url,
        "apply_url": apply_url or source_url,
        "links": all_links,
        "description": desc,
        "skills_extracted": extract_skills(desc + " " + (title or "")),
        "experience_required": exp_text,
        "exp_min": exp_min,
        "exp_max": exp_max,
        "employer_industry": employer_industry or "",
        "first_seen": now.isoformat(timespec="seconds"),
        "last_seen": now.isoformat(timespec="seconds"),
        "last_verified": None,
        "status": "unchecked",
        "verify_note": "",
        "flags": [],
        "reposted": False,
        "repost_note": "",
        "manual_verified": False,
        "new_since_refresh": True,
        "extra": extra or {},
    }
