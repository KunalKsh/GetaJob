"""Admin: access requests, invites, users, site settings and refresh."""
from __future__ import annotations

import hmac
from urllib.parse import urlencode

import yaml
from fastapi import APIRouter, Depends, Form, HTTPException, Request

from core import auth, db, pipeline
from core.config import PUBLIC_URL, cron_secret, key_status

from .web import page, redirect, require_admin

router = APIRouter()


def _link(request: Request, token: str) -> str:
    base = PUBLIC_URL or str(request.base_url).rstrip("/")
    return f"{base}/invite/{token}"


def _invite(request: Request, email: str, admin: dict, purpose: str = "invite") -> tuple[str, bool]:
    token = db.create_token(email, purpose, admin["id"], days=7)
    link = _link(request, token)
    if purpose == "reset":
        subject, body = "Reset your GetaJob password", f"Use this link to set a new password (valid 7 days, works once):\n\n{link}\n"
    else:
        subject = "You're invited to GetaJob"
        body = (f"{admin['name'] or 'The admin'} invited you to GetaJob, a job finder that ranks fresh analytics "
                f"postings against your resume.\n\nCreate your account (valid 7 days, works once):\n\n{link}\n")
    return link, auth.send_email(email, subject, body)


def flash(request: Request, tab: str, msg: str, link: str = ""):
    """Invite links travel in the signed session, not the URL, so they never land in browser history or logs."""
    request.session["flash"] = {"msg": msg, "link": link}
    return redirect(f"/admin?tab={tab}")


@router.get("/admin")
def admin_page(request: Request, admin: dict = Depends(require_admin), tab: str = "requests", msg: str = "",
               err: str = ""):
    from sources.base import employers_text
    f = request.session.pop("flash", None) or {}
    msg, link = f.get("msg") or msg, f.get("link") or ""
    users = db.list_users()
    return page(request, "admin.html", user=admin, tab=tab, msg=msg, link=link, err=err,
                pending=db.list_requests("pending"), decided=db.list_requests()[:40], users=users,
                invites=db.list_invites(), settings=db.get_settings(), keys=key_status(),
                employers_text=employers_text(), cron_on=bool(cron_secret()))


@router.post("/admin/requests/{rid}/approve")
def approve(request: Request, rid: int, admin: dict = Depends(require_admin)):
    r = db.get_request(rid)
    if not r or r["status"] != "pending":
        raise HTTPException(404, "That request isn't pending.")
    if db.get_user_by_email(r["email"]):
        db.decide_request(rid, "approved", admin["id"])
        return redirect("/admin?" + urlencode({"msg": f"{r['email']} already has an account."}))
    link, sent = _invite(request, r["email"], admin)
    db.decide_request(rid, "approved", admin["id"])
    note = f"Approved {r['email']}." + (" Invite emailed." if sent else " Send them this invite link:")
    return flash(request, "requests", note, "" if sent else link)


@router.post("/admin/requests/{rid}/decline")
def decline(rid: int, admin: dict = Depends(require_admin)):
    r = db.get_request(rid)
    if not r or r["status"] != "pending":
        raise HTTPException(404, "That request isn't pending.")
    db.decide_request(rid, "declined", admin["id"])
    return redirect("/admin?" + urlencode({"msg": f"Declined {r['email']}."}))


@router.post("/admin/invite")
def invite(request: Request, email: str = Form(""), admin: dict = Depends(require_admin)):
    email = email.strip().lower()
    if not auth.valid_email(email):
        return redirect("/admin?" + urlencode({"tab": "users", "err": "Enter a valid email address."}))
    if db.get_user_by_email(email):
        return redirect("/admin?" + urlencode({"tab": "users", "err": f"{email} already has an account."}))
    link, sent = _invite(request, email, admin)
    for r in db.list_requests("pending"):
        if r["email"] == email:
            db.decide_request(r["id"], "approved", admin["id"])
    note = f"Invited {email}." + (" Invite emailed." if sent else " Send them this link:")
    return flash(request, "users", note, "" if sent else link)


@router.post("/admin/users/{uid}/{action}")
def user_action(request: Request, uid: int, action: str, admin: dict = Depends(require_admin)):
    u = db.get_user(uid)
    if not u:
        raise HTTPException(404, "No such user.")
    if uid == admin["id"] and action in ("disable", "delete", "demote"):
        raise HTTPException(400, "You can't do that to your own account.")
    if action == "disable":
        db.update_user(uid, status="disabled")
        db.bump_session(uid)
        msg = f"Disabled {u['email']}. They were signed out."
    elif action == "enable":
        db.update_user(uid, status="active")
        msg = f"Re-enabled {u['email']}."
    elif action == "reset":
        link, sent = _invite(request, u["email"], admin, purpose="reset")
        return flash(request, "users", f"Password reset link for {u['email']}" + (" emailed." if sent else ":"),
                     "" if sent else link)
    elif action == "make-admin":
        db.update_user(uid, role="admin")
        msg = f"{u['email']} is now an admin."
    elif action == "demote":
        db.update_user(uid, role="user")
        msg = f"{u['email']} is no longer an admin."
    elif action == "delete":
        db.delete_user(uid)
        msg = f"Deleted {u['email']} and all their data."
    else:
        raise HTTPException(404, "Unknown action.")
    return redirect("/admin?" + urlencode({"tab": "users", "msg": msg}))


@router.post("/admin/settings")
async def save_settings(request: Request, admin: dict = Depends(require_admin)):
    form = await request.form()
    s = db.get_settings()
    for k, lo, hi in (("refresh_hours", 1, 168), ("google_jobs_every_hours", 1, 720), ("verify_limit", 50, 3000),
                      ("max_age_days", 1, 60), ("bucket_size", 5, 200), ("max_query_roles", 1, 40)):
        try:
            s[k] = max(lo, min(hi, int(form.get(k) or s[k])))
        except ValueError:
            pass
    for k in ("adzuna", "jooble", "jsearch", "serpapi"):
        try:
            s["api_budget"][k] = max(0, min(1000, int(form.get("budget_" + k) or s["api_budget"][k])))
        except ValueError:
            pass
    s["auto_refresh"] = form.get("auto_refresh") == "on"
    s["demo_mode"] = form.get("demo_mode") == "on"
    msg = "Saved."
    emp = form.get("employers_yaml")
    if emp is not None:
        try:
            data = yaml.safe_load(emp) or {}
            if not isinstance(data, dict):
                raise ValueError("the top level must be ATS sections like greenhouse:, lever:, workday:")
            s["employers_yaml"] = str(emp)[:200000]
        except (yaml.YAMLError, ValueError) as exc:
            msg = f"Saved everything except the company list: it isn't valid YAML ({str(exc)[:200]})."
    db.save_settings(s)
    from .main import schedule
    schedule()
    pipeline.rescore_everyone()
    return redirect("/admin?" + urlencode({"tab": "settings", "msg": msg}))


@router.post("/api/refresh")
def api_refresh(admin: dict = Depends(require_admin)):
    return {"started": pipeline.start_refresh("manual"), "state": pipeline.STATE}


@router.post("/api/cron/refresh")
def cron_refresh(request: Request):
    """Called on a schedule (GitHub Actions) with the CRON_SECRET header, so a sleeping free-tier server wakes up."""
    secret = cron_secret()
    sent = request.headers.get("x-cron-token", "")
    if not secret or not hmac.compare_digest(sent, secret):
        raise HTTPException(403, "Not allowed.")
    return {"started": pipeline.start_refresh("cron")}
