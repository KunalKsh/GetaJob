"""Cross-portal de-duplication: one canonical record per (title, company, city), all source links kept."""
from __future__ import annotations

import hashlib
import re

from rapidfuzz import fuzz

from .dates import CONFIDENCE_RANK

_COMPANY_NOISE = re.compile(
    r"\b(private|pvt|limited|ltd|llp|inc|incorporated|corp|corporation|co|company|plc|gmbh|india|"
    r"technologies|technology|solutions|services|group|the)\b\.?", re.I)
_TITLE_NOISE = [
    r"\(\s*[a-z]?\d+[a-z]?\s*\)",            # (4B)
    r"\s[-–|]\s*c\d{1,2}\b.*$",               # - C12 - GURUGRAM
    r"\b\d[a-d]\b$",                          # trailing grade 4B
    r"[_-]?\b(?:req|jr|r)[-_]?\d{3,}\b",      # requisition ids
    r"\|.*$",                                 # | Exp 1-3 yrs
    r"\s[-–]\s*(?:gurugram|gurgaon|noida|delhi|bengaluru|bangalore|hyderabad|mumbai|pune|india)\b.*$",
    r"\((?:remote|hybrid|onsite|on-site)\)",
]
_SENIOR = [(r"\bsr\.?\b", "senior"), (r"\bjr\.?\b", "junior"), (r"\bmgr\b", "manager"), (r"\bassoc\.?\b", "associate"),
           (r"\banlst\b", "analyst"), (r"\bspec\b", "specialized")]


def norm_title(t: str) -> str:
    t = (t or "").lower()
    for pat in _TITLE_NOISE:
        t = re.sub(pat, " ", t, flags=re.I)
    for pat, rep in _SENIOR:
        t = re.sub(pat, rep, t)
    t = re.sub(r"[^a-z0-9&/ ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def norm_company(c: str) -> str:
    c = (c or "").lower()
    c = re.sub(r"^[a-z ]{2,20}:\s*", "", c)  # "India: Mastercard India Services" -> "mastercard..."
    c = re.sub(r"\(.*?\)", " ", c)
    c = _COMPANY_NOISE.sub(" ", c)
    c = re.sub(r"[^a-z0-9& ]+", " ", c)
    return re.sub(r"\s+", " ", c).strip()


def dedup_key(job: dict) -> str:
    return f"{norm_title(job.get('title'))}|{norm_company(job.get('company'))}|{job.get('city') or ''}"


def content_hash(job: dict) -> str | None:
    desc = re.sub(r"\s+", " ", (job.get("description") or "").lower()).strip()
    if len(desc) < 200:
        return None
    return hashlib.sha1((norm_company(job.get("company")) + "|" + desc[:1500]).encode()).hexdigest()[:20]


def same_posting(a: dict, b: dict) -> bool:
    if (a.get("city") or "") != (b.get("city") or ""):
        return False
    ca, cb = norm_company(a.get("company")), norm_company(b.get("company"))
    if not ca or not cb:
        return False
    if fuzz.token_set_ratio(ca, cb) < 90:
        return False
    return fuzz.token_sort_ratio(norm_title(a.get("title")), norm_title(b.get("title"))) >= 92


def _source_rank(job: dict) -> int:
    """Prefer company ATS records (exact dates, direct apply links) as the canonical copy."""
    src = job.get("source_name", "")
    if src in ("greenhouse", "lever", "ashby", "workable", "smartrecruiters", "workday"):
        return 3
    if src in ("manual",):
        return 2
    return 1


def merge(canonical: dict, other: dict) -> dict:
    """Merge `other` into `canonical` (both normalized). Returns the merged canonical record."""
    if _source_rank(other) > _source_rank(canonical):
        canonical, other = dict(other), canonical
        canonical["id"], canonical["first_seen"] = other["id"], other.get("first_seen", canonical["first_seen"])
    links = list(canonical.get("links") or [])
    seen = {l["url"] for l in links}
    for l in other.get("links") or []:
        if l["url"] not in seen:
            links.append(l)
            seen.add(l["url"])
    canonical["links"] = links
    # date: higher confidence wins; equal confidence keeps the older date (never overstate freshness)
    ca, oa = canonical.get("posted_date_confidence", "unknown"), other.get("posted_date_confidence", "unknown")
    if other.get("posted_date") and (
            not canonical.get("posted_date") or CONFIDENCE_RANK.get(oa, 0) > CONFIDENCE_RANK.get(ca, 0)
            or (CONFIDENCE_RANK.get(oa, 0) == CONFIDENCE_RANK.get(ca, 0)
                and other["posted_date"] < canonical["posted_date"])):
        canonical["posted_date"], canonical["posted_date_confidence"] = other["posted_date"], oa
    for f in ("description", "salary_text", "experience_required"):
        if len(other.get(f) or "") > len(canonical.get(f) or ""):
            canonical[f] = other[f]
    for f in ("salary_min_lpa", "salary_max_lpa", "exp_min", "exp_max"):
        if canonical.get(f) is None and other.get(f) is not None:
            canonical[f] = other[f]
    canonical["skills_extracted"] = sorted(set(canonical.get("skills_extracted") or []) |
                                           set(other.get("skills_extracted") or []))
    return canonical


def dedupe(jobs: list[dict]) -> list[dict]:
    """Collapse duplicates within one batch."""
    out: list[dict] = []
    by_city: dict[str, list[int]] = {}
    for job in jobs:
        idxs = by_city.setdefault(job.get("city") or "", [])
        hit = next((i for i in idxs if out[i]["id"] == job["id"] or same_posting(out[i], job)), None)
        if hit is None:
            idxs.append(len(out))
            out.append(job)
        else:
            out[hit] = merge(out[hit], job)
    return out
