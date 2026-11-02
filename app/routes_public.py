"""Pages anyone can open: landing, sign in, request access, accept an invite or reset link."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request

from core import auth, db
from core.config import ADMIN_EMAIL, PUBLIC_URL

from .web import client_ip, current_user, login, page, redirect

router = APIRouter()


def _safe_next(nxt: str | None) -> str:
    """Only allow redirects back into this site (no open redirects)."""
    if nxt and nxt.startswith("/") and not nxt.startswith("//") and "\\" not in nxt:
        return nxt
    return "/dashboard"


@router.get("/healthz")
def healthz():
    return {"ok": True}


@router.get("/")
def landing(request: Request):
    user = current_user(request)
    if user:
        return redirect("/dashboard")
    return page(request, "landing.html")


@router.get("/login")
def login_page(request: Request, next: str = ""):
    if current_user(request):
        return redirect(_safe_next(next))
    return page(request, "login.html", next=_safe_next(next), error="")


@router.post("/login")
def login_post(request: Request, email: str = Form(""), password: str = Form(""), next: str = Form("")):
    email = email.strip().lower()
    key = f"{client_ip(request)}|{email}"
    if not auth.login_ip_limiter.allow(client_ip(request)) or not auth.login_limiter.allow(key):
        return page(request, "login.html", next=_safe_next(next), status_code=429,
                    error="Too many sign-in attempts. Wait 15 minutes and try again.")
    user = db.get_user_by_email(email) if auth.valid_email(email) else None
    if not user:
        auth.burn_time()
    ok = bool(user) and user["status"] == "active" and auth.verify_password(password, user["password_hash"])
    if not ok:
        return page(request, "login.html", next=_safe_next(next), status_code=401, email=email,
                    error="That email and password don't match an active account.")
    login(request, user)
    return redirect(_safe_next(next))


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return redirect("/")


@router.get("/request-access")
def request_page(request: Request):
    if current_user(request):
        return redirect("/dashboard")
    return page(request, "request_access.html", done=False, error="")


@router.post("/request-access")
def request_post(request: Request, name: str = Form(""), email: str = Form(""), reason: str = Form(""),
                 website: str = Form("")):
    if website:  # honeypot field humans never see
        return page(request, "request_access.html", done=True, error="")
    email, name = email.strip().lower(), name.strip()
    if not auth.request_limiter.allow(client_ip(request)):
        return page(request, "request_access.html", done=False, status_code=429,
                    error="Too many requests from your network. Try again in an hour.")
    if not auth.valid_email(email) or not name or len(name) > 120:
        return page(request, "request_access.html", done=False, status_code=400, name=name, email=email,
                    reason=reason, error="Enter your name and a valid email address.")
    if not db.get_user_by_email(email):  # existing users get the same reply, so emails can't be probed
        if db.add_request(email, name, reason):
            link = (PUBLIC_URL or "") + "/admin"
            auth.send_email(ADMIN_EMAIL, f"GetaJob access request from {name}",
                            f"{name} <{email}> asked for access.\n\nReason: {reason or '(none given)'}\n\n"
                            f"Approve or decline: {link}")
    return page(request, "request_access.html", done=True, error="")


@router.get("/invite/{token}")
def invite_page(request: Request, token: str):
    inv = db.peek_token(token)
    if not inv:
        return page(request, "message.html", status_code=404, title="This link has expired",
                    message="Invite and reset links work once and expire after 7 days. Ask the admin for a new one.")
    existing = db.get_user_by_email(inv["email"])
    if inv["purpose"] != "reset" and existing:
        return page(request, "message.html", title="You already have an account",
                    message="Sign in with your email and password.", link=("/login", "Sign in"))
    return page(request, "invite.html", inv=inv, token=token, error="", reset=inv["purpose"] == "reset")


@router.post("/invite/{token}")
def invite_post(request: Request, token: str, name: str = Form(""), password: str = Form(""),
                confirm: str = Form("")):
    inv = db.peek_token(token)
    if not inv:
        return redirect(f"/invite/{token}")
    reset = inv["purpose"] == "reset"
    problem = auth.password_problem(password, inv["email"]) or (None if password == confirm else
                                                                "The two passwords don't match.")
    if not reset and not name.strip():
        problem = problem or "Enter your name."
    if problem:
        return page(request, "invite.html", inv=inv, token=token, error=problem, name=name, reset=reset,
                    status_code=400)
    if not db.use_token(token):
        return redirect(f"/invite/{token}")
    if reset:
        user = db.get_user_by_email(inv["email"])
        if not user:
            return redirect("/login")
        db.update_user(user["id"], password_hash=auth.hash_password(password))
        db.bump_session(user["id"])
    else:
        role = "admin" if inv["purpose"] == "setup" and inv["email"] == ADMIN_EMAIL else "user"
        uid = db.create_user(inv["email"], name, auth.hash_password(password), role)
        user = db.get_user(uid)
    login(request, db.get_user(user["id"]))
    return redirect("/resumes" if not reset else "/dashboard")
