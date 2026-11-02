"""Shared web helpers: templates, the signed-in user, CSRF, and page rendering."""
from __future__ import annotations

import hmac
import secrets
from datetime import date, datetime
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from core import db, pipeline
from core.config import APP_NAME, IST
from core.dates import age_days, humanize_age, tier_for_age
from core.locations import BUCKET_LABEL
from core.verify import STATUS_COLOR, STATUS_LABEL

APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=APP_DIR / "templates")

CONF_LABEL = {"exact": "exact date", "relative": "from \"N days ago\"", "aggregator": "date from aggregator listing",
              "user": "date entered by you", "unknown": "date unknown"}


class LoginRequired(Exception):
    pass


# ---------------------------------------------------------------------------- session and user
def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def csrf_token(request: Request) -> str:
    tok = request.session.get("csrf")
    if not tok:
        tok = secrets.token_urlsafe(32)
        request.session["csrf"] = tok
    return tok


async def csrf_protect(request: Request):
    """Every state-changing request must carry the session's CSRF token (form field or X-CSRF-Token header)."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if request.url.path == "/api/cron/refresh":
        return  # authenticated by its own secret header instead
    sent = request.headers.get("x-csrf-token")
    if not sent:
        ctype = request.headers.get("content-type", "")
        if "form" in ctype:
            form = await request.form()
            sent = form.get("csrf_token")
    expected = request.session.get("csrf")
    if not (sent and expected and hmac.compare_digest(str(sent), str(expected))):
        raise HTTPException(403, "Your session expired or the form was out of date. Go back, reload the page and try again.")


def login(request: Request, user: dict):
    request.session.clear()  # new session on sign-in (no fixation)
    request.session.update(uid=user["id"], sv=user["session_version"], csrf=secrets.token_urlsafe(32))
    db.update_user(user["id"], last_login=db.now())


def current_user(request: Request) -> dict | None:
    uid = request.session.get("uid")
    if not uid:
        return None
    u = db.get_user(int(uid))
    if not u or u["status"] != "active" or u["session_version"] != request.session.get("sv"):
        request.session.clear()
        return None
    return u


def require_user(request: Request) -> dict:
    u = current_user(request)
    if not u:
        raise LoginRequired()
    return u


def require_admin(request: Request) -> dict:
    u = require_user(request)
    if u["role"] != "admin":
        raise HTTPException(403, "Only the site admin can do this.")
    return u


# ---------------------------------------------------------------------------- formatting helpers
def fmt_date(d: str | None) -> str:
    if not d:
        return "Unknown"
    try:
        return date.fromisoformat(d[:10]).strftime("%d %b %Y")
    except ValueError:
        return d


def fmt_dt(s) -> str:
    if not s:
        return "never"
    try:
        dt = s if isinstance(s, datetime) else datetime.fromisoformat(str(s))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST).strftime("%d %b, %I:%M %p")
    except ValueError:
        return str(s)


def salary_label(j: dict) -> str:
    lo, hi = j.get("salary_min_lpa"), j.get("salary_max_lpa")
    if lo is None and hi is None:
        return "Salary: Unknown"
    if lo == hi or hi is None:
        return f"₹{lo:g} LPA"
    return f"₹{lo:g}–{hi:g} LPA"


def portals_of(j: dict) -> list[str]:
    seen = []
    for l in j.get("links") or [{"portal": j.get("source_portal")}]:
        if l.get("portal") and l["portal"] not in seen:
            seen.append(l["portal"])
    return seen


def kb(n: int) -> str:
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


templates.env.globals.update(
    fmt_date=fmt_date, fmt_dt=fmt_dt, salary_label=salary_label, portals_of=portals_of, humanize_age=humanize_age,
    STATUS_LABEL=STATUS_LABEL, STATUS_COLOR=STATUS_COLOR, CONF_LABEL=CONF_LABEL, BUCKET_LABEL=BUCKET_LABEL,
    TRACKER_STATUSES=db.TRACKER_STATUSES, APP_NAME=APP_NAME, kb=kb)


def decorate(j: dict, today: date, tracker: dict) -> dict:
    j = dict(j)
    j["age"] = age_days(j.get("posted_date"), today)
    j["tier"] = tier_for_age(j["age"])
    j["track"] = tracker.get(j["id"], {})
    return j


def page(request: Request, name: str, user: dict | None = None, status_code: int = 200, **ctx) -> HTMLResponse:
    base = {"request": request, "user": user, "csrf": csrf_token(request), "nav": name.split(".")[0],
            "refresh": pipeline.STATE, "last_run": db.last_run() if user else None, "settings": db.get_settings()}
    base.update(ctx)
    return templates.TemplateResponse(request, name, base, status_code=status_code)


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)
