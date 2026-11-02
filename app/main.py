"""GetaJob web app. Run locally: uvicorn app.main:app --port 8000"""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from core import db, pipeline
from core.config import ADMIN_EMAIL, COOKIE_SECURE, DATA_DIR, PUBLIC_URL, ensure_dirs, secret_key

from .web import APP_DIR, LoginRequired, csrf_protect, current_user, page, redirect

log = logging.getLogger("getajob")
_scheduler = None


def schedule():
    """Background refresh every N hours while the server is awake (hosted sites also use /api/cron/refresh)."""
    global _scheduler
    from apscheduler.schedulers.background import BackgroundScheduler
    s = db.get_settings()
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
        _scheduler.start()
    if _scheduler.get_job("refresh"):
        _scheduler.remove_job("refresh")
    if s.get("auto_refresh"):
        _scheduler.add_job(lambda: pipeline.run_refresh("scheduled"), "interval",
                           hours=max(1, int(s.get("refresh_hours") or 12)), id="refresh", max_instances=1, coalesce=True)


def next_run() -> str:
    from .web import fmt_dt
    j = _scheduler.get_job("refresh") if _scheduler else None
    return fmt_dt(j.next_run_time) if j and j.next_run_time else ""


def bootstrap_admin():
    """First start: print a one-time link that lets ADMIN_EMAIL create the admin account."""
    if db.admin_exists():
        return
    token = db.create_token(ADMIN_EMAIL, "setup", None, days=2)
    base = PUBLIC_URL or "http://127.0.0.1:8000"
    msg = f"ADMIN SETUP: open {base}/invite/{token} to create the admin account for {ADMIN_EMAIL} (valid 48 hours)."
    log.warning(msg)
    print("\n" + "=" * 100 + "\n" + msg + "\n" + "=" * 100 + "\n", flush=True)


def startup():
    ensure_dirs()
    handlers = [logging.StreamHandler()]
    try:
        handlers.append(logging.FileHandler(DATA_DIR / "getajob.log", encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)
    db.init_db()
    bootstrap_admin()
    threading.Thread(target=pipeline.rescore_everyone, daemon=True, name="rescore").start()
    try:
        schedule()
    except Exception:
        log.exception("scheduler failed to start")


@asynccontextmanager
async def lifespan(_app):
    startup()
    yield
    if _scheduler:
        _scheduler.shutdown(wait=False)


app = FastAPI(title="GetaJob", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None,
              dependencies=[Depends(csrf_protect)])
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
       "form-action 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'")
MAX_BODY = 30 * 1024 * 1024


@app.middleware("http")
async def security(request: Request, call_next):
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > MAX_BODY:
        return JSONResponse({"detail": "Upload too large (30 MB limit per request)."}, status_code=413)
    response = await call_next(request)
    h = response.headers
    h.setdefault("Content-Security-Policy", CSP)
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "same-origin")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
    h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    if COOKIE_SECURE:
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.url.path.startswith(("/dashboard", "/resumes", "/profile", "/tracker", "/admin", "/account",
                                    "/review", "/import", "/export", "/api")):
        h.setdefault("Cache-Control", "no-store")
    return response


# Session cookie: signed, HttpOnly, SameSite=Lax, Secure when served over HTTPS. Added last so it runs first.
app.add_middleware(SessionMiddleware, secret_key=secret_key(), session_cookie="getajob_session",
                   max_age=14 * 24 * 3600, same_site="lax", https_only=COOKIE_SECURE)


@app.exception_handler(LoginRequired)
async def _login_required(request: Request, exc: LoginRequired):
    if request.url.path.startswith("/api"):
        return JSONResponse({"detail": "Sign in first."}, status_code=401)
    return redirect("/login?next=" + request.url.path)


@app.exception_handler(HTTPException)
async def _http_error(request: Request, exc: HTTPException):
    if request.url.path.startswith("/api") or request.headers.get("x-csrf-token"):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
    titles = {403: "Not allowed", 404: "Not found", 413: "Too large", 429: "Too many attempts"}
    return page(request, "message.html", user=current_user(request), status_code=exc.status_code,
                title=titles.get(exc.status_code, "Something went wrong"), message=str(exc.detail))


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/api"):
        return JSONResponse({"detail": "Some fields were missing or invalid."}, status_code=422)
    return page(request, "message.html", user=current_user(request), status_code=422, title="Check the form",
                message="Some fields were missing or invalid. Go back and try again.")


from . import routes_admin, routes_public, routes_user  # noqa: E402

app.include_router(routes_public.router)
app.include_router(routes_user.router)
app.include_router(routes_admin.router)
