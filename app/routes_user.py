"""Signed-in pages: resumes, profile & roles, dashboard, review, tracker, import, account, exports."""
from __future__ import annotations

import hashlib
import re
from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from rapidfuzz import fuzz

from core import auth, db, llm, pipeline
from core.config import MAX_RESUME_BYTES, MAX_RESUMES, MAX_RESUME_PAGES
from core.dates import TIERS, today_ist
from core.dedup import norm_title
from core.export import top100_xlsx, tracker_csv, tracker_xlsx
from core.locations import ALL_CITIES, MAJOR_METROS, NCR_CITIES, region_label
from core.normalize import PORTALS, make_id
from core.relevance import families_from
from core.resume import (build_profile, default_families, detect_families, extract_pdf_bytes, identity, is_pdf,
                         same_person, suggest_roles)
from core.select import city_lists, ineligible_reason, select_buckets
from core.skills import INDUSTRIES
from core.taxonomy import BAND_HINT, BAND_NAMES, BY_KEY, FAMILIES, companies_for, default_bands

from .web import client_ip, decorate, page, portals_of, redirect, require_user

router = APIRouter()

ROLE_TYPE_OPTIONS = ["Full-time", "Part-time", "Contract", "Internship", "Freelance"]
WORK_MODE_OPTIONS = ["onsite", "hybrid", "remote"]
NOTICE_OPTIONS = ["Immediate joiner", "15 days", "30 days", "60 days", "90 days", "Currently studying"]


def view_prefs(uid: int) -> dict:
    """A person's preferences merged with the site-wide settings that the ranking needs."""
    return {**db.get_settings(), **db.get_prefs(uid)}


def my_jobs(uid: int, prefs: dict) -> list[dict]:
    return [j for j in db.jobs_for_user(uid, bool(prefs.get("demo_mode"))) if pipeline.visible_to(j, uid)]


def own_job(uid: int, job_id: str) -> dict:
    j = db.job_for_user(uid, job_id)
    if not j or not pipeline.visible_to(j, uid):
        raise HTTPException(404, "That job isn't available.")
    return j


def _lines(s: str) -> list[str]:
    return [x.strip() for x in re.split(r"[\n,]", s or "") if x.strip()][:50]


# ---------------------------------------------------------------------------- resumes
def rebuild_profile(uid: int):
    rows = db.list_resumes(uid, with_text=True)
    prefs = db.get_prefs(uid)
    prefs["profile"] = build_profile({r["filename"]: r["text"] for r in rows}) if rows else {}
    db.save_prefs(uid, prefs)
    pipeline.score_user_async(uid)


@router.get("/resumes")
def resumes_page(request: Request, user: dict = Depends(require_user), msg: str = "", err: str = ""):
    rows = db.list_resumes(user["id"])
    prof = db.get_prefs(user["id"]).get("profile") or {}
    return page(request, "resumes.html", user=user, rows=rows, profile=prof, msg=msg, err=err,
                max_resumes=MAX_RESUMES, max_mb=MAX_RESUME_BYTES // (1024 * 1024))


@router.post("/resumes/upload")
async def resumes_upload(request: Request, files: list[UploadFile] = File(...), user: dict = Depends(require_user)):
    uid = user["id"]
    if not auth.upload_limiter.allow(f"{uid}"):
        return redirect("/resumes?" + urlencode({"err": "Too many uploads in the last hour. Try again later."}))
    existing = db.list_resumes(uid)
    ids = [r["identity"] for r in existing]
    added, problems = 0, []
    for f in files[:MAX_RESUMES]:
        name = re.sub(r"[^\w.\- ()]+", "_", (f.filename or "resume.pdf"))[-120:]
        if len(existing) + added >= MAX_RESUMES:
            problems.append(f"{name}: you already have {MAX_RESUMES} resumes. Delete one to add another.")
            break
        data = await f.read(MAX_RESUME_BYTES + 1)
        if len(data) > MAX_RESUME_BYTES:
            problems.append(f"{name}: larger than {MAX_RESUME_BYTES // (1024 * 1024)} MB.")
            continue
        if not name.lower().endswith(".pdf") or not is_pdf(data):
            problems.append(f"{name}: not a PDF file. Export your resume as PDF and upload that.")
            continue
        sha = hashlib.sha256(data).hexdigest()
        if any(r["sha256"] == sha for r in existing):
            problems.append(f"{name}: this exact file is already uploaded.")
            continue
        try:
            text = extract_pdf_bytes(data, MAX_RESUME_PAGES)
        except Exception:
            problems.append(f"{name}: the PDF couldn't be read. Try exporting it again.")
            continue
        if len(text.strip()) < 200:
            problems.append(f"{name}: no readable text found (a scanned image?). Upload a text-based PDF.")
            continue
        ident = identity(text)
        ok, why = same_person(ident, ids)
        if not ok:
            problems.append(f"{name}: {why}")
            continue
        try:
            db.add_resume(uid, name, data, sha, text, ident)
        except Exception:
            problems.append(f"{name}: couldn't be saved (already uploaded?).")
            continue
        ids.append(ident)
        added += 1
    if added:
        rebuild_profile(uid)
    params = {}
    if added:
        params["msg"] = f"Added {added} resume{'s' if added != 1 else ''}."
    if problems:
        params["err"] = " | ".join(problems)
    first_time = added and not db.get_prefs(uid).get("confirmed")
    return redirect(("/profile?" if first_time and not problems else "/resumes?") + urlencode(params))


@router.post("/resumes/{rid}/delete")
def resume_delete(rid: int, user: dict = Depends(require_user)):
    if db.delete_resume(user["id"], rid):
        rebuild_profile(user["id"])
        return redirect("/resumes?msg=Resume+deleted.")
    raise HTTPException(404, "That resume isn't on your account.")


@router.get("/resumes/{rid}/download")
def resume_download(rid: int, user: dict = Depends(require_user)):
    r = db.get_resume(user["id"], rid)
    if not r:
        raise HTTPException(404, "That resume isn't on your account.")
    safe = re.sub(r"[^\w.\- ]+", "_", r["filename"])
    return Response(r["content"], media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{safe}"'})


# ---------------------------------------------------------------------------- profile & roles
def _families_of(prefs: dict, prof: dict) -> list[str]:
    if prefs.get("families"):
        return [k for k in prefs["families"] if k in BY_KEY]
    if prefs.get("confirmed") and prefs.get("roles"):
        return families_from(prefs["roles"]) or default_families(prof)
    return default_families(prof)


def _default_cities(prefs: dict, prof: dict) -> tuple[list[str], list[str]]:
    if prefs.get("primary_cities") is not None or prefs.get("ncr_cities") is not None:
        return city_lists(prefs)
    loc = prof.get("location") or ""
    primary = NCR_CITIES if (loc in NCR_CITIES or loc == "Delhi NCR" or not loc or loc not in ALL_CITIES) else [loc]
    pool = NCR_CITIES + MAJOR_METROS
    return list(primary), [c for c in pool if c not in primary][:6]


def _role_payload(rows: list[dict]) -> list[dict]:
    return [{"title": r["title"], "score": r["score"], "reason": r["reason"], "family": r.get("family", ""),
             "family_name": r.get("family_name", "")} for r in rows]


@router.get("/profile")
def profile_page(request: Request, user: dict = Depends(require_user), msg: str = "", step: int = 1):
    prefs = db.get_prefs(user["id"])
    prof = prefs.get("profile") or {}
    if not prof:
        return redirect("/resumes?" + urlencode({"msg": "Upload your resume first. Your roles are suggested from it."}))
    detected = prof.get("families") or detect_families(prof)
    fams = _families_of(prefs, prof)
    suggestions = suggest_roles(prof, fams)
    chosen = {(r["title"] if isinstance(r, dict) else r) for r in prefs.get("roles") or []}
    if not chosen:
        chosen = {s["title"] for s in suggestions if s["score"] >= 75 and "stretch" not in s["reason"]} or \
                 {s["title"] for s in suggestions[:5]}
    custom = [r for r in chosen if r not in {s["title"] for s in suggestions}]
    years = float(prof.get("years_experience") or 0)
    bands = prefs.get("seniority_bands") or default_bands(years)
    primary, secondary = _default_cities(prefs, prof)
    fam_rows = sorted(FAMILIES, key=lambda f: -next((d["score"] for d in detected if d["key"] == f["key"]), 0))
    fam_info = {d["key"]: d for d in detected}
    return page(request, "profile.html", user=user, prefs=prefs, profile=prof, suggestions=suggestions,
                chosen=chosen, custom="\n".join(custom), msg=msg, step=max(1, min(4, step)),
                families=fam_rows, fam_info=fam_info, chosen_fams=fams,
                company_suggestions=companies_for([f["key"] for f in FAMILIES]),
                bands=BAND_NAMES, band_hint=BAND_HINT, chosen_bands=bands, years=years,
                role_type_options=ROLE_TYPE_OPTIONS, work_mode_options=WORK_MODE_OPTIONS,
                notice_options=NOTICE_OPTIONS, industries=list(INDUSTRIES), all_cities=ALL_CITIES,
                primary=primary, secondary=secondary)


@router.get("/api/roles")
def roles_for_families(request: Request, f: list[str] = Query(default=[]), user: dict = Depends(require_user)):
    """Role suggestions for the job families ticked on the profile page (no page reload)."""
    prof = db.get_prefs(user["id"]).get("profile") or {}
    fams = [k for k in f if k in BY_KEY][:8]
    if not prof:
        return {"roles": []}
    return {"roles": _role_payload(suggest_roles(prof, fams or None))}


@router.post("/profile")
async def profile_save(request: Request, user: dict = Depends(require_user)):
    form = await request.form()
    uid = user["id"]
    prefs = db.get_prefs(uid)
    prof = prefs.get("profile") or {}
    fams = [k for k in form.getlist("families") if k in BY_KEY][:8] or (default_families(prof) if prof else [])
    sugg = {s["title"]: s for s in suggest_roles(prof, fams)} if prof else {}
    roles = []
    for t in form.getlist("roles")[:24]:
        t = str(t)[:80]
        s = sugg.get(t)
        roles.append({"title": t, "queries": s["queries"] if s else [t.lower()]})
    for t in _lines(form.get("custom_roles", ""))[:8]:
        t = t[:80]
        if t not in {r["title"] for r in roles}:
            roles.append({"title": t, "queries": [t.lower()]})
    if not roles:
        return redirect("/profile?step=2&msg=Pick+at+least+one+role.")

    def num(name):
        v = form.get(name)
        try:
            return max(0.0, min(500.0, float(v))) if v not in (None, "") else None
        except ValueError:
            return None

    primary = [c for c in form.getlist("primary_cities") if c in ALL_CITIES][:20]
    if not primary:
        return redirect("/profile?step=4&msg=Choose+at+least+one+first-choice+city.")
    secondary = [c for c in form.getlist("secondary_cities") if c in ALL_CITIES and c not in primary][:25]
    for old in ("ncr_cities", "metro_cities", "seniority"):
        prefs.pop(old, None)
    prefs.update(
        families=fams, roles=roles, confirmed=True,
        salary_min_lpa=num("salary_min_lpa"), salary_max_lpa=num("salary_max_lpa"),
        salary_hard_filter=form.get("salary_hard_filter") == "on",
        seniority_bands=[b for b in form.getlist("seniority_bands") if b in BAND_NAMES] or None,
        role_types=[s for s in form.getlist("role_types") if s in ROLE_TYPE_OPTIONS] or ["Full-time"],
        work_modes=[m for m in form.getlist("work_modes") if m in WORK_MODE_OPTIONS],
        prefer_industries=[s for s in form.getlist("prefer_industries") if s in INDUSTRIES],
        avoid_industries=[s for s in form.getlist("avoid_industries") if s in INDUSTRIES],
        notice_period=form.get("notice_period") if form.get("notice_period") in NOTICE_OPTIONS else prefs["notice_period"],
        prefer_companies=[x[:80] for x in _lines(form.get("prefer_companies", ""))][:40],
        exclude_companies=[x[:80] for x in _lines(form.get("exclude_companies", ""))],
        exclude_title_words=[w[:40] for w in _lines(form.get("exclude_title_words", ""))],
        primary_cities=primary, secondary_cities=secondary,
        use_llm_summary=form.get("use_llm_summary") == "on",
    )
    db.save_prefs(uid, prefs)
    pipeline.score_user(uid, prefs)
    return redirect("/dashboard?saved=1")


# ---------------------------------------------------------------------------- dashboard
@router.get("/dashboard")
def dashboard(request: Request, user: dict = Depends(require_user), tab: str = "primary", city: str = "",
              portal: str = "", role: str = "", mode: str = "", status: str = "", tier: str = "", min_fit: int = 0,
              salary: str = "", sort: str = "tier", saved: int = 0, preferred: int = 0, q: str = ""):
    uid = user["id"]
    prefs = view_prefs(uid)
    if not db.list_resumes(uid):
        return redirect("/resumes")
    if not prefs.get("confirmed"):
        return redirect("/profile")
    today = today_ist()
    tracker = db.tracker_all(uid)
    jobs = my_jobs(uid, prefs)
    buckets = select_buckets(jobs, prefs, today)
    tab = {"ncr": "primary", "metro": "secondary"}.get(tab, tab)
    tab = tab if tab in buckets else "primary"
    b = buckets[tab]
    rows = [decorate(j, today, tracker) for j in b["jobs"]]
    roles = [r["title"] for r in prefs.get("roles") or []]
    if city:
        rows = [j for j in rows if j.get("city") == city or city in (j.get("cities") or [])]
    if portal:
        rows = [j for j in rows if portal in portals_of(j)]
    if role:
        rows = [j for j in rows if fuzz.token_set_ratio(norm_title(j["title"]), norm_title(role)) >= 70]
    if mode:
        rows = [j for j in rows if j.get("work_mode") == mode]
    if status == "verified":
        rows = [j for j in rows if j.get("status") == "verified"]
    elif status == "manual":
        rows = [j for j in rows if j.get("manual_verified")]
    if tier:
        rows = [j for j in rows if str(j["tier"]) == tier]
    if min_fit:
        rows = [j for j in rows if (j.get("fit_score") or 0) >= min_fit]
    if preferred:
        rows = [j for j in rows if (j.get("fit_detail") or {}).get("preferred")]
    if q:
        ql = q.lower()[:80]
        rows = [j for j in rows if ql in (j.get("title") or "").lower() or ql in (j.get("company") or "").lower()
                or any(ql in s.lower() for s in (j.get("fit_detail") or {}).get("matched") or [])]
    if salary == "stated":
        rows = [j for j in rows if j.get("salary_min_lpa") is not None]
    elif salary == "unknown":
        rows = [j for j in rows if j.get("salary_min_lpa") is None]
    if sort == "fit":
        rows.sort(key=lambda j: -(j.get("fit_score") or 0))
    elif sort == "salary":
        rows.sort(key=lambda j: -(j.get("salary_max_lpa") or -1))
    elif sort == "company":
        rows.sort(key=lambda j: (j.get("company") or "").lower())
    elif sort == "newest":
        rows.sort(key=lambda j: j.get("posted_date") or "", reverse=True)
    cities = sorted({c for j in b["jobs"] for c in (j.get("cities") or [j.get("city")]) if c})
    f = dict(city=city, portal=portal, role=role, mode=mode, status=status, tier=tier, min_fit=min_fit, salary=salary,
             sort=sort, preferred=preferred, q=q)
    review_count = sum(1 for j in jobs if ineligible_reason(j, prefs, today) in ("date_unknown", "not_verified")
                       and j.get("status") not in ("expired", "dead"))
    all_chosen = b["jobs"]
    stats = {
        "new": sum(1 for j in all_chosen if j.get("new_since_refresh")),
        "fresh": b["tiers"].get(1, 0),
        "avg_fit": round(sum(j.get("fit_score") or 0 for j in all_chosen) / len(all_chosen)) if all_chosen else 0,
        "preferred": sum(1 for j in all_chosen if (j.get("fit_detail") or {}).get("preferred")),
        "applied": sum(1 for j in all_chosen if (tracker.get(j["id"]) or {}).get("status") not in (None, "", "New")),
        "gaps": _top_gaps(all_chosen),
    }
    return page(request, "dashboard.html", user=user, prefs=prefs, tab=tab, bucket=b, buckets=buckets, rows=rows,
                stats=stats, fam_names=[BY_KEY[k]["name"] for k in families_from(prefs.get("roles") or [], prefs.get("families"))],
                roles=roles, cities=cities, portals=PORTALS, f=f, qs=urlencode({k: v for k, v in f.items() if v}),
                tiers=TIERS, saved=saved, review_count=review_count, total_jobs=len(jobs),
                llm_on=prefs.get("use_llm_summary") and llm.available())


def _top_gaps(jobs: list[dict], n: int = 6) -> list[tuple[str, int]]:
    from collections import Counter
    c = Counter(g.replace(" (nice to have)", "") for j in jobs for g in (j.get("fit_detail") or {}).get("gaps") or [])
    return c.most_common(n)


@router.get("/review")
def review(request: Request, user: dict = Depends(require_user), show: str = "date"):
    uid = user["id"]
    prefs = view_prefs(uid)
    today = today_ist()
    tracker = db.tracker_all(uid)
    groups = {"date": [], "check": [], "expired": []}
    for j in my_jobs(uid, prefs):
        if not j.get("bucket"):
            continue
        if j.get("status") in ("expired", "dead"):
            groups["expired"].append(j)
            continue
        r = ineligible_reason(j, prefs, today)
        if r == "date_unknown":
            groups["date"].append(j)
        elif r == "not_verified":
            groups["check"].append(j)
    for g in groups.values():
        g.sort(key=lambda j: -(j.get("fit_score") or 0))
    show = show if show in groups else "date"
    rows = [decorate(j, today, tracker) for j in groups[show][:300]]
    return page(request, "review.html", user=user, prefs=prefs, groups={k: len(v) for k, v in groups.items()},
                show=show, rows=rows)


@router.get("/tracker")
def tracker_page(request: Request, user: dict = Depends(require_user)):
    uid = user["id"]
    today = today_ist()
    tracker = db.tracker_all(uid)
    rows = []
    for jid in tracker:
        j = db.job_for_user(uid, jid)
        if j and pipeline.visible_to(j, uid):
            rows.append(decorate(j, today, tracker))
    order = {s: i for i, s in enumerate(["Interview", "Offer", "Applied", "Shortlisted", "New", "Rejected"])}
    rows.sort(key=lambda j: (order.get(j["track"].get("status"), 9), j["track"].get("follow_up") or "9999"))
    counts = {s: sum(1 for t in tracker.values() if t["status"] == s) for s in db.TRACKER_STATUSES}
    return page(request, "tracker.html", user=user, rows=rows, counts=counts)


# ---------------------------------------------------------------------------- import
@router.get("/import")
def import_page(request: Request, user: dict = Depends(require_user), msg: str = "", job: str = ""):
    j = None
    if job:
        try:
            j = decorate(own_job(user["id"], job), today_ist(), db.tracker_all(user["id"]))
        except HTTPException:
            j = None
    return page(request, "import.html", user=user, msg=msg, job=j)


@router.post("/import")
def import_post(request: Request, user: dict = Depends(require_user), url: str = Form(""), text: str = Form(""),
                title: str = Form(""), company: str = Form(""), location: str = Form(""), posted: str = Form("")):
    from core.http import Http
    from sources.manual import import_text, import_url
    uid = user["id"]
    if not auth.upload_limiter.allow(f"import:{uid}"):
        return redirect("/import?" + urlencode({"msg": "Too many imports in the last hour. Try again later."}))
    url, text = url.strip()[:2000], text[:50000]
    if url and not re.match(r"^https?://", url):
        return redirect("/import?" + urlencode({"msg": "The link must start with http:// or https://"}))
    overrides = {"title": title[:200], "company": company[:200], "location": location[:200], "posted": posted[:10]}
    http = Http()
    try:
        job, msg = import_url(url, http, overrides) if url and not text.strip() else \
            import_text(text, url=url, overrides=overrides)
    finally:
        http.close()
    if not job:
        return redirect("/import?" + urlencode({"msg": msg}))
    job["id"] = make_id("manual", f"{uid}:{job.get('native_id') or job['title']}")
    job.setdefault("extra", {})["owner_id"] = uid
    job["demo"] = bool(db.get_settings().get("demo_mode"))
    if not job.get("bucket"):
        msg += ". No target city found, so it won't appear in the lists: add the city and import again."
    db.save_jobs([job])
    if posted:
        try:
            date.fromisoformat(posted)
            db.set_user_job(uid, job["id"], manual_posted=posted)
        except ValueError:
            pass
    pipeline.reverify_one(job["id"], uid)
    db.tracker_set(uid, job["id"], status="Shortlisted")
    return redirect("/import?" + urlencode({"msg": msg, "job": job["id"]}))


@router.post("/import/alerts")
async def import_alerts(files: list[UploadFile] = File(...), user: dict = Depends(require_user)):
    from sources.alerts import jobs_from_alert_files
    from sources.base import Ctx
    from core.http import Http
    uid = user["id"]
    if not auth.upload_limiter.allow(f"alerts:{uid}"):
        return redirect("/import?" + urlencode({"msg": "Too many uploads in the last hour. Try again later."}))
    payload = []
    for f in files[:20]:
        name = (f.filename or "").lower()
        if not name.endswith((".eml", ".mbox")):
            continue
        payload.append((name, await f.read(10 * 1024 * 1024)))
    prefs = view_prefs(uid)
    ctx = Ctx(prefs=prefs, http=Http(cache=False))
    try:
        found = jobs_from_alert_files(payload, ctx.relevant_title, ctx.target_location, owner_id=uid)
    finally:
        ctx.http.close()
    demo = bool(prefs.get("demo_mode"))
    for j in found:
        j["demo"] = demo
        j["id"] = make_id("alerts", j["native_id"])
    db.save_jobs(found)
    pipeline.score_user(uid, db.get_prefs(uid))
    msg = (f"Read {len(payload)} file(s) and found {len(found)} matching job(s). They're under Needs review → "
           f"Date unverified until you confirm each one's posting date.") if payload else \
        "No .eml or .mbox files were found in the upload."
    return redirect("/import?" + urlencode({"msg": msg}))


# ---------------------------------------------------------------------------- per-job actions
@router.post("/api/tracker/{job_id}")
async def api_tracker(job_id: str, request: Request, user: dict = Depends(require_user)):
    own_job(user["id"], job_id)
    data = await request.json()
    try:
        return db.tracker_set(user["id"], job_id, status=data.get("status"), notes=data.get("notes"),
                              follow_up=data.get("follow_up"))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


def _back(back: str) -> str:
    return back if back.startswith("/") and not back.startswith("//") else "/dashboard"


@router.post("/jobs/{job_id}/manual-verify")
def manual_verify(job_id: str, posted: str = Form(""), back: str = Form("/review"), user: dict = Depends(require_user)):
    own_job(user["id"], job_id)
    fields = {"manual_verified": True}
    if posted:
        try:
            date.fromisoformat(posted)
            fields["manual_posted"] = posted
        except ValueError:
            pass
    db.set_user_job(user["id"], job_id, **fields)
    return redirect(_back(back))


@router.post("/jobs/{job_id}/unverify")
def manual_unverify(job_id: str, back: str = Form("/dashboard"), user: dict = Depends(require_user)):
    own_job(user["id"], job_id)
    db.set_user_job(user["id"], job_id, manual_verified=False)
    return redirect(_back(back))


@router.post("/jobs/{job_id}/recheck")
def recheck(request: Request, job_id: str, back: str = Form("/review"), user: dict = Depends(require_user)):
    own_job(user["id"], job_id)
    if not auth.upload_limiter.allow(f"recheck:{user['id']}"):
        raise HTTPException(429, "Too many checks in the last hour. Try again later.")
    pipeline.reverify_one(job_id, user["id"])
    return redirect(_back(back))


@router.post("/api/jobs/{job_id}/summary")
def api_summary(job_id: str, user: dict = Depends(require_user)):
    prefs = db.get_prefs(user["id"])
    job = own_job(user["id"], job_id)
    if not (prefs.get("use_llm_summary") and llm.available()):
        raise HTTPException(400, "Written summaries are off.")
    if not auth.upload_limiter.allow(f"llm:{user['id']}"):
        raise HTTPException(429, "Too many summaries in the last hour.")
    prof = prefs.get("profile") or {}
    try:
        text = llm.fit_summary(job, prof.get("skills") or [], float(prof.get("years_experience") or 0))
    except Exception:
        raise HTTPException(502, "Couldn't write a summary right now.")
    db.set_user_job(user["id"], job_id, summary=text)
    return {"summary": text}


# ---------------------------------------------------------------------------- refresh status, health, account
@router.get("/api/refresh/status")
def api_refresh_status(user: dict = Depends(require_user)):
    lr = db.last_run()
    return {"state": pipeline.STATE, "last_run": {"finished": lr["finished"]} if lr else None}


@router.get("/health")
def health(request: Request, user: dict = Depends(require_user)):
    from sources import ALL_SOURCES, PORTAL_COVERAGE
    settings = db.get_settings()
    jobs = [j for j in db.all_jobs(demo=bool(settings.get("demo_mode")))
            if j.get("bucket") and not (j.get("extra") or {}).get("owner_id")]
    adapters = {h["source"]: h for h in db.health_all()}
    portal_rows = []
    for p, cov in PORTAL_COVERAGE.items():
        mine = [j for j in jobs if p in portals_of(j)]
        ok = [j for j in mine if j.get("status") == "verified"]
        errs = [f"{adapters[a]['label']}: {adapters[a]['error']}" for a in cov["adapters"]
                if a in adapters and adapters[a].get("error")] if user["role"] == "admin" else []
        notes = [f"{adapters[a]['label']}: {adapters[a]['note']}" for a in cov["adapters"]
                 if a in adapters and adapters[a].get("note")]
        portal_rows.append({"portal": p, "found": len(mine), "ok": len(ok), "how": cov["how"], "limit": cov["limit"],
                            "errors": errs, "notes": notes})
    src_rows = []
    for s in ALL_SOURCES:
        h = adapters.get(s.name, {})
        src_rows.append({"label": s.label, "name": s.name, "configured": s.configured(), "needs": s.requires_keys,
                         "kind": s.kind, "coverage": s.coverage_note,
                         **{k: h.get(k) for k in ("last_run", "found", "kept", "note")},
                         "error": h.get("error") if user["role"] == "admin" else ""})
    from core.config import key_status
    return page(request, "health.html", user=user, portal_rows=portal_rows, src_rows=src_rows,
                keys=key_status() if user["role"] == "admin" else None, last=db.last_run())


@router.get("/account")
def account_page(request: Request, user: dict = Depends(require_user), msg: str = "", err: str = ""):
    return page(request, "account.html", user=user, msg=msg, err=err)


@router.post("/account/password")
def change_password(request: Request, user: dict = Depends(require_user), current: str = Form(""),
                    new: str = Form(""), confirm: str = Form("")):
    if not auth.login_limiter.allow(f"pw:{user['id']}"):
        return redirect("/account?err=Too+many+attempts.+Try+again+later.")
    if not auth.verify_password(current, user["password_hash"]):
        return redirect("/account?err=Your+current+password+is+wrong.")
    problem = auth.password_problem(new, user["email"]) or (None if new == confirm else "The new passwords don't match.")
    if problem:
        return redirect("/account?" + urlencode({"err": problem}))
    db.update_user(user["id"], password_hash=auth.hash_password(new))
    db.bump_session(user["id"])
    from .web import login
    login(request, db.get_user(user["id"]))
    return redirect("/account?msg=Password+changed.+Other+devices+were+signed+out.")


@router.post("/account/delete")
def delete_account(request: Request, user: dict = Depends(require_user), password: str = Form(""),
                   confirm_text: str = Form("")):
    if user["role"] == "admin" and sum(1 for u in db.list_users() if u["role"] == "admin") == 1:
        return redirect("/account?err=You+are+the+only+admin.+The+site+needs+one,+so+this+account+can't+be+deleted.")
    if confirm_text.strip().upper() != "DELETE" or not auth.verify_password(password, user["password_hash"]):
        return redirect("/account?err=Type+DELETE+and+enter+your+password+to+delete+your+account.")
    db.delete_user(user["id"])
    request.session.clear()
    return page(request, "message.html", title="Account deleted",
                message="Your account, resumes, preferences and tracker were deleted.", link=("/", "Home"))


# ---------------------------------------------------------------------------- exports
@router.get("/export/top100.xlsx")
def export_top100(user: dict = Depends(require_user)):
    prefs = view_prefs(user["id"])
    data = top100_xlsx(select_buckets(my_jobs(user["id"], prefs), prefs), db.tracker_all(user["id"]))
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="GetaJob_top100_{today_ist()}.xlsx"'})


def _tracker_jobs(uid: int) -> dict:
    return {jid: db.job_for_user(uid, jid) or {} for jid in db.tracker_all(uid)}


@router.get("/export/tracker.csv")
def export_tracker_csv(user: dict = Depends(require_user)):
    return Response(tracker_csv(_tracker_jobs(user["id"]), db.tracker_all(user["id"])), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="GetaJob_tracker.csv"'})


@router.get("/export/tracker.xlsx")
def export_tracker_xlsx(user: dict = Depends(require_user)):
    return Response(tracker_xlsx(_tracker_jobs(user["id"]), db.tracker_all(user["id"])),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="GetaJob_tracker.xlsx"'})
