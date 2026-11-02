"""Job-alert emails (.eml / .mbox) exported from your inbox into ./alerts/.

This is how LinkedIn, Naukri, Instahyre and IIMJobs/Hirist listings come in without
logging in to those sites. Alert emails don't carry a reliable posting date, so these
jobs land in "Date unverified" until you open them and confirm.
"""
from __future__ import annotations

import email
import mailbox
import re
from email import policy
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup

from core.normalize import make_job, portal_from_url

from .base import Ctx, Source

SENDER_PORTAL = [("linkedin", "LinkedIn"), ("naukri", "Naukri"), ("instahyre", "Instahyre"),
                 ("iimjobs", "IIMJobs/Hirist"), ("hirist", "IIMJobs/Hirist"), ("indeed", "Indeed"),
                 ("foundit", "Foundit"), ("monster", "Foundit")]
JOB_URL = re.compile(
    r"linkedin\.com/(?:comm/)?jobs/view/\d+|naukri\.com/job-listings-[\w-]+|instahyre\.com/job-[\w-]+|"
    r"iimjobs\.com/j/[\w-]+|hirist\.(?:tech|com)/j/[\w-]+|indeed\.(?:com|co\.in)/(?:viewjob|rc/clk)\S*|"
    r"foundit\.in/job/[\w-]+", re.I)
SKIP_TEXT = re.compile(r"^(apply|view job|view|see (?:all|more)|easy apply|unsubscribe|search|jobs?|\d+ (?:new )?jobs?)$", re.I)


def _unwrap(url: str) -> str:
    """Click-tracking links often carry the real URL in a query parameter."""
    if JOB_URL.search(url):
        m = JOB_URL.search(url)
        clean = "https://www." + m.group(0) if not m.group(0).startswith("http") else m.group(0)
        return clean.replace("www.www.", "www.")
    for vals in parse_qs(urlparse(url).query).values():
        for v in vals:
            v = unquote(v)
            if JOB_URL.search(v):
                return _unwrap(v)
    return ""


def _portal(sender: str, url: str) -> str:
    low = (sender or "").lower()
    for k, v in SENDER_PORTAL:
        if k in low:
            return v
    return portal_from_url(url)


def _body_html(msg) -> str:
    try:
        part = msg.get_body(preferencelist=("html", "plain"))
        return part.get_content() if part else ""
    except Exception:
        for part in msg.walk():
            if part.get_content_type() in ("text/html", "text/plain"):
                try:
                    return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
                except Exception:
                    continue
    return ""


def parse_message(msg) -> list[dict]:
    """Extract (title, company, location, url) items from one alert email."""
    sender = str(msg.get("From", ""))
    html = _body_html(msg)
    soup = BeautifulSoup(html, "html.parser")
    items, seen = [], set()
    for a in soup.find_all("a", href=True):
        url = _unwrap(a["href"])
        if not url:
            continue
        key = re.sub(r"[?#].*$", "", url)
        text = a.get_text(" ", strip=True)
        if key in seen:
            continue
        if not text or SKIP_TEXT.match(text) or len(text) > 140:
            # look for the job title in the link's block instead
            block = a.find_parent(["td", "div", "li"])
            text = ""
            if block:
                strong = block.find(["strong", "b", "h2", "h3", "h4"])
                text = strong.get_text(" ", strip=True) if strong else ""
            if not text:
                continue
        seen.add(key)
        block = a.find_parent(["td", "li", "tr", "div"])
        lines = []
        if block:
            lines = [l.strip() for l in block.get_text("\n", strip=True).split("\n") if l.strip()]
        after = [l for l in lines if l != text and not SKIP_TEXT.match(l)]
        if text in lines:
            after = [l for l in lines[lines.index(text) + 1:] if not SKIP_TEXT.match(l)]
        company = after[0] if after else ""
        location = after[1] if len(after) > 1 else ""
        if "·" in company and not location:
            company, _, location = company.partition("·")
        items.append({"title": text, "company": company.strip(" ·|-"), "location": location.strip(" ·|-"),
                      "url": key, "portal": _portal(sender, key)})
    return items


def iter_messages(folder: Path):
    for p in sorted(folder.glob("*")):
        try:
            if p.suffix.lower() == ".eml":
                with open(p, "rb") as fh:
                    yield p.name, email.message_from_binary_file(fh, policy=policy.default)
            elif p.suffix.lower() == ".mbox":
                for m in mailbox.mbox(str(p), factory=lambda f: email.message_from_binary_file(f, policy=policy.default)):
                    yield p.name, m
        except Exception as exc:
            yield p.name, exc


class EmailAlerts(Source):
    name, label, kind = "alerts", "Job-alert emails", "alerts"
    portal = "LinkedIn / Naukri / Instahyre / IIMJobs"
    coverage_note = ("Reads .eml/.mbox files you export into the alerts folder. Dates in alert emails are not "
                     "posting dates, so these jobs need a quick manual check before they count.")

    def configured(self) -> bool:
        return True

    def fetch(self, ctx: Ctx) -> list[dict]:
        """During a refresh only the demo fixtures are read. Real alert emails are private to each person and are
        uploaded on the Import page (see jobs_from_alert_files)."""
        if not ctx.demo:
            ctx.note(self.name, "Each person uploads their own alert emails on the Import page")
            return []
        from core.config import FIXTURES_DIR
        out = []
        for path in sorted((FIXTURES_DIR / "alerts").glob("*.eml")):
            out += jobs_from_alert_files([(path.name, path.read_bytes())], ctx.relevant_title, ctx.target_location,
                                         owner_id=None, now=ctx.now)
        return out


def jobs_from_alert_files(files: list[tuple[str, bytes]], relevant, in_target, owner_id, now=None) -> list[dict]:
    """Parse uploaded .eml / .mbox files into postings owned by one person."""
    import tempfile
    out = []
    for fname, data in files:
        msgs = []
        if fname.lower().endswith(".mbox"):
            with tempfile.NamedTemporaryFile(suffix=".mbox", delete=False) as tmp:
                tmp.write(data)
                tmp_path = tmp.name
            try:
                for m in mailbox.mbox(tmp_path, factory=lambda f: email.message_from_binary_file(f, policy=policy.default)):
                    msgs.append(m)
            finally:
                Path(tmp_path).unlink(missing_ok=True)
        else:
            msgs.append(email.message_from_bytes(data, policy=policy.default))
        for msg in msgs[:500]:
            received = str(msg.get("Date", ""))
            for it in parse_message(msg):
                if not relevant(it["title"]):
                    continue
                if it["location"] and not in_target(it["location"]):
                    continue
                extra = {"alert_file": fname, "alert_received": received}
                if owner_id is not None:
                    extra["owner_id"] = owner_id
                out.append(make_job(
                    source_name="alerts", native_id=f"{owner_id}:{it['url']}", title=it["title"],
                    company=it["company"], location_raw=it["location"], posted_raw=None, source_url=it["url"],
                    source_portal=it["portal"], links=[{"portal": it["portal"], "url": it["url"], "source": "alerts"}],
                    extra=extra, now=now))
    return out
