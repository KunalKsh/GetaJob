"""Pick the top 50 per bucket: verified, dated, ≤30 days, filled tier 1 → 4, ranked by fit inside a tier."""
from __future__ import annotations

import re
from collections import Counter
from datetime import date

from .dates import UNKNOWN, age_days, tier_for_age, today_ist
from .dedup import norm_company
from .locations import METRO, NCR
from .relevance import is_relevant
from .verify import COUNTABLE

REASON_TEXT = {
    "not_verified": "not verified yet or failed verification",
    "date_unknown": "posting date could not be confirmed",
    "too_old": "older than {max_age} days",
    "excluded_company": "excluded company",
    "excluded_title": "title outside your seniority band",
    "salary": "stated salary outside your range",
    "no_city": "no target city",
    "off_target": "not an analytics role (e.g. accounting, compliance, HR operations)",
}


def _excluded_company(company: str, excludes: list[str]) -> bool:
    nc = norm_company(company)
    return any(e and norm_company(e) and norm_company(e) in nc for e in excludes)


def _excluded_title(title: str, words: list[str]) -> bool:
    t = (title or "").lower()
    return any(re.search(r"\b" + re.escape(w.lower()) + r"\b", t) for w in words if w)


def ineligible_reason(job: dict, prefs: dict, today: date) -> str | None:
    max_age = int(prefs.get("max_age_days") or 30)
    if job.get("bucket") not in (NCR, METRO):
        return "no_city"
    if _excluded_company(job.get("company", ""), prefs.get("exclude_companies") or []):
        return "excluded_company"
    if _excluded_title(job.get("title", ""), prefs.get("exclude_title_words") or []):
        return "excluded_title"
    if not job.get("source_name") == "manual" and not is_relevant(job.get("title", ""), prefs.get("roles") or []):
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
    for bucket in (NCR, METRO):
        pool = [j for j in jobs if j.get("bucket") == bucket and j.get("status") not in ("expired", "dead")]
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
                       "tiers": {t: tiers.get(t, 0) for t in (1, 2, 3, 4)}, "reasons": dict(reasons)}
    return out


def _ord(d: str | None) -> int:
    try:
        return date.fromisoformat(d[:10]).toordinal() if d else 0
    except ValueError:
        return 0
