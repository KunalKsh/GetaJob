"""Passwords, rate limits, email validation and optional email sending."""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
import secrets
import smtplib
import threading
import time
from email.message import EmailMessage

log = logging.getLogger("getajob.auth")

_N, _R, _P = 2 ** 14, 8, 1
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]{1,64}@[A-Za-z0-9.-]{1,180}\.[A-Za-z]{2,24}$")
MIN_PASSWORD = 10


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                              dklen=len(base64.b64decode(dk)))
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


_DUMMY = hash_password(secrets.token_urlsafe(12))


def burn_time():
    """Spend the same time as a real password check so unknown emails can't be told apart by timing."""
    verify_password("x" * 12, _DUMMY)


def valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match((email or "").strip()))


def password_problem(pw: str, email: str = "") -> str | None:
    if len(pw or "") < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters."
    if len(pw) > 200:
        return "That password is too long."
    if email and pw.lower() == email.lower():
        return "Don't use your email address as the password."
    if len(set(pw)) < 5:
        return "Use a less repetitive password."
    return None


class RateLimiter:
    """Sliding-window limit per key (an IP address, or IP + email)."""

    def __init__(self, limit: int, window_seconds: int):
        self.limit, self.window = limit, window_seconds
        self.hits: dict[str, list[float]] = {}
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        t = time.monotonic()
        with self.lock:
            q = [x for x in self.hits.get(key, []) if t - x < self.window]
            if len(q) >= self.limit:
                self.hits[key] = q
                return False
            q.append(t)
            self.hits[key] = q
            if len(self.hits) > 10000:  # keep memory bounded
                self.hits = {k: v for k, v in self.hits.items() if v and t - v[-1] < self.window}
            return True

    def reset(self):  # used by tests
        with self.lock:
            self.hits.clear()


login_limiter = RateLimiter(8, 15 * 60)       # per IP + email
login_ip_limiter = RateLimiter(40, 15 * 60)   # per IP, across emails
request_limiter = RateLimiter(5, 60 * 60)
upload_limiter = RateLimiter(30, 60 * 60)


def email_configured() -> bool:
    return all(os.getenv(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"))


def send_email(to: str, subject: str, body: str) -> bool:
    """Send a plain-text email if SMTP is configured. Returns False (and the UI shows a copy link) otherwise."""
    if not email_configured():
        return False
    msg = EmailMessage()
    msg["From"] = os.getenv("MAIL_FROM") or os.environ["SMTP_USER"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT") or 587), timeout=20) as s:
            s.starttls()
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            s.send_message(msg)
        return True
    except (OSError, smtplib.SMTPException) as exc:
        log.warning("email to %s failed: %s", to, exc)
        return False
