"""Find the public career board of a company someone prefers, so it can be searched directly.

Only the public job-board JSON endpoints of Greenhouse, Lever and Ashby are tried, with a few likely
board names built from the company name. Results (found or not) are remembered for two weeks.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from core import db
from core.config import IST
from core.dedup import norm_company
from core.http import Http, RobotsDisallowed

log = logging.getLogger("getajob.discover")
RETRY_AFTER = timedelta(days=14)
MAX_PER_RUN = 12

PROBES = [
    ("greenhouse", "token", "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
     lambda d: isinstance(d, dict) and isinstance(d.get("jobs"), list)),
    ("lever", "company", "https://api.lever.co/v0/postings/{slug}?mode=json&limit=1", lambda d: isinstance(d, list)),
    ("ashby", "org", "https://api.ashbyhq.com/posting-api/job-board/{slug}",
     lambda d: isinstance(d, dict) and isinstance(d.get("jobs"), list)),
]


def slugs(name: str) -> list[str]:
    base = norm_company(name) or name.lower()
    words = re.findall(r"[a-z0-9]+", base)
    if not words:
        return []
    out = ["".join(words), "-".join(words), words[0]]
    return [s for i, s in enumerate(out) if s and len(s) >= 3 and s not in out[:i]]


def listed_names(emp: dict) -> set[str]:
    return {norm_company(e.get("name", "")) for rows in emp.values() if isinstance(rows, list) for e in rows}


def discover_boards(http: Http, names: list[str], now: datetime | None = None) -> list[dict]:
    """Probe boards for preferred companies not already searched. Returns newly found entries."""
    from .base import employers
    now = now or datetime.now(IST)
    settings = db.get_settings()
    memo: dict = dict(settings.get("discovered_boards") or {})
    known = listed_names(employers())
    found, tried = [], 0
    for name in names:
        key = norm_company(name)
        if not key or key in known:
            continue
        seen = memo.get(key)
        if seen and (seen.get("ats") or now - datetime.fromisoformat(seen["checked"]) < RETRY_AFTER):
            continue
        if tried >= MAX_PER_RUN:
            break
        tried += 1
        hit = None
        for ats, field, url, ok in PROBES:
            for slug in slugs(name):
                try:
                    r = http.get(url.format(slug=slug), cache_ttl=24 * 3600, retries=0)
                except RobotsDisallowed:
                    break
                except Exception:
                    continue
                if r.status == 200:
                    try:
                        data = r.json()
                    except Exception:
                        continue
                    if ok(data):
                        hit = {"ats": ats, field: slug, "name": name.strip()[:80]}
                        break
            if hit:
                break
        memo[key] = {**(hit or {}), "name": name.strip()[:80], "checked": now.isoformat(timespec="seconds")}
        if hit:
            found.append(hit)
            log.info("found %s board for %s: %s", hit["ats"], name, hit)
    settings["discovered_boards"] = memo
    db.save_settings(settings)
    return found


def discovered_entries() -> dict[str, list[dict]]:
    """Discovered boards in the same shape as employers.yaml."""
    try:
        memo = db.get_settings().get("discovered_boards") or {}
    except Exception:
        return {}
    out: dict[str, list[dict]] = {}
    for v in memo.values():
        ats = v.get("ats")
        if ats:
            field = {"greenhouse": "token", "lever": "company", "ashby": "org"}[ats]
            out.setdefault(ats, []).append({field: v[field], "name": v["name"], "industry": ""})
    return out
