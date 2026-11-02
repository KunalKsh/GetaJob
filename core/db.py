"""Storage (SQLAlchemy Core): Postgres in production, SQLite locally.

Jobs are a shared pool. Everything personal (resumes, preferences, fit scores, tracker,
manual verifications) is keyed by user id, and every query filters by it.
History is never deleted for jobs; a user can delete their own data.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
from datetime import datetime, timedelta

from sqlalchemy import (Boolean, Column, DateTime, Float, ForeignKey, Integer, LargeBinary, MetaData, String,
                        Table, Text, UniqueConstraint, create_engine, delete, func, insert, select, update)
from sqlalchemy.engine import Engine

from . import config
from .config import DEFAULT_PREFS, DEFAULT_SETTINGS, IST, merged

md = MetaData()

users = Table(
    "users", md,
    Column("id", Integer, primary_key=True),
    Column("email", String(254), nullable=False, unique=True),
    Column("name", String(120), nullable=False, default=""),
    Column("password_hash", String(255), nullable=False, default=""),
    Column("role", String(16), nullable=False, default="user"),        # user | admin
    Column("status", String(16), nullable=False, default="active"),    # active | disabled
    Column("session_version", Integer, nullable=False, default=1),
    Column("created_at", DateTime(timezone=True)),
    Column("last_login", DateTime(timezone=True)),
)
access_requests = Table(
    "access_requests", md,
    Column("id", Integer, primary_key=True),
    Column("email", String(254), nullable=False),
    Column("name", String(120), nullable=False, default=""),
    Column("reason", Text, nullable=False, default=""),
    Column("status", String(16), nullable=False, default="pending"),   # pending | approved | declined
    Column("created_at", DateTime(timezone=True)),
    Column("decided_at", DateTime(timezone=True)),
    Column("decided_by", Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
)
invites = Table(
    "invites", md,
    Column("id", Integer, primary_key=True),
    Column("email", String(254), nullable=False),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("purpose", String(16), nullable=False, default="invite"),   # invite | reset | setup
    Column("created_by", Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    Column("created_at", DateTime(timezone=True)),
    Column("expires_at", DateTime(timezone=True)),
    Column("used_at", DateTime(timezone=True)),
)
resumes = Table(
    "resumes", md,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("filename", String(200), nullable=False),
    Column("content", LargeBinary, nullable=False),
    Column("size", Integer, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("text", Text, nullable=False, default=""),
    Column("identity", Text, nullable=False, default="{}"),
    Column("uploaded_at", DateTime(timezone=True)),
    UniqueConstraint("user_id", "sha256", name="uq_resume_user_sha"),
)
profiles = Table(
    "profiles", md,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("prefs", Text, nullable=False, default="{}"),
    Column("updated_at", DateTime(timezone=True)),
)
settings_t = Table(
    "settings", md,
    Column("key", String(64), primary_key=True),
    Column("value", Text, nullable=False),
)
jobs = Table(
    "jobs", md,
    Column("id", String(32), primary_key=True),
    Column("data", Text, nullable=False),
    Column("bucket", String(8)),
    Column("status", String(24)),
    Column("posted_date", String(10)),
    Column("dedup_key", String(400), index=True),
    Column("content_hash", String(40), index=True),
    Column("demo", Boolean, nullable=False, default=False),
    Column("first_seen", String(32)),
    Column("last_seen", String(32)),
)
user_jobs = Table(
    "user_jobs", md,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("job_id", String(32), ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True),
    Column("fit_score", Integer),
    Column("detail", Text, nullable=False, default="{}"),
    Column("resume_variant", String(200), default=""),
    Column("manual_verified", Boolean, nullable=False, default=False),
    Column("manual_posted", String(10)),
    Column("summary", Text),
    Column("updated_at", DateTime(timezone=True)),
)
tracker_t = Table(
    "tracker", md,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("job_id", String(32), ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True),
    Column("status", String(16), nullable=False, default="New"),
    Column("notes", Text, nullable=False, default=""),
    Column("follow_up", String(10), nullable=False, default=""),
    Column("updated_at", DateTime(timezone=True)),
)
source_health = Table(
    "source_health", md,
    Column("source", String(40), primary_key=True),
    Column("portal", String(80)), Column("label", String(80)), Column("configured", Boolean),
    Column("last_run", String(32)), Column("found", Integer, default=0), Column("kept", Integer, default=0),
    Column("error", Text, default=""), Column("note", Text, default=""),
)
runs = Table(
    "runs", md,
    Column("id", Integer, primary_key=True),
    Column("started", String(32)), Column("finished", String(32)), Column("trigger", String(32)),
    Column("summary", Text),
)

_engine: Engine | None = None
_lock = threading.Lock()


def now() -> datetime:
    return datetime.now(IST)


def engine() -> Engine:
    global _engine
    with _lock:
        if _engine is None:
            url = config.database_url()
            if url.startswith("sqlite"):
                config.ensure_dirs()
                _engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})
            else:
                _engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)
        return _engine


def reset_engine():
    """Tests point DATABASE_URL somewhere new and call this."""
    global _engine
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None


def init_db():
    md.create_all(engine())


def _row(r) -> dict | None:
    return dict(r._mapping) if r is not None else None


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------- users
def create_user(email: str, name: str, password_hash: str, role: str = "user") -> int:
    with engine().begin() as c:
        return c.execute(insert(users).values(email=email.lower().strip(), name=name.strip()[:120],
                                              password_hash=password_hash, role=role, status="active",
                                              session_version=1, created_at=now())).inserted_primary_key[0]


def get_user(uid: int) -> dict | None:
    with engine().connect() as c:
        return _row(c.execute(select(users).where(users.c.id == uid)).first())


def get_user_by_email(email: str) -> dict | None:
    with engine().connect() as c:
        return _row(c.execute(select(users).where(users.c.email == (email or "").lower().strip())).first())


def list_users() -> list[dict]:
    with engine().connect() as c:
        return [_row(r) for r in c.execute(select(users).order_by(users.c.created_at))]


def update_user(uid: int, **fields):
    with engine().begin() as c:
        c.execute(update(users).where(users.c.id == uid).values(**fields))


def bump_session(uid: int):
    """Sign the user out everywhere (password change, disable)."""
    with engine().begin() as c:
        c.execute(update(users).where(users.c.id == uid).values(session_version=users.c.session_version + 1))


def admin_exists() -> bool:
    with engine().connect() as c:
        return c.execute(select(func.count()).select_from(users).where(users.c.role == "admin")).scalar() > 0


def delete_user(uid: int):
    with engine().begin() as c:
        for t in (tracker_t, user_jobs, resumes, profiles):
            c.execute(delete(t).where(t.c.user_id == uid))
        c.execute(update(access_requests).where(access_requests.c.decided_by == uid).values(decided_by=None))
        c.execute(update(invites).where(invites.c.created_by == uid).values(created_by=None))
        c.execute(delete(users).where(users.c.id == uid))


# ---------------------------------------------------------------- access requests
def add_request(email: str, name: str, reason: str) -> bool:
    """Returns False if this email already has a pending request (the caller shows the same message either way)."""
    email = email.lower().strip()
    with engine().begin() as c:
        exists = c.execute(select(access_requests.c.id).where(access_requests.c.email == email,
                                                              access_requests.c.status == "pending")).first()
        if exists:
            return False
        c.execute(insert(access_requests).values(email=email, name=name.strip()[:120], reason=reason.strip()[:1000],
                                                 status="pending", created_at=now()))
        return True


def list_requests(status: str | None = None) -> list[dict]:
    q = select(access_requests).order_by(access_requests.c.created_at.desc())
    if status:
        q = q.where(access_requests.c.status == status)
    with engine().connect() as c:
        return [_row(r) for r in c.execute(q)]


def get_request(rid: int) -> dict | None:
    with engine().connect() as c:
        return _row(c.execute(select(access_requests).where(access_requests.c.id == rid)).first())


def decide_request(rid: int, status: str, by: int):
    with engine().begin() as c:
        c.execute(update(access_requests).where(access_requests.c.id == rid)
                  .values(status=status, decided_at=now(), decided_by=by))


# ---------------------------------------------------------------- invites / reset / setup tokens
def create_token(email: str, purpose: str, created_by: int | None, days: float = 7) -> str:
    token = secrets.token_urlsafe(32)
    with engine().begin() as c:
        if purpose in ("setup", "reset"):  # only one live link of these kinds per email
            c.execute(update(invites).where(invites.c.email == email.lower(), invites.c.purpose == purpose,
                                            invites.c.used_at.is_(None)).values(used_at=now()))
        c.execute(insert(invites).values(email=email.lower().strip(), token_hash=_hash(token), purpose=purpose,
                                         created_by=created_by, created_at=now(),
                                         expires_at=now() + timedelta(days=days)))
    return token


def peek_token(token: str) -> dict | None:
    """A live (unused, unexpired) token, or None."""
    with engine().connect() as c:
        r = _row(c.execute(select(invites).where(invites.c.token_hash == _hash(token or ""))).first())
    if not r or r["used_at"] is not None:
        return None
    exp = r["expires_at"]
    if exp is not None and exp.tzinfo is None:
        exp = exp.replace(tzinfo=IST)
    if exp is not None and exp < now():
        return None
    return r


def use_token(token: str) -> dict | None:
    r = peek_token(token)
    if not r:
        return None
    with engine().begin() as c:
        res = c.execute(update(invites).where(invites.c.id == r["id"], invites.c.used_at.is_(None)).values(used_at=now()))
        if res.rowcount != 1:
            return None
    return r


def list_invites(limit: int = 50) -> list[dict]:
    with engine().connect() as c:
        return [_row(r) for r in c.execute(select(invites).where(invites.c.purpose == "invite")
                                           .order_by(invites.c.created_at.desc()).limit(limit))]


# ---------------------------------------------------------------- resumes
def add_resume(uid: int, filename: str, content: bytes, sha: str, text: str, identity: dict) -> int:
    with engine().begin() as c:
        return c.execute(insert(resumes).values(user_id=uid, filename=filename[:200], content=content, size=len(content),
                                                sha256=sha, text=text, identity=json.dumps(identity),
                                                uploaded_at=now())).inserted_primary_key[0]


def list_resumes(uid: int, with_text: bool = False) -> list[dict]:
    cols = [resumes.c.id, resumes.c.filename, resumes.c.size, resumes.c.sha256, resumes.c.identity,
            resumes.c.uploaded_at] + ([resumes.c.text] if with_text else [])
    with engine().connect() as c:
        rows = [_row(r) for r in c.execute(select(*cols).where(resumes.c.user_id == uid).order_by(resumes.c.uploaded_at))]
    for r in rows:
        r["identity"] = json.loads(r["identity"] or "{}")
    return rows


def get_resume(uid: int, rid: int) -> dict | None:
    with engine().connect() as c:
        return _row(c.execute(select(resumes).where(resumes.c.user_id == uid, resumes.c.id == rid)).first())


def delete_resume(uid: int, rid: int) -> bool:
    with engine().begin() as c:
        return c.execute(delete(resumes).where(resumes.c.user_id == uid, resumes.c.id == rid)).rowcount == 1


# ---------------------------------------------------------------- per-user prefs, site settings
def get_prefs(uid: int) -> dict:
    with engine().connect() as c:
        r = c.execute(select(profiles.c.prefs).where(profiles.c.user_id == uid)).first()
    return merged(DEFAULT_PREFS, json.loads(r[0]) if r else {})


def save_prefs(uid: int, prefs: dict):
    data = json.dumps(prefs, ensure_ascii=False)
    with engine().begin() as c:
        if c.execute(select(profiles.c.user_id).where(profiles.c.user_id == uid)).first():
            c.execute(update(profiles).where(profiles.c.user_id == uid).values(prefs=data, updated_at=now()))
        else:
            c.execute(insert(profiles).values(user_id=uid, prefs=data, updated_at=now()))


def active_profiles() -> list[tuple[int, dict]]:
    """(user id, prefs) for every active user who has confirmed their roles."""
    with engine().connect() as c:
        rows = c.execute(select(profiles.c.user_id, profiles.c.prefs).join(users, users.c.id == profiles.c.user_id)
                         .where(users.c.status == "active")).all()
    out = []
    for uid, p in rows:
        prefs = merged(DEFAULT_PREFS, json.loads(p or "{}"))
        if prefs.get("confirmed"):
            out.append((uid, prefs))
    return out


def get_settings() -> dict:
    with engine().connect() as c:
        r = c.execute(select(settings_t.c.value).where(settings_t.c.key == "site")).first()
    return merged(DEFAULT_SETTINGS, json.loads(r[0]) if r else {})


def save_settings(s: dict):
    data = json.dumps(s)
    with engine().begin() as c:
        if c.execute(select(settings_t.c.key).where(settings_t.c.key == "site")).first():
            c.execute(update(settings_t).where(settings_t.c.key == "site").values(value=data))
        else:
            c.execute(insert(settings_t).values(key="site", value=data))


# ---------------------------------------------------------------- shared job pool
def _job_values(j: dict) -> dict:
    core = {k: v for k, v in j.items() if k not in ("fit_score", "fit_detail", "resume_variant", "manual_verified",
                                                    "llm_summary", "track", "age", "tier")}
    return dict(id=j["id"], data=json.dumps(core, ensure_ascii=False), bucket=j.get("bucket"), status=j.get("status"),
                posted_date=j.get("posted_date"), dedup_key=(j.get("dedup_key") or "")[:400],
                content_hash=j.get("content_hash"), demo=bool(j.get("demo")), first_seen=j.get("first_seen"),
                last_seen=j.get("last_seen"))


def save_jobs(items: list[dict]):
    if not items:
        return
    with engine().begin() as c:
        existing = {r[0] for r in c.execute(select(jobs.c.id).where(jobs.c.id.in_([j["id"] for j in items])))}
        new = [_job_values(j) for j in items if j["id"] not in existing]
        if new:
            c.execute(insert(jobs), new)
        for j in items:
            if j["id"] in existing:
                v = _job_values(j)
                c.execute(update(jobs).where(jobs.c.id == j["id"]).values(**{k: v[k] for k in v if k != "id"}))


def all_jobs(demo: bool | None = None) -> list[dict]:
    q = select(jobs.c.data)
    if demo is not None:
        q = q.where(jobs.c.demo == bool(demo))
    with engine().connect() as c:
        return [json.loads(r[0]) for r in c.execute(q)]


def get_job(job_id: str) -> dict | None:
    with engine().connect() as c:
        r = c.execute(select(jobs.c.data).where(jobs.c.id == job_id)).first()
    return json.loads(r[0]) if r else None


def clear_new_flags():
    items = [j for j in all_jobs() if j.get("new_since_refresh")]
    for j in items:
        j["new_since_refresh"] = False
    save_jobs(items)


# ---------------------------------------------------------------- per-user scores and overrides
def save_user_scores(uid: int, rows: list[dict]):
    """rows: {job_id, fit_score, detail, resume_variant}. Keeps manual verification and summaries."""
    if not rows:
        return
    with engine().begin() as c:
        have = {r[0] for r in c.execute(select(user_jobs.c.job_id).where(user_jobs.c.user_id == uid))}
        new = [dict(user_id=uid, job_id=r["job_id"], fit_score=r["fit_score"], detail=json.dumps(r["detail"]),
                    resume_variant=r["resume_variant"][:200], manual_verified=False, updated_at=now())
               for r in rows if r["job_id"] not in have]
        if new:
            c.execute(insert(user_jobs), new)
        for r in rows:
            if r["job_id"] in have:
                c.execute(update(user_jobs).where(user_jobs.c.user_id == uid, user_jobs.c.job_id == r["job_id"])
                          .values(fit_score=r["fit_score"], detail=json.dumps(r["detail"]),
                                  resume_variant=r["resume_variant"][:200], updated_at=now()))


def set_user_job(uid: int, job_id: str, **fields):
    with engine().begin() as c:
        if c.execute(select(user_jobs.c.job_id).where(user_jobs.c.user_id == uid, user_jobs.c.job_id == job_id)).first():
            c.execute(update(user_jobs).where(user_jobs.c.user_id == uid, user_jobs.c.job_id == job_id)
                      .values(updated_at=now(), **fields))
        else:
            c.execute(insert(user_jobs).values(user_id=uid, job_id=job_id, detail="{}", updated_at=now(),
                                               **{"manual_verified": False, **fields}))


def user_job_map(uid: int) -> dict[str, dict]:
    with engine().connect() as c:
        return {r.job_id: _row(r) for r in c.execute(select(user_jobs).where(user_jobs.c.user_id == uid))}


def overlay(job: dict, uj: dict | None) -> dict:
    """A job as one user sees it: their fit score, resume pick and manual confirmation."""
    j = dict(job)
    if uj:
        j["fit_score"] = uj.get("fit_score")
        j["fit_detail"] = json.loads(uj.get("detail") or "{}")
        j["resume_variant"] = uj.get("resume_variant") or ""
        j["manual_verified"] = bool(uj.get("manual_verified"))
        j["llm_summary"] = uj.get("summary")
        if uj.get("manual_posted"):
            j["posted_date"], j["posted_date_confidence"] = uj["manual_posted"], "user"
            j["date_note"] = "Date entered by you"
    else:
        j.update(fit_score=None, fit_detail={}, resume_variant="", manual_verified=False)
    return j


def jobs_for_user(uid: int, demo: bool) -> list[dict]:
    m = user_job_map(uid)
    return [overlay(j, m.get(j["id"])) for j in all_jobs(demo=demo)]


def job_for_user(uid: int, job_id: str) -> dict | None:
    j = get_job(job_id)
    if not j:
        return None
    return overlay(j, user_job_map(uid).get(job_id))


# ---------------------------------------------------------------- tracker
TRACKER_STATUSES = ["New", "Shortlisted", "Applied", "Interview", "Rejected", "Offer"]


def tracker_all(uid: int) -> dict[str, dict]:
    with engine().connect() as c:
        return {r.job_id: _row(r) for r in c.execute(select(tracker_t).where(tracker_t.c.user_id == uid))}


def tracker_set(uid: int, job_id: str, status: str | None = None, notes: str | None = None,
                follow_up: str | None = None) -> dict:
    if status is not None and status not in TRACKER_STATUSES:
        raise ValueError(f"Unknown status {status}")
    with engine().begin() as c:
        cur = _row(c.execute(select(tracker_t).where(tracker_t.c.user_id == uid, tracker_t.c.job_id == job_id)).first())
        rec = cur or {"user_id": uid, "job_id": job_id, "status": "New", "notes": "", "follow_up": ""}
        if status is not None:
            rec["status"] = status
        if notes is not None:
            rec["notes"] = notes[:4000]
        if follow_up is not None:
            rec["follow_up"] = follow_up[:10]
        rec["updated_at"] = now()
        vals = {k: rec[k] for k in ("status", "notes", "follow_up", "updated_at")}
        if cur:
            c.execute(update(tracker_t).where(tracker_t.c.user_id == uid, tracker_t.c.job_id == job_id).values(**vals))
        else:
            c.execute(insert(tracker_t).values(user_id=uid, job_id=job_id, **vals))
    return {**rec, "updated_at": rec["updated_at"].isoformat(timespec="seconds")}


# ---------------------------------------------------------------- source health & runs
def health_set(source: str, **fields):
    with engine().begin() as c:
        cur = _row(c.execute(select(source_health).where(source_health.c.source == source)).first())
        if cur:
            c.execute(update(source_health).where(source_health.c.source == source).values(**fields))
        else:
            base = {"portal": "", "label": source, "configured": False, "last_run": None, "found": 0, "kept": 0,
                    "error": "", "note": ""}
            base.update(fields)
            c.execute(insert(source_health).values(source=source, **base))


def health_all() -> list[dict]:
    with engine().connect() as c:
        return [_row(r) for r in c.execute(select(source_health).order_by(source_health.c.source))]


def run_add(started: str, finished: str, trigger: str, summary: dict):
    with engine().begin() as c:
        c.execute(insert(runs).values(started=started, finished=finished, trigger=trigger, summary=json.dumps(summary)))


def last_run() -> dict | None:
    with engine().connect() as c:
        r = _row(c.execute(select(runs).order_by(runs.c.id.desc()).limit(1)).first())
    if r:
        r["summary"] = json.loads(r["summary"] or "{}")
    return r
