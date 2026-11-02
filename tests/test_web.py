"""Accounts, access control, resume uploads and per-user isolation, through the real web app."""
import re
from urllib.parse import parse_qs, unquote_plus as unquote, urlparse

from fastapi.testclient import TestClient

from tests.conftest import csrf_of, make_pdf, resume_lines
from core import auth, db


def new_client():
    from app.main import app
    return TestClient(app)


def invite_and_register(admin_client, email, name, password="user-pass-12345"):
    r = admin_client.post("/admin/invite", data={"csrf_token": csrf_of(admin_client, "/admin"), "email": email},
                          follow_redirects=False)
    page = admin_client.get(r.headers["location"]).text
    token = re.search(r'/invite/([\w-]+)"', page).group(1)
    c = new_client()
    r = c.post(f"/invite/{token}", data={"csrf_token": csrf_of(c, f"/invite/{token}"), "name": name,
                                         "password": password, "confirm": password}, follow_redirects=False)
    assert r.status_code == 303
    return c, token


def upload(c, files):
    return c.post("/resumes/upload", data={"csrf_token": csrf_of(c, "/resumes")},
                  files=[("files", (n, data, "application/pdf")) for n, data in files], follow_redirects=False)


# ------------------------------------------------------------------ passwords and tokens
def test_password_hashing():
    h = auth.hash_password("correct horse battery")
    assert h.startswith("scrypt$") and "correct" not in h
    assert auth.verify_password("correct horse battery", h)
    assert not auth.verify_password("wrong", h)
    assert auth.password_problem("short") and auth.password_problem("aaaaaaaaaaaa")
    assert auth.password_problem("a-good-passphrase") is None


def test_tokens_are_single_use_and_stored_hashed():
    tok = db.create_token("someone@example.com", "invite", None)
    assert db.peek_token(tok)
    assert tok not in str(db.list_invites())
    assert db.use_token(tok) and not db.use_token(tok)


# ------------------------------------------------------------------ public pages and access requests
def test_public_pages_and_security_headers(app_client):
    c = new_client()
    r = c.get("/")
    assert r.status_code == 200 and "Request access" in r.text
    h = r.headers
    assert "default-src 'self'" in h["content-security-policy"] and h["x-frame-options"] == "DENY"
    assert h["x-content-type-options"] == "nosniff"
    for p in ("/dashboard", "/resumes", "/admin", "/tracker"):
        assert c.get(p, follow_redirects=False).headers["location"].startswith("/login")
    assert c.get("/api/refresh/status").status_code == 401
    assert c.get("/docs").status_code == 404  # API docs are off


def test_forms_require_csrf(admin):
    assert admin.post("/admin/invite", data={"email": "x@example.com"}).status_code == 403
    c = new_client()
    assert c.post("/request-access", data={"name": "A", "email": "a@example.com"}).status_code == 403


def test_request_access_is_reviewed_by_admin(admin):
    c = new_client()
    r = c.post("/request-access", data={"csrf_token": csrf_of(c, "/request-access"), "name": "Priya Sharma",
                                        "email": "priya@example.com", "reason": "Product analyst roles"})
    assert "Request received" in r.text
    assert "priya@example.com" in admin.get("/admin").text
    rid = next(r["id"] for r in db.list_requests("pending") if r["email"] == "priya@example.com")
    r = admin.post(f"/admin/requests/{rid}/approve", data={"csrf_token": csrf_of(admin, "/admin")}, follow_redirects=False)
    assert "/invite/" not in r.headers["location"]  # never in the URL
    assert "/invite/" in admin.get(r.headers["location"]).text
    assert db.get_request(rid)["status"] == "approved"


def test_honeypot_and_existing_user_get_same_reply(admin):
    c = new_client()
    r = c.post("/request-access", data={"csrf_token": csrf_of(c, "/request-access"), "name": "Bot",
                                        "email": "bot@example.com", "website": "spam"})
    assert "Request received" in r.text
    assert not any(x["email"] == "bot@example.com" for x in db.list_requests())


def test_login_rate_limit_and_no_enumeration():
    auth.login_limiter.reset()
    c = new_client()
    bad = []
    for i in range(9):
        r = c.post("/login", data={"csrf_token": csrf_of(c, "/login"), "email": "admin@example.com", "password": f"x{i}"})
        bad.append(r.status_code)
    assert bad[:8] == [401] * 8 and bad[8] == 429
    auth.login_limiter.reset()
    r1 = c.post("/login", data={"csrf_token": csrf_of(c, "/login"), "email": "nobody@example.com", "password": "x"})
    r2 = c.post("/login", data={"csrf_token": csrf_of(c, "/login"), "email": "admin@example.com", "password": "x"})
    assert r1.status_code == r2.status_code == 401
    assert "match an active account" in r1.text and "match an active account" in r2.text
    auth.login_limiter.reset()


def test_open_redirect_blocked():
    auth.login_limiter.reset()
    c = new_client()
    r = c.post("/login", data={"csrf_token": csrf_of(c, "/login"), "email": "admin@example.com",
                               "password": "admin-pass-12345", "next": "//evil.example.com"}, follow_redirects=False)
    assert r.headers["location"] == "/dashboard"


# ------------------------------------------------------------------ admin-only and isolation
def test_admin_pages_forbidden_for_users(admin):
    c, _ = invite_and_register(admin, "ravi@example.com", "Ravi Kumar")
    assert c.get("/admin").status_code == 403
    assert c.post("/api/refresh", headers={"X-CSRF-Token": csrf_of(c, "/resumes")}).status_code == 403
    uid = db.get_user_by_email("ravi@example.com")["id"]
    assert c.post(f"/admin/users/{uid}/make-admin", data={"csrf_token": csrf_of(c, "/resumes")}).status_code == 403


def test_resume_upload_rules_and_isolation(admin):
    c, token = invite_and_register(admin, "meera@example.com", "Meera Iyer")
    pdf = lambda focus: make_pdf(resume_lines("Meera Iyer", "meera@example.com", focus))
    r = upload(c, [("Meera_Product_Analyst.pdf", pdf("Product Analytics"))])
    assert r.headers["location"].startswith("/profile")  # first upload goes on to roles
    # someone else's resume is refused
    r = upload(c, [("Other.pdf", make_pdf(resume_lines("Arjun Mehta", "arjun@example.com", "Strategy")))])
    assert "belongs to someone else" in unquote(r.headers["location"])
    # not a PDF / duplicate
    assert "not a PDF" in unquote(upload(c, [("x.pdf", b"hello" * 100)]).headers["location"])
    assert "already uploaded" in unquote(upload(c, [("Meera_Product_Analyst.pdf", pdf("Product Analytics"))]).headers["location"])
    # up to 5 versions, then refused
    for i, f in enumerate(["BI", "Strategy", "General", "Data"]):
        upload(c, [(f"Meera_{f}_{i}.pdf", pdf(f + " Analytics " + str(i)))])
    rows = db.list_resumes(db.get_user_by_email("meera@example.com")["id"])
    assert len(rows) == 5
    assert "already have 5" in unquote(upload(c, [("Meera_6.pdf", pdf("Six"))]).headers["location"])
    # another user can't download or delete Meera's resume
    other, _ = invite_and_register(admin, "kabir@example.com", "Kabir Singh")
    rid = rows[0]["id"]
    assert other.get(f"/resumes/{rid}/download").status_code == 404
    assert other.post(f"/resumes/{rid}/delete", data={"csrf_token": csrf_of(other, "/resumes")}).status_code == 404
    assert c.get(f"/resumes/{rid}/download").status_code == 200
    # profile was built from the uploads, without contact details
    prof = db.get_prefs(db.get_user_by_email("meera@example.com")["id"])["profile"]
    assert "Power BI" in prof["skills"] and "meera@example.com" not in str(prof["achievements"])


def test_disable_signs_user_out(admin):
    c, _ = invite_and_register(admin, "temp@example.com", "Temp User")
    assert c.get("/resumes").status_code == 200
    uid = db.get_user_by_email("temp@example.com")["id"]
    admin.post(f"/admin/users/{uid}/disable", data={"csrf_token": csrf_of(admin, "/admin")})
    assert c.get("/resumes", follow_redirects=False).status_code == 303


def test_cron_endpoint_needs_secret(app_client):
    c = new_client()
    assert c.post("/api/cron/refresh").status_code == 403
    assert c.post("/api/cron/refresh", headers={"X-Cron-Token": "wrong"}).status_code == 403


def test_delete_account_removes_data(admin):
    c, _ = invite_and_register(admin, "gone@example.com", "Gone Person")
    upload(c, [("Gone.pdf", make_pdf(resume_lines("Gone Person", "gone@example.com", "BI")))])
    uid = db.get_user_by_email("gone@example.com")["id"]
    r = c.post("/account/delete", data={"csrf_token": csrf_of(c, "/account"), "password": "user-pass-12345",
                                        "confirm_text": "DELETE"})
    assert "Account deleted" in r.text
    assert db.get_user(uid) is None and db.list_resumes(uid) == []
