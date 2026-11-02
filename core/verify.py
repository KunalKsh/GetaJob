"""Posting verification: live link, expiry text, title/company consistency, date recheck, scam flags."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from rapidfuzz import fuzz

from .config import IST
from .dates import CONFIDENCE_RANK, EXACT, parse_posted, today_ist
from .dedup import norm_company, norm_title
from .http import Http, RobotsDisallowed

VERIFIED, NEEDS_REVIEW, EXPIRED, DEAD = "verified", "needs_review", "expired", "dead"
LOGIN, UNVERIFIABLE, UNCHECKED = "login_required", "unverifiable", "unchecked"
COUNTABLE = {VERIFIED}
STATUS_LABEL = {
    VERIFIED: "Verified", NEEDS_REVIEW: "Needs review", EXPIRED: "Expired", DEAD: "Dead link",
    LOGIN: "Could not verify (login required)", UNVERIFIABLE: "Could not verify", UNCHECKED: "Not checked yet",
}
STATUS_COLOR = {VERIFIED: "green", NEEDS_REVIEW: "amber", LOGIN: "amber", UNVERIFIABLE: "amber",
                UNCHECKED: "grey", EXPIRED: "red", DEAD: "red"}

EXPIRY_PATTERNS = [
    r"no longer accepting applications", r"(?:this )?job (?:has )?expired", r"job (?:posting )?(?:is )?closed",
    r"this (?:job|position|role|vacancy) (?:is|has been) (?:closed|filled|removed)",
    r"position (?:has been )?filled", r"posting (?:has been )?removed", r"(?:job|position) is no longer available",
    r"no longer available", r"applications? (?:are |is )?(?:now )?closed",
    r"job (?:you(?:'|’)re|you are) looking for (?:is|was|has) (?:no longer|been|expired|closed|removed|not)", r"requisition (?:is )?no longer",
    r"this job posting is no longer active", r"has been filled", r"page (?:you requested )?(?:could not be|cannot be|was not) found",
    r"job not found", r"this listing has expired",
]
_EXPIRY_RE = re.compile("|".join(EXPIRY_PATTERNS), re.I)
LOGIN_PATTERNS = [r"sign in to (?:view|continue|see)", r"log ?in to (?:view|continue|see)", r"join (?:linkedin|now) to",
                  r"authwall", r"please (?:sign|log) ?in", r"create an account to (?:view|continue)"]
_LOGIN_RE = re.compile("|".join(LOGIN_PATTERNS), re.I)
_LOGIN_URL = re.compile(r"/(login|signin|sign-in|authwall|uas/login|checkpoint|auth)(?:[/?#]|$)", re.I)
_PERSONAL_EMAIL = re.compile(r"[\w.+-]+@(gmail|yahoo|hotmail|outlook|rediffmail|ymail|live)\.(com|in|co\.in)", re.I)
_PAYMENT = re.compile(r"registration (?:fee|charges?)|security deposit|processing fee|training fee|"
                      r"pay (?:a |the )?(?:fee|amount|deposit)|refundable (?:fee|deposit)|joining fee", re.I)


def detect_expiry(text: str) -> str | None:
    m = _EXPIRY_RE.search(text or "")
    return m.group(0) if m else None


def detect_login_wall(final_url: str, text: str) -> bool:
    if _LOGIN_URL.search(urlparse(final_url or "").path or ""):
        return True
    head = (text or "")[:20000]
    return bool(_LOGIN_RE.search(head)) and bool(re.search(r'type=["\']?password', head, re.I))


def is_generic_redirect(original: str, final: str) -> bool:
    o, f = urlparse(original), urlparse(final)
    if not final or o.path.rstrip("/") == f.path.rstrip("/"):
        return False
    fp = f.path.rstrip("/").lower()
    generic = fp in ("", "/careers", "/jobs", "/search", "/job-search", "/en", "/en-us", "/careers/search")
    shallower = o.path.count("/") >= 2 and fp.count("/") <= 1
    return generic or (shallower and not re.search(r"\d{3,}", fp))


def quality_flags(job: dict) -> list[str]:
    flags = []
    desc = job.get("description") or ""
    if _PAYMENT.search(desc):
        flags.append("Asks for a payment or deposit")
    if _PERSONAL_EMAIL.search(desc):
        flags.append("Recruiter uses a personal email address")
    comp = (job.get("company") or "").strip().lower()
    if not comp or comp in ("confidential", "unknown", "company", "n/a", "hiring company"):
        flags.append("No company name")
    if len(desc) < 300:
        flags.append("Short or vague description")
    return flags


def jsonld_postings(html: str) -> list[dict]:
    out = []
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup.find_all("script", type=re.compile("ld\\+json", re.I)):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except (ValueError, TypeError):
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for it in items:
            if isinstance(it, dict) and "JobPosting" in str(it.get("@type", "")):
                out.append(it)
    return out


def page_text(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html or "", "html.parser")
    title = (soup.title.get_text(" ", strip=True) if soup.title else "")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    h = " ".join(x.get_text(" ", strip=True) for x in soup.find_all(["h1", "h2"])[:6])
    body = soup.get_text(" ", strip=True)
    return f"{title} {h}", body[:60000]


def consistency_ok(job: dict, heading: str, body: str) -> bool:
    nt, nc = norm_title(job.get("title")), norm_company(job.get("company"))
    hay = (heading + " " + body[:15000]).lower()
    title_ok = fuzz.partial_ratio(nt, hay) >= 85 if nt else False
    company_ok = (not nc) or fuzz.partial_ratio(nc, hay) >= 80
    return title_ok and company_ok


def result(status: str, note: str = "", page_date: str | None = None, page_conf: str | None = None,
           extra: dict | None = None) -> dict:
    return {"status": status, "note": note, "page_date": page_date, "page_conf": page_conf,
            "checked_at": datetime.now(IST).isoformat(timespec="seconds"), **(extra or {})}


def verify_generic(job: dict, http: Http) -> dict:
    url = job.get("apply_url") or job.get("source_url")
    if not url:
        return result(UNVERIFIABLE, "No link to check")
    try:
        r = http.get(url, retries=1, timeout=20)
    except RobotsDisallowed:
        return result(UNVERIFIABLE, "The site's robots.txt does not allow automated checks of this page")
    if r.error == "redirect loop":
        return result(DEAD, "Redirect loop")
    if r.status == 0:
        if "DNS" in r.error:
            return result(DEAD, "DNS failure: the site could not be found")
        return result(NEEDS_REVIEW, f"Could not load the page ({r.error})")
    if r.status in (404, 410):
        return result(DEAD, f"HTTP {r.status}: page not found")
    if r.status in (401, 403):
        if detect_login_wall(r.url, r.text) or portal_needs_login(url):
            return result(LOGIN, "Login wall instead of the job page")
        return result(NEEDS_REVIEW, f"HTTP {r.status}: the site blocks automated checks")
    if r.status >= 500:
        return result(NEEDS_REVIEW, f"HTTP {r.status}: server error")
    if r.status >= 400:
        return result(NEEDS_REVIEW, f"HTTP {r.status}")
    if detect_login_wall(r.url, r.text):
        return result(LOGIN, "Login wall instead of the job page")
    if is_generic_redirect(url, r.url):
        return result(DEAD, f"Redirected to a general page ({urlparse(r.url).path or '/'})")

    heading, body = page_text(r.text)
    exp = detect_expiry(body[:20000])
    postings = jsonld_postings(r.text)
    page_date = page_conf = None
    if postings:
        jp = postings[0]
        vt = jp.get("validThrough")
        if vt:
            d, _ = parse_posted(vt)
            if d and d < today_ist():
                return result(EXPIRED, f"Listing says it closed on {d.isoformat()}")
        if jp.get("datePosted"):
            d, c = parse_posted(jp["datePosted"])
            if d:
                page_date, page_conf = d.isoformat(), c
        heading += " " + str(jp.get("title", "")) + " " + str((jp.get("hiringOrganization") or {}).get("name", "")
                                                             if isinstance(jp.get("hiringOrganization"), dict) else "")
    if exp and not postings:
        return result(EXPIRED, f'Page says "{exp}"')
    if not consistency_ok(job, heading, body):
        note = "Title or company on the page does not match this record"
        if exp:
            return result(EXPIRED, f'Page says "{exp}"')
        return result(NEEDS_REVIEW, note, page_date, page_conf)
    return result(VERIFIED, "Live page, title and company match", page_date, page_conf)


def portal_needs_login(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return any(d in host for d in ("linkedin.com", "instahyre.com"))


def apply_verification(job: dict, res: dict) -> dict:
    """Write a verification result onto the job, including the date recheck and quality flags."""
    job = dict(job)
    job["status"] = res["status"]
    job["verify_note"] = res.get("note", "")
    job["last_verified"] = res.get("checked_at")
    pd, pc = res.get("page_date"), res.get("page_conf")
    if pd:
        cur, cc = job.get("posted_date"), job.get("posted_date_confidence", "unknown")
        if not cur or CONFIDENCE_RANK.get(pc, 0) > CONFIDENCE_RANK.get(cc, 0):
            job["posted_date"], job["posted_date_confidence"] = pd, pc
            job["date_note"] = "Date taken from the job page"
        elif pc == EXACT and cc == EXACT and abs((date.fromisoformat(pd) - date.fromisoformat(cur)).days) > 2:
            job["posted_date"] = pd
            job["date_note"] = f"Job page shows {pd}; listing showed {cur}"
    for k in ("title_on_page",):
        if k in res:
            job[k] = res[k]
    flags = quality_flags(job)
    job["flags"] = flags
    if job["status"] == VERIFIED and any(f.startswith(("Asks for a payment", "Recruiter uses")) for f in flags):
        job["status"] = NEEDS_REVIEW
        job["verify_note"] = "Possible scam: " + "; ".join(flags)
    return job
