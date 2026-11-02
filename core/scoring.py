"""Explainable 0-100 resume-fit score.

Skills 40 · Title & seniority 20 · Experience 15 · Salary 10 · Industry 10 · Location & mode 5
"""
from __future__ import annotations

import re

from rapidfuzz import fuzz

from .dedup import norm_title
from .relevance import CORE
from .skills import SOFT_GAP_EXCLUDE, _COMPILED, detect_industries

WEIGHTS = {"skills": 40, "title": 20, "experience": 15, "salary": 10, "industry": 10, "location": 5}
_MUST_HDR = re.compile(r"(requirements?|qualifications?|what you(?:'|’)?ll need|what we(?:'|’)?re looking for|"
                       r"must[- ]haves?|skills required|required skills|who you are|you (?:have|bring|will need)|"
                       r"eligibility|key skills|minimum qualifications|basic qualifications)", re.I)
_NICE_HDR = re.compile(r"(nice[- ]to[- ]have|good[- ]to[- ]have|preferred|bonus|plus points?|desirable|"
                       r"preferred qualifications|additional skills)", re.I)
_ANALYTIC_TITLE = re.compile(r"analy|insight|intelligence|\bbi\b|strategy|data|reporting|\bmis\b|decision|pricing|"
                             r"growth|operations|consult", re.I)

LEVELS = [  # (pattern, label, fit for ~3 years of experience)
    (r"\b(intern|trainee|apprentice|fresher)\b", "Entry", 0.2),
    (r"\b(chief|vice president|vp|director|head)\b", "Director+", 0.05),
    (r"\b(principal|staff)\b", "Principal", 0.3),
    (r"\b(assistant|asst\.?|deputy) manager\b", "Assistant Manager", 0.95),
    (r"\bsenior manager\b", "Senior Manager", 0.3),
    (r"\b(manager|mgr)\b", "Manager", 0.55),
    (r"\b(lead|team lead)\b", "Lead", 0.8),
    (r"\b(senior|sr)\b", "Senior", 1.0),
    (r"\b(associate|junior|jr)\b", "Associate", 0.85),
]


def seniority(title: str) -> tuple[str, float]:
    t = (title or "").lower()
    for pat, label, fit in LEVELS:
        if re.search(pat, t):
            return label, fit
    return "Mid", 1.0


def split_requirements(desc: str) -> tuple[str, str, str]:
    """(must-have text, nice-to-have text, other text) from a JD using its section headings."""
    must, nice, other = [], [], []
    bucket = other
    for line in (desc or "").splitlines():
        short = len(line) < 90
        if short and _NICE_HDR.search(line):
            bucket = nice
        elif short and _MUST_HDR.search(line):
            bucket = must
        elif short and re.match(r"^\s*(about|benefits|perks|why join|our culture|who we are|what we offer|"
                                r"responsibilities|what you(?:'|’)?ll do|role|the role)\b", line, re.I):
            bucket = other
        bucket.append(line)
    return "\n".join(must), "\n".join(nice), "\n".join(other)


def _skills_in(text: str) -> set[str]:
    return {name for name, pats in _COMPILED.items() if any(p.search(text) for p in pats)}


def score_job(job: dict, prefs: dict) -> tuple[int, dict]:
    prof = prefs.get("profile") or {}
    have = set(prof.get("skills") or [])
    yrs = float(prof.get("years_experience") or 0)
    desc = job.get("description") or ""
    title = job.get("title") or ""
    notes = []

    # ---- skills (40)
    must_t, nice_t, other_t = split_requirements(desc)
    if must_t or nice_t:
        must = _skills_in(must_t + "\n" + title)
        nice = _skills_in(nice_t) - must
        other = _skills_in(other_t) - must - nice
        must |= other  # skills named in duties are expected too
    else:
        must, nice = _skills_in(desc + "\n" + title), set()
    wanted = len(must) * 2 + len(nice)
    if wanted == 0 or len(desc) < 250:
        skill_pts = WEIGHTS["skills"] * 0.5
        notes.append("Description too short to judge skills; scored as neutral")
    else:
        got = len(must & have) * 2 + len(nice & have)
        skill_pts = WEIGHTS["skills"] * got / wanted
    matched = sorted((must | nice) & have)
    gaps = sorted((must - have) - SOFT_GAP_EXCLUDE) + sorted(n + " (nice to have)" for n in (nice - have) - SOFT_GAP_EXCLUDE)

    # ---- title & seniority (20)
    roles = [r["title"] if isinstance(r, dict) else r for r in prefs.get("roles") or []]
    nt = norm_title(title)
    sim = max([fuzz.token_set_ratio(nt, norm_title(r)) for r in roles] or [0]) / 100
    if CORE.search(title):
        sim = max(sim, 0.6)  # an analytics title, even if worded differently from your roles
    level, lvl_fit = seniority(title)
    title_pts = WEIGHTS["title"] * (0.7 * sim + 0.3 * lvl_fit)
    if lvl_fit < 0.6:
        notes.append(f"{level}-level title: a stretch at {yrs:g} years")

    # ---- experience (15)
    lo, hi = job.get("exp_min"), job.get("exp_max")
    if lo is None:
        exp_pts = WEIGHTS["experience"] * 0.5
        exp_note = "not stated"
    else:
        top = hi if hi is not None else lo + 4
        if lo <= yrs <= top:
            exp_pts = WEIGHTS["experience"]
        elif yrs < lo:
            exp_pts = WEIGHTS["experience"] * max(0.0, 1 - (lo - yrs) / 3)
        else:
            exp_pts = WEIGHTS["experience"] * max(0.3, 1 - (yrs - top) / 5)
        exp_note = job.get("experience_required") or f"{lo:g}+ years"

    # ---- salary (10)
    smin, smax = job.get("salary_min_lpa"), job.get("salary_max_lpa")
    pmin, pmax = float(prefs.get("salary_min_lpa") or 0), float(prefs.get("salary_max_lpa") or 999)
    if smin is None and smax is None:
        sal_pts, sal_note = WEIGHTS["salary"] * 0.5, "not stated"
    else:
        smin, smax = smin or smax, smax or smin
        if smax >= pmin and smin <= pmax:
            sal_pts, sal_note = WEIGHTS["salary"], "within your range"
        elif smax < pmin:
            sal_pts, sal_note = 0, "below your range"
        else:
            sal_pts, sal_note = WEIGHTS["salary"] * 0.8, "above your range"

    # ---- industry (10)
    inds = detect_industries(" ".join([job.get("company") or "", job.get("employer_industry") or "", desc[:4000]]), 2)
    if job.get("employer_industry"):
        inds = [job["employer_industry"]] + [i for i in inds if i != job["employer_industry"]]
    prefer = set(prefs.get("prefer_industries") or [])
    avoid = set(prefs.get("avoid_industries") or [])
    if inds and inds[0] in avoid:
        ind_pts = 0
    elif prefer & set(inds[:2]):
        ind_pts = WEIGHTS["industry"]
    elif set(prof.get("industries") or []) & set(inds[:2]):
        ind_pts = WEIGHTS["industry"] * 0.8
    else:
        ind_pts = WEIGHTS["industry"] * 0.5

    # ---- location & work mode (5)
    city = job.get("city")
    if city == "Gurugram":
        loc_pts = 5
    elif city in ("Delhi", "Noida", "Delhi NCR"):
        loc_pts = 4.5
    elif city:
        loc_pts = 3
    else:
        loc_pts = 2
    if job.get("work_mode") in ("remote", "hybrid"):
        loc_pts = min(5, loc_pts + 0.5)

    parts = {"skills": skill_pts, "title": title_pts, "experience": exp_pts, "salary": sal_pts,
             "industry": ind_pts, "location": loc_pts}
    score = int(round(sum(parts.values())))
    detail = {
        "parts": {k: round(v, 1) for k, v in parts.items()},
        "matched": matched,
        "gaps": gaps[:10],
        "level": level,
        "experience_note": exp_note,
        "salary_note": sal_note,
        "industries": inds[:2],
        "notes": notes,
    }
    return max(0, min(100, score)), detail


VARIANT_TITLE_RULES = [
    ("Product Analyst", re.compile(r"product|growth|experiment|user|app\b|lifecycle|crm|retention", re.I)),
    ("Business Intelligence", re.compile(r"\bbi\b|business intelligence|reporting|\bmis\b|dashboard|power ?bi|tableau|"
                                         r"visuali|data management|\bmi\b", re.I)),
    ("Strategy & Consulting", re.compile(r"strateg|consult|advisory|pricing|business operations|bizops|revenue|"
                                         r"planning|research|intelligence & advisory", re.I)),
]


def pick_resume(job: dict, prefs: dict) -> str:
    """Which of the user's resume versions to send: a version whose focus matches the job title, else the one
    whose skills overlap the job description most (a general version wins close calls)."""
    variants = (prefs.get("profile") or {}).get("variants") or []
    if not variants:
        return ""
    if len(variants) == 1:
        return variants[0]["label"]
    title = job.get("title") or ""
    for focus, rx in VARIANT_TITLE_RULES:
        if rx.search(title):
            hit = next((v for v in variants if v.get("focus") == focus), None)
            if hit:
                return hit["label"]
    jd = set(job.get("skills_extracted") or [])
    general = next((v for v in variants if v.get("focus") in ("General", "Analyst")), variants[0])
    best, best_n = general["label"], len(jd & set(general.get("skills") or [])) + 1
    for v in variants:
        n = len(jd & set(v.get("skills") or []))
        if v is not general and n > best_n:
            best, best_n = v["label"], n
    return best
