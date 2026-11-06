"""Pick the top 50 per list: verified, dated, ≤30 days, filled tier 1 → 4, ranked by fit inside a tier.

Each person has two lists: their first-choice cities and their other cities (both chosen on the profile page).
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date

from .dates import UNKNOWN, age_days, tier_for_age, today_ist
from .dedup import norm_company
from .locations import MAJOR_METROS, NCR_CITIES, expand, region_label
from .relevance import is_relevant
from .taxonomy import band_years, title_level
from .verify import COUNTABLE

LISTS = ("primary", "secondary")

REASON_TEXT = {
    "not_verified": "not verified yet or failed verification",
    "date_unknown": "posting date could not be confirmed",
    "too_old": "older than {max_age} days",
    "excluded_company": "excluded company",
    "excluded_title": "title or experience outside your seniority levels, or a title word you excluded",
    "salary": "stated salary outside your range",
    "no_city": "no target city",
    "off_target": "outside the job types and roles you chose",
}


def _excluded_company(company: str, excludes: list[str]) -> bool:
    nc = norm_company(company)
    return any(e and norm_company(e) and norm_company(e) in nc for e in excludes)


def _excluded_title(title: str, words: list[str]) -> bool:
    t = (title or "").lower()
    return any(re.search(r"\b" + re.escape(w.lower()) + r"\b", t) for w in words if w)


def city_lists(prefs: dict) -> tuple[list[str], list[str]]:
    """(first-choice cities, other cities). Older profiles stored them as NCR / metro lists."""
    p = prefs.get("primary_cities")
    if p is None:
        p = prefs.get("ncr_cities") if prefs.get("ncr_cities") is not None else NCR_CITIES
    q = prefs.get("secondary_cities")
    if q is None:
        q = prefs.get("metro_cities") if prefs.get("metro_cities") is not None else MAJOR_METROS[:4]
    return list(p or []), [c for c in (q or []) if c not in (p or [])]


def list_of(job: dict, prefs: dict) -> str | None:
    primary, secondary = city_lists(prefs)
    jc = set(job.get("cities") or ([job["city"]] if job.get("city") else []))
    if not jc:
        return None
    if jc & expand(primary):
        return "primary"
    if jc & expand(secondary):
        return "secondary"
    return None


def _outside_levels(job: dict, prefs: dict) -> bool:
    title = job.get("title", "")
    types = prefs.get("role_types")
    if types is not None and "Internship" not in types and re.search(r"\bintern(ship)?\b", title, re.I):
        return True
    bands = prefs.get("seniority_bands")
    if not bands:
        return False
    _, fits = title_level(title)
    if fits and not set(fits) & set(bands):
        return True
    lo, hi = band_years(bands)
    emin, emax = job.get("exp_min"), job.get("exp_max")
    if emin is not None and emin > hi + 1:
        return True
    if emax is not None and emax < lo - 1:
        return True
    return False


def ineligible_reason(job: dict, prefs: dict, today: date) -> str | None:
    max_age = int(prefs.get("max_age_days") or 30)
    if not job.get("bucket") or list_of(job, prefs) is None:
        return "no_city"
    if _excluded_company(job.get("company", ""), prefs.get("exclude_companies") or []):
        return "excluded_company"
    if _excluded_title(job.get("title", ""), prefs.get("exclude_title_words") or []) or _outside_levels(job, prefs):
        return "excluded_title"
    if not job.get("source_name") == "manual" and not is_relevant(job.get("title", ""), prefs.get("roles") or [],
                                                                    prefs.get("families")):
        return "off_target"
    if prefs.get("salary_hard_filter"):
        smin, smax = job.get("salary_min_lpa"), job.get("salary_max_lpa")
        if smin is not None or smax is not None:
            lo, hi = smin or smax, smax or smin
            if hi < float(prefs.get("salary_min_lpa") or 0) or lo > float(prefs.get("salary_max_lpa") or 1e9):
                return "salary"
    if not job.get("posted_date") or job.get("posted_date_confidence") == UNKNOWN:
        return "date_unknown"
    a = age_days(job["posted_date"], today)
    if a is None or a > max_age:
        return "too_old"
    if not (job.get("status") in COUNTABLE or job.get("manual_verified")):
        return "not_verified"
    return None


def sort_key(job: dict, today: date):
    tier = tier_for_age(age_days(job.get("posted_date"), today)) or 9
    return (tier, -(job.get("fit_score") or 0), job.get("posted_date") or "", job.get("title") or "")


def select_buckets(jobs: list[dict], prefs: dict, today: date | None = None) -> dict:
    today = today or today_ist()
    size = int(prefs.get("bucket_size") or 50)
    max_age = int(prefs.get("max_age_days") or 30)
    out = {}
    primary, secondary = city_lists(prefs)
    labels = {"primary": region_label(primary), "secondary": region_label(secondary)}
    for bucket in LISTS:
        pool = [j for j in jobs if list_of(j, prefs) == bucket and j.get("status") not in ("expired", "dead")]
        ok, reasons = [], Counter()
        for j in pool:
            r = ineligible_reason(j, prefs, today)
            if r:
                reasons[r] += 1
            else:
                ok.append(j)
        ok.sort(key=lambda j: (sort_key(j, today)[0], sort_key(j, today)[1], -_ord(j.get("posted_date")),
                               j.get("title") or ""))
        chosen = ok[:size]
        tiers = Counter(tier_for_age(age_days(j["posted_date"], today), max_age) for j in chosen)
        shortfall = None
        if len(chosen) < size:
            bits = [f"{n} {REASON_TEXT[k].format(max_age=max_age)}" for k, n in reasons.most_common()
                    if k not in ("no_city",)]
            shortfall = (f"Only {len(chosen)} postings passed every check (verified, dated, ≤{max_age} days)."
                         + (" Not counted: " + "; ".join(bits) + "." if bits else ""))
        out[bucket] = {"jobs": chosen, "count": len(chosen), "eligible": len(ok), "shortfall": shortfall,
                       "label": labels[bucket], "cities": primary if bucket == "primary" else secondary,
                       "tiers": {t: tiers.get(t, 0) for t in (1, 2, 3, 4)}, "reasons": dict(reasons)}
    return out


def _ord(d: str | None) -> int:
    try:
        return date.fromisoformat(d[:10]).toordinal() if d else 0
    except ValueError:
        return 0
