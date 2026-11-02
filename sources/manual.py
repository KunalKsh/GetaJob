"""Import by URL or pasted job description (for login-walled portals such as Instahyre or LinkedIn)."""
from __future__ import annotations

import re

from core.http import Http, RobotsDisallowed
from core.normalize import make_job, portal_from_url, strip_html
from core.verify import detect_login_wall, jsonld_postings, page_text

from .base import Source


def _loc_from_jsonld(jp: dict) -> str:
    locs = jp.get("jobLocation") or []
    if isinstance(locs, dict):
        locs = [locs]
    parts = []
    for l in locs:
        addr = (l or {}).get("address") or {}
        if isinstance(addr, dict):
            parts.append(", ".join(str(addr.get(k)) for k in ("addressLocality", "addressRegion") if addr.get(k)))
        elif isinstance(addr, str):
            parts.append(addr)
    return "; ".join(p for p in parts if p)


def _salary_from_jsonld(jp: dict) -> str:
    bs = jp.get("baseSalary") or {}
    if not isinstance(bs, dict) or (bs.get("currency") or "INR").upper() != "INR":
        return ""
    v = bs.get("value") or {}
    if isinstance(v, dict):
        lo, hi, unit = v.get("minValue"), v.get("maxValue"), (v.get("unitText") or "YEAR").upper()
        if lo:
            per = " a month" if unit == "MONTH" else ""
            return f"INR {lo} - {hi or lo}{per}"
    return ""


def import_url(url: str, http: Http, overrides: dict | None = None) -> tuple[dict | None, str]:
    """Fetch a public job page and read its schema.org JobPosting. Returns (job, message)."""
    overrides = {k: v for k, v in (overrides or {}).items() if v}
    try:
        r = http.get(url, retries=1)
    except RobotsDisallowed:
        return None, ("This site's robots.txt doesn't allow automated reading. Paste the job description "
                      "into the text box instead.")
    if not r.ok:
        return None, f"Could not open the page (HTTP {r.status} {r.error}). Paste the job description instead."
    if detect_login_wall(r.url, r.text):
        return None, "The page needs a login. Paste the job description into the text box instead."
    postings = jsonld_postings(r.text)
    if postings:
        jp = postings[0]
        org = jp.get("hiringOrganization")
        company = org.get("name", "") if isinstance(org, dict) else str(org or "")
        job = make_job(source_name="manual", native_id=url, title=overrides.get("title") or jp.get("title", ""),
                       company=overrides.get("company") or company,
                       location_raw=overrides.get("location") or _loc_from_jsonld(jp),
                       posted_raw=overrides.get("posted") or jp.get("datePosted"),
                       date_confidence="user" if overrides.get("posted") else None,
                       source_url=url, description=jp.get("description", ""), salary_text=_salary_from_jsonld(jp),
                       source_portal=portal_from_url(url))
        return job, "Imported from the page's structured job data"
    heading, body = page_text(r.text)
    return import_text(body, url=url, overrides=overrides, title_hint=heading)


def import_text(text: str, url: str = "", overrides: dict | None = None, title_hint: str = "") -> tuple[dict | None, str]:
    overrides = {k: v for k, v in (overrides or {}).items() if v}
    text = strip_html(text or "")
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines and not overrides.get("title"):
        return None, "Nothing to import: paste a job description or a link."

    def field(*names):
        for n in names:
            m = re.search(rf"(?im)^\s*{n}\s*[:\-–]\s*(.+)$", text)
            if m:
                return m.group(1).strip()
        return ""

    title = overrides.get("title") or field("job title", "title", "role", "position") or \
        (title_hint.split("|")[0].strip() if title_hint else "") or lines[0][:120]
    company = overrides.get("company") or field("company", "organisation", "organization", "employer")
    location = overrides.get("location") or field("location", "job location", "city", "work location")
    posted = overrides.get("posted")
    conf = "user" if posted else None
    if not posted:
        m = re.search(r"(?i)posted\s*(?:on)?\s*[:\-]?\s*((?:\d+\+?\s*(?:day|week|month|hour)s?\s*ago)|today|yesterday|"
                      r"\d{1,2}\s+\w{3,9}\s+\d{4}|\d{4}-\d{2}-\d{2})", text)
        posted = m.group(1) if m else None
    salary = field("salary", "ctc", "compensation", "pay")
    job = make_job(source_name="manual", native_id=url or (title + "|" + company), title=title, company=company,
                   location_raw=location, posted_raw=posted, date_confidence=conf, source_url=url or "",
                   description=text, salary_text=salary, source_portal=portal_from_url(url) if url else "Company/ATS")
    missing = [n for n, v in (("company", company), ("city", job["city"]), ("posted date", job["posted_date"])) if not v]
    msg = "Imported from the pasted text" + (f". Add the missing {', '.join(missing)} so it can be ranked." if missing else "")
    return job, msg


class Manual(Source):
    name, label, kind = "manual", "Import by URL / pasted JD", "manual"
    portal = "Any portal"
    coverage_note = "Paste a link or the full job description from any portal, including login-walled ones."

    def configured(self) -> bool:
        return True

    def fetch(self, ctx):
        return []  # manual imports are added from the Import page, not during refresh
