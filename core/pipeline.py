"""Refresh: collect from every source → normalize → de-duplicate → verify → score → store."""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime

from . import db
from collections import Counter

from .config import IST, ensure_dirs
from .dates import age_days, today_ist
from .dedup import content_hash, dedup_key, dedupe, merge, same_posting
from .http import Http
from .scoring import pick_resume, score_job
from .verify import DEAD, EXPIRED, UNVERIFIABLE, apply_verification, result, verify_generic

log = logging.getLogger("getajob.pipeline")

STATE = {"running": False, "phase": "idle", "detail": "", "started": None, "finished": None, "error": ""}
_run_lock = threading.Lock()


def _set(phase: str, detail: str = ""):
    STATE["phase"], STATE["detail"] = phase, detail
    log.info("%s %s", phase, detail)


def start_refresh(trigger: str = "manual") -> bool:
    if STATE["running"]:
        return False
    t = threading.Thread(target=run_refresh, args=(trigger,), daemon=True, name="refresh")
    t.start()
    return True


def run_refresh(trigger: str = "manual") -> dict | None:
    if not _run_lock.acquire(blocking=False):
        return None
    from sources import ALL_SOURCES
    from sources.base import Ctx

    started = datetime.now(IST)
    STATE.update(running=True, started=started.isoformat(timespec="seconds"), error="")
    http = Http()
    summary: dict = {}
    try:
        ensure_dirs()
        db.init_db()
        settings = db.get_settings()
        profiles = db.active_profiles()
        prefs = search_prefs(settings, profiles)
        ctx = Ctx(prefs=prefs, http=http, demo=bool(settings.get("demo_mode")), now=started)
        db.clear_new_flags()
        if not ctx.demo and prefs.get("prefer_companies"):
            _set("collecting", "Looking up career boards for preferred companies")
            try:
                from sources.discover import discover_boards
                discover_boards(http, prefs["prefer_companies"])
            except Exception:
                log.exception("career-board lookup failed")

        # ---------------------------------------------------------------- 1. collect
        _set("collecting", "Searching all sources")
        collected, per_source = [], {}
        active = [s for s in ALL_SOURCES if s.kind != "manual"]
        for s in active:
            if not s.configured():
                db.health_set(s.name, portal=s.portal, label=s.label, configured=0, found=0, kept=0,
                              error="", note=("Not configured: add " + ", ".join(s.requires_keys) + " to .env")
                              if s.requires_keys else "No companies listed in config/employers.yaml")
        runnable = [s for s in active if s.configured()]
        with ThreadPoolExecutor(max_workers=max(1, len(runnable))) as ex:
            futs = {ex.submit(s.fetch, ctx): s for s in runnable}
            for f in as_completed(futs):
                s = futs[f]
                try:
                    jobs = f.result()
                except Exception as exc:
                    log.exception("source %s failed", s.name)
                    ctx.error(s.name, f"{exc.__class__.__name__}: {exc}")
                    jobs = []
                per_source[s.name] = len(jobs)
                collected.extend(jobs)
                _set("collecting", f"{s.label}: {len(jobs)} postings")

        # ---------------------------------------------------------------- 2. de-duplicate and store
        _set("merging", f"{len(collected)} postings collected")
        for j in collected:
            j["demo"] = ctx.demo
        batch = dedupe(collected)
        existing = {j["id"]: j for j in db.all_jobs(demo=ctx.demo)}
        by_city: dict[str, list[dict]] = {}
        by_hash: dict[str, dict] = {}
        for j in existing.values():
            by_city.setdefault(j.get("city") or "", []).append(j)
            if j.get("content_hash"):
                by_hash.setdefault(j["content_hash"], j)
        now_s = started.isoformat(timespec="seconds")
        new_count, to_save = 0, {}
        for job in batch:
            job["dedup_key"], job["content_hash"] = dedup_key(job), content_hash(job)
            match = existing.get(job["id"]) or next(
                (e for e in by_city.get(job.get("city") or "", [])
                 if not (e.get("extra") or {}).get("owner_id") and same_posting(e, job)), None)
            if match and match.get("status") in (EXPIRED, DEAD) and match.get("native_id") != job.get("native_id"):
                job["reposted"] = True
                job["repost_note"] = f"Same role was listed on {(match.get('posted_date') or match['first_seen'])[:10]} and closed"
                match = None
            if match:
                old_date = match.get("posted_date")
                merged = merge(dict(match), job)
                for k in ("first_seen", "manual_verified", "status", "last_verified", "verify_note", "fit_score",
                          "fit_detail", "llm_summary", "reposted", "repost_note", "flags"):
                    if k in match:
                        merged[k] = match[k]
                if (job.get("posted_date") and old_date and job.get("native_id") == match.get("native_id")
                        and (age_days(old_date, date.fromisoformat(job["posted_date"])) or 0) > 7):
                    merged["reposted"] = True
                    merged["repost_note"] = f"Listing date moved from {old_date} to {job['posted_date']}; first seen {match['first_seen'][:10]}"
                merged["last_seen"], merged["new_since_refresh"] = now_s, False
                merged["dedup_key"], merged["content_hash"] = dedup_key(merged), content_hash(merged)
                to_save[merged["id"]] = merged
            else:
                h = job.get("content_hash")
                prior = by_hash.get(h) if h else None
                if prior and prior["id"] != job["id"]:
                    job["reposted"] = True
                    job["repost_note"] = f"Same description first seen on {prior['first_seen'][:10]}"
                job["new_since_refresh"] = True
                new_count += 1
                to_save[job["id"]] = job
                by_city.setdefault(job.get("city") or "", []).append(job)
        db.save_jobs(list(to_save.values()))

        # ---------------------------------------------------------------- 3. verify
        today = today_ist(started)
        max_age = int(prefs.get("max_age_days") or 30)
        everything = db.all_jobs(demo=ctx.demo)
        cands = [j for j in everything if j.get("bucket") and
                 (j.get("posted_date") is None or (age_days(j["posted_date"], today) or 0) <= max_age + 3) and
                 not (j.get("status") in (EXPIRED, DEAD) and j.get("last_seen") != now_s)]
        cands.sort(key=lambda j: j.get("posted_date") or "0", reverse=True)
        cands = cands[: int(prefs.get("verify_limit") or 500)]
        _set("verifying", f"Checking {len(cands)} postings")
        from sources import BY_NAME
        demo_verify = ctx.fixture("verify") if ctx.demo else None
        verified: list[dict] = []
        done = [0]

        def check(job):
            if demo_verify is not None:
                spec = (demo_verify.get(job.get("native_id") or "") or demo_verify.get("source:" + job.get("source_name", ""))
                        or demo_verify.get("*", {"status": "verified"}))
                res = result(spec["status"], spec.get("note", "Demo data: treated as live"))
            elif not (job.get("apply_url") or job.get("source_url")):
                res = result(UNVERIFIABLE, "No link to check: confirm it yourself")
            else:
                src = BY_NAME.get(job.get("source_name"))
                res = None
                try:
                    res = src.verify(job, ctx) if src else None
                except Exception as exc:
                    res = result("needs_review", f"Check failed: {exc}")
                if res is None:
                    res = verify_generic(job, http)
            out = apply_verification(job, res)
            done[0] += 1
            if done[0] % 10 == 0:
                _set("verifying", f"{done[0]} of {len(cands)} checked")
            return out

        with ThreadPoolExecutor(max_workers=8) as ex:
            for out in ex.map(check, cands):
                verified.append(out)

        db.save_jobs(verified)

        # ---------------------------------------------------------------- 4. score for every user
        _set("scoring", f"Scoring for {len(profiles)} people")
        for uid, uprefs in profiles:
            score_user(uid, uprefs, settings)

        # ---------------------------------------------------------------- 5. health and summary
        by_src_ok: dict[str, int] = {}
        for j in db.all_jobs(demo=ctx.demo):
            if j.get("status") == "verified":
                by_src_ok[j.get("source_name")] = by_src_ok.get(j.get("source_name"), 0) + 1
        for s in runnable:
            db.health_set(s.name, portal=s.portal, label=s.label, configured=1, last_run=now_s,
                          found=per_source.get(s.name, 0), kept=by_src_ok.get(s.name, 0),
                          error=" | ".join(ctx.errors.get(s.name, [])), note=ctx.notes.get(s.name, ""))
        finished = datetime.now(IST)
        summary = {"collected": len(collected), "unique": len(batch), "new": new_count, "verified_checks": len(verified),
                   "requests": http.request_count, "seconds": round(time.time() - started.timestamp()),
                   "demo": ctx.demo, "per_source": per_source}
        db.run_add(started.isoformat(timespec="seconds"), finished.isoformat(timespec="seconds"), trigger, summary)
        _set("done", f"{new_count} new postings · {len(verified)} checked")
        return summary
    except Exception as exc:
        log.exception("refresh failed")
        STATE["error"] = f"Refresh failed: {exc}"
        _set("failed", str(exc))
        return None
    finally:
        http.close()
        STATE["running"] = False
        STATE["finished"] = datetime.now(IST).isoformat(timespec="seconds")
        _run_lock.release()


DEFAULT_QUERY_ROLES = [{"title": t, "queries": [t.lower()]} for t in
                       ("Business Analyst", "Data Analyst", "Software Engineer", "Product Manager",
                        "Financial Analyst", "Sales Manager", "HR Executive", "Digital Marketing Executive")]


def search_prefs(settings: dict, profiles: list[tuple[int, dict]]) -> dict:
    """What to search for: the roles most people asked for (capped), in every city anyone chose, and
    each person's roles and job families so a posting is kept when it is relevant to anyone."""
    from .select import city_lists
    count, first, pos = Counter(), {}, {}
    specs, cities = [], []
    for _, p in profiles:
        rs = [r if isinstance(r, dict) else {"title": r, "queries": [r.lower()]} for r in p.get("roles") or []]
        for i, r in enumerate(rs):
            count[r["title"]] += 1
            pos[r["title"]] = min(pos.get(r["title"], 99), i)
            first.setdefault(r["title"], r)
        specs.append((rs, p.get("families") or []))
        a, b = city_lists(p)
        cities += [c for c in a + b if c not in cities]
    ordered = sorted(count, key=lambda t: (-count[t], pos[t]))[: int(settings.get("max_query_roles") or 14)]
    roles = [first[t] for t in ordered] or DEFAULT_QUERY_ROLES
    if not specs:
        specs = [(DEFAULT_QUERY_ROLES, [])]
    if not cities:
        cities = ["Gurugram", "Delhi", "Noida", "Bengaluru", "Hyderabad", "Mumbai", "Pune"]
    prefer = sorted({c for _, p in profiles for c in p.get("prefer_companies") or []})
    return {**settings, "roles": roles, "cities": cities, "relevance_specs": specs, "prefer_companies": prefer}


def visible_to(job: dict, uid: int) -> bool:
    owner = (job.get("extra") or {}).get("owner_id")
    return owner is None or owner == uid


def score_user(uid: int, prefs: dict, settings: dict | None = None):
    """Score every recent posting for one person (no network). Runs after a refresh and after profile changes."""
    settings = settings or db.get_settings()
    prefs = {**settings, **prefs}
    max_age = int(settings.get("max_age_days") or 30)
    today = today_ist()
    rows = []
    for j in db.all_jobs(demo=bool(settings.get("demo_mode"))):
        if not visible_to(j, uid) or not j.get("bucket"):
            continue
        if j.get("posted_date") and (age_days(j["posted_date"], today) or 0) > max_age + 5:
            continue
        score, detail = score_job(j, prefs)
        rows.append({"job_id": j["id"], "fit_score": score, "detail": detail, "resume_variant": pick_resume(j, prefs)})
    db.save_user_scores(uid, rows)
    return len(rows)


def score_user_async(uid: int):
    def go():
        try:
            score_user(uid, db.get_prefs(uid))
        except Exception:
            log.exception("scoring for user %s failed", uid)
    threading.Thread(target=go, daemon=True, name=f"score-{uid}").start()


def reverify_one(job_id: str, uid: int | None = None) -> dict | None:
    """Re-run verification for one posting and re-score it for one person (used after an import)."""
    from sources import BY_NAME
    from sources.base import Ctx
    settings = db.get_settings()
    job = db.get_job(job_id)
    if not job:
        return None
    http = Http()
    try:
        ctx = Ctx(prefs={**settings, "roles": [], "cities": []}, http=http,
                  demo=bool(settings.get("demo_mode")))
        if not (job.get("apply_url") or job.get("source_url")):
            res = result(UNVERIFIABLE, "No link to check: confirm it yourself")
        else:
            src = BY_NAME.get(job.get("source_name"))
            res = (src.verify(job, ctx) if src else None) or verify_generic(job, http)
        job = apply_verification(job, res)
        job["dedup_key"], job["content_hash"] = dedup_key(job), content_hash(job)
        db.save_jobs([job])
        if uid is not None:
            prefs = {**settings, **db.get_prefs(uid)}
            score, detail = score_job(job, prefs)
            db.save_user_scores(uid, [{"job_id": job["id"], "fit_score": score, "detail": detail,
                                       "resume_variant": pick_resume(job, prefs)}])
        return job
    finally:
        http.close()


def upgrade_profiles():
    """Rebuild saved profiles made by an older version of the resume parser (from the stored resume text)."""
    from .resume import PROFILE_VERSION, build_profile
    for u in db.list_users():
        try:
            prefs = db.get_prefs(u["id"])
            if not prefs.get("profile") or prefs["profile"].get("v") == PROFILE_VERSION:
                continue
            rows = db.list_resumes(u["id"], with_text=True)
            if rows:
                prefs["profile"] = build_profile({r["filename"]: r["text"] for r in rows})
                db.save_prefs(u["id"], prefs)
                log.info("rebuilt profile for user %s", u["id"])
        except Exception:
            log.exception("profile upgrade for user %s failed", u.get("id"))


def startup_tasks():
    upgrade_profiles()
    rescore_everyone()


def rescore_everyone():
    for uid, prefs in db.active_profiles():
        try:
            score_user(uid, prefs)
        except Exception:
            log.exception("scoring for user %s failed", uid)
