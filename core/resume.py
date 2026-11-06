"""Resume intake: local PDF text extraction, profile building and role suggestions.

Nothing here touches the network. Phone numbers, emails and profile links are
stripped before the profile is saved, and only skill keywords ever leave the machine.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from rapidfuzz import fuzz

from .skills import detect_industries, extract_skills, skill_counts

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
SECTION_RE = re.compile(
    r"^(professional summary|summary|profile|objective|career objective|key achievements|core skills|key skills|"
    r"technical skills|skills|skills & tools|skills and tools|tools|core competencies|competencies|areas of expertise|"
    r"expertise|technologies|professional experience|work experience|experience|employment history|work history|"
    r"career history|internships?|projects|education|academic qualifications?|qualifications|certifications?|"
    r"achievements|languages|interests|hobbies)\s*:?\s*$", re.I)
SKILL_SECTIONS = ("core skills", "key skills", "technical skills", "skills", "skills & tools", "skills and tools", "tools",
                  "core competencies", "competencies", "areas of expertise", "expertise", "technologies")
EXP_SECTIONS = ("professional experience", "work experience", "experience", "employment history", "work history",
                "career history")
RANGE_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{4})\s*[–—-]+\s*"
    r"(present|current|now|(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{4}))", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE_RE = re.compile(r"(?:\+?\d[\d\s-]{8,}\d)")
LINK_RE = re.compile(r"\b(?:https?://)?(?:www\.)?(?:linkedin|github)\.com/\S+", re.I)

def extract_pdf_text(path: Path) -> str:
    import pdfplumber
    with pdfplumber.open(str(path)) as pdf:
        return "\n".join((page.extract_text() or "") for page in pdf.pages)


def variant_focus(filename: str, headline: str, skills: list[str]) -> dict:
    """What a resume version is aimed at, from its file name and headline: a catalog role, else a job family."""
    from .taxonomy import FAMILIES, families_of_title, strip_level
    stem = re.sub(r"[_\-.]+", " ", Path(filename).stem).lower()

    def catalog_hit(text: str):
        best, best_s = None, 0
        for f in FAMILIES:
            for title, *_ in f["roles"]:
                for part in strip_level(title).lower().split("/"):
                    part = part.strip()
                    if len(part) > 3 and re.search(r"\b" + re.escape(part) + r"\b", text) and len(part) > best_s:
                        best, best_s = (title, f["key"]), len(part)
        return best

    def family_hit(text: str):
        for f in FAMILIES:
            words = [w for w in re.findall(r"[a-z]+", f["name"].lower()) if len(w) > 3]
            if words and sum(w[:6] in text for w in words) >= max(1, len(words) - 1):
                return f
        return None

    hit = catalog_hit(stem)
    if hit:
        return {"focus": hit[0], "focus_family": hit[1]}
    fam = family_hit(stem)
    if fam:
        return {"focus": fam["name"], "focus_family": fam["key"]}
    if re.search(r"\b(resume|cv|general|master|main)\b", stem) or re.search(r"\banalyst$", stem):
        return {"focus": "General", "focus_family": ""}
    fams = families_of_title(stem)
    if fams:
        from .taxonomy import BY_KEY
        return {"focus": BY_KEY[fams[0]]["name"], "focus_family": fams[0]}
    return {"focus": "General", "focus_family": ""}


def display_name(filename: str) -> str:
    return re.sub(r"[_]+", " ", Path(filename).stem).strip()[:80] or "Resume"


def _sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"header": []}
    current = "header"
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = SECTION_RE.match(line)
        if m:
            current = m.group(1).lower()
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return sections


def _months_worked(lines: list[str], today: date) -> tuple[int, list[tuple[str, str]]]:
    """Union of month ranges in the experience section, plus (title, company) pairs."""
    months: set[int] = set()
    roles = []
    for line in lines:
        m = RANGE_RE.search(line)
        if not m:
            continue
        sm, sy = MONTHS[m.group(1)[:3].lower()], int(m.group(2))
        if m.group(3).lower() in ("present", "current", "now"):
            em, ey = today.month, today.year
        else:
            em, ey = MONTHS[m.group(4)[:3].lower()], int(m.group(5))
        start, end = sy * 12 + sm, ey * 12 + em
        if 0 <= end - start < 600:
            months.update(range(start, end + 1))
        head = line[: m.start()].strip(" ·|-–")
        parts = [p.strip() for p in re.split(r"\s[·|•▪–—-]\s|\s+at\s+|,\s", head) if p.strip()]
        if parts:
            roles.append((parts[0], parts[1] if len(parts) > 1 else ""))
    return len(months), roles


PROFILE_VERSION = 2  # bump when build_profile changes, so saved profiles are rebuilt from the stored resumes


def _free_skills(lines: list[str]) -> list[str]:
    """Skill phrases listed in a resume's skills section that the built-in vocabulary doesn't know."""
    from .skills import extract_skills
    out: list[str] = []
    for line in lines:
        line = re.sub(r"^[▪•\-*●◦]\s*", "", line)
        line = re.sub(r"^[A-Za-z &/]{2,30}:\s*", "", line)  # "Tools: ..." -> "..."
        for tok in re.split(r"[,;|•·▪●]|\s{2,}|\band\b", line):
            tok = tok.strip(" .:-–()").strip()
            if not (2 <= len(tok) <= 32) or len(tok.split()) > 4 or not re.search(r"[A-Za-z]", tok):
                continue
            if re.search(r"\d{4}|@|http|www\.|\+\d", tok) or extract_skills(tok):
                continue
            if tok.lower() in {"etc", "others", "skills", "tools", "languages", "english", "hindi", "communication",
                               "teamwork", "leadership", "hard working", "team player", "time management"}:
                continue
            name = tok if any(c.isupper() for c in tok) else tok.title()
            if name.lower() not in {o.lower() for o in out}:
                out.append(name)
    return out[:30]


def _clean_bullet(line: str) -> str:
    return re.sub(r"^[▪•\-*●◦]\s*", "", line).strip()


def build_profile(resumes: dict[str, str], today: date | None = None) -> dict:
    """resumes: {filename: text}. Returns a merged, contact-free profile."""
    today = today or date.today()
    all_text = "\n".join(resumes.values())
    first = next(iter(resumes.values()), "")
    first_lines = [l.strip() for l in first.splitlines() if l.strip()]

    contact_found = bool(EMAIL_RE.search(all_text) or PHONE_RE.search(all_text))
    name = first_lines[0].title() if first_lines else ""
    headline = first_lines[1] if len(first_lines) > 1 else ""

    from .locations import find_cities
    location = ""
    for line in first_lines[:5]:
        found = find_cities(line)
        if found:
            location = found[0]
            break

    best_months, roles, exp_lines, edu, achievements = 0, [], [], [], []
    variants, skill_lines, held = [], [], []
    for fname, text in resumes.items():
        sec = _sections(text)
        exp = next((sec[k] for k in EXP_SECTIONS if sec.get(k)), [])
        months, r = _months_worked(exp, today)
        if months > best_months:
            best_months, roles = months, r
        for t, _ in r:
            t = re.sub(r"\s+", " ", t).strip(" ,|-–")
            if 2 < len(t) <= 70 and t.lower() not in {h.lower() for h in held}:
                held.append(t)
        for k in SKILL_SECTIONS:
            skill_lines.extend(sec.get(k, []))
        exp_lines.extend(exp)
        edu.extend(_clean_bullet(l) for l in sec.get("education", []))
        for l in exp:
            if l.startswith(("▪", "•", "-", "*", "●")) and re.search(r"\d", l):
                achievements.append(_clean_bullet(l))
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        head = LINK_RE.sub("", EMAIL_RE.sub("", PHONE_RE.sub("", lines[1] if len(lines) > 1 else ""))).strip(" |")
        vskills = extract_skills(text)
        variants.append({"label": display_name(fname), "file": fname, "headline": head, "skills": vskills,
                         **variant_focus(fname, head, vskills)})

    years = round(best_months / 12, 1)
    if not years:
        m = re.search(r"(\d+(?:\.\d+)?)\+?\s*years", all_text, re.I)
        years = float(m.group(1)) if m else 0.0

    # dedupe achievements across resume versions
    unique: list[str] = []
    for a in achievements:
        a = EMAIL_RE.sub("", PHONE_RE.sub("", a))
        if all(fuzz.token_set_ratio(a, u) < 80 for u in unique):
            unique.append(a)

    custom = _free_skills(skill_lines)
    counts = skill_counts(all_text, custom)
    skills = sorted(counts, key=lambda s: -counts[s])
    edu_unique = []
    for e in edu:
        if e and e not in edu_unique:
            edu_unique.append(e)

    prof = {
        "name": name,
        "headline": LINK_RE.sub("", EMAIL_RE.sub("", headline)).strip(" |"),
        "location": location,
        "current_title": roles[0][0] if roles else "",
        "current_company": roles[0][1] if roles else "",
        "companies": [c for _, c in roles],
        "years_experience": years,
        "skills": skills,
        "skill_counts": counts,
        "industries": detect_industries("\n".join(exp_lines) or all_text, min_hits=2)[:4],
        "custom_skills": [c for c in custom if c in counts],
        "titles_held": held[:10],
        "achievements": unique[:14],
        "education": edu_unique[:4],
        "variants": variants,
        "contact_removed": contact_found,
        "source_files": list(resumes.keys()),
    }
    prof["families"] = detect_families(prof)
    prof["v"] = PROFILE_VERSION
    return prof


def load_resumes(folder: Path) -> dict[str, str]:
    out = {}
    for p in sorted(folder.glob("*.pdf")):
        try:
            out[p.name] = extract_pdf_text(p)
        except Exception as exc:  # unreadable PDF: show it, don't crash setup
            out[p.name] = ""
            print(f"[resume] could not read {p.name}: {exc}")
    return {k: v for k, v in out.items() if v.strip()}


# ---------------------------------------------------------------- job families and role suggestions
def detect_families(profile: dict) -> list[dict]:
    """Every job family scored against the resume: skills evidence plus the titles the person has held."""
    from .taxonomy import FAMILIES, title_in_family
    counts = profile.get("skill_counts") or {s: 1 for s in profile.get("skills", [])}
    current = [profile.get("current_title", "")]
    heads = [profile.get("headline", "")] + [v.get("headline", "") for v in profile.get("variants", [])]
    past = profile.get("titles_held", [])[1:]
    out = []
    for f in FAMILIES:
        fs = f["skills"]
        got = sorted(((min(counts.get(s, 0), 4), s) for s in fs if counts.get(s)), reverse=True)
        skill_score = min(1.0, sum(n for n, _ in got) / (4 * min(len(fs), 7)))
        cur_hit = any(t and title_in_family(t, f) for t in current)
        head_hit = any(t and title_in_family(re.split(r"\s[|·]\s", t)[0], f) for t in heads)
        past_hit = any(t and title_in_family(t, f) for t in past)
        title_score = 1.0 if cur_hit else (0.75 if head_hit else (0.6 if past_hit else 0.0))
        score = round(100 * (0.55 * skill_score + 0.45 * title_score))
        why = []
        if cur_hit:
            why.append("your current title")
        elif head_hit:
            why.append("your resume headline")
        elif past_hit:
            why.append("a title you've held")
        if got:
            why.append(", ".join(s for _, s in got[:3]))
        out.append({"key": f["key"], "name": f["name"], "score": score, "why": "; ".join(why)})
    out.sort(key=lambda x: -x["score"])
    return out


def default_families(profile: dict) -> list[str]:
    fams = profile.get("families") or detect_families(profile)
    keep = [f["key"] for f in fams if f["score"] >= 40][:3]
    return keep or [fams[0]["key"]]


def _evidence(skills: list[str], achievements: list[str]) -> str:
    from .skills import _COMPILED
    for sk in skills:
        for a in achievements:
            if any(p.search(a) for p in _COMPILED.get(sk, [])):
                short = re.split(r";| via | across | for (?=[a-z])", a)[0].strip().rstrip(",")
                return short if len(short) <= 95 else short[:92].rsplit(" ", 1)[0] + "…"
    return ""


CREDENTIALS = {"MBBS / MD", "Pharmacy", "Nursing"}  # a role led by one of these needs it on the resume


def _score_role(title, signals, ymin, ymax, counts, yrs, heads, ach, past="", current=""):
    from .relevance import matches_role
    matched = [s for s in signals if counts.get(s)]
    vals = sorted((min(counts.get(s, 0), 3) / 3 for s in signals), reverse=True)[:4]  # roles list alternatives
    strength = sum(vals) / max(1, min(4, len(signals)))
    words = [w for w in re.findall(r"[a-z]+", title.lower())
             if w not in ("senior", "analyst", "associate", "and", "manager", "executive", "specialist", "engineer", "lead")]
    base = title.lower().split("/")[0].strip()
    if base and re.search(r"\b" + re.escape(base) + r"\b", heads):
        affinity = 1.0
    elif base and fuzz.partial_ratio(base, heads) >= 92:
        affinity = 0.8
    elif base and re.search(r"\b" + re.escape(base) + r"\b", past):
        affinity = 0.6
    elif words and any(w in heads for w in words):
        affinity = 0.6
    else:
        affinity = 0.3
    if ymin <= yrs <= ymax:
        senior = 1.0
    elif yrs < ymin:
        senior = max(0.0, 1 - (ymin - yrs) / 3)
    else:
        senior = max(0.2, 1 - (yrs - ymax) / 5)
    score = round(70 * strength + 20 * affinity + 10 * senior) - (10 if yrs < ymin - 0.5 else 0) \
        - (15 if yrs > ymax + 2 else 0)
    if signals and signals[0] in CREDENTIALS and not counts.get(signals[0]):
        score -= 35
    if current and matches_role(current, [title], 90):
        score += 12
    reason = (", ".join(matched[:3]) + " on your resume") if matched else "Adjacent to your experience"
    generic = {"SQL", "Excel", "Python", "Stakeholder Management", "MS Office", "Customer Service"}
    ev = _evidence([m for m in matched if m not in generic] + [m for m in matched if m in generic], ach)
    if ev:
        reason += f". Evidence: {ev}"
    if yrs < ymin - 0.5:
        reason += f" (stretch: usually {ymin}+ years)"
    return score, reason


def suggest_roles(profile: dict, families: list[str] | None = None, n_min: int = 8, n_max: int = 16) -> list[dict]:
    """Roles for this person: catalog roles in their job families, ranked by resume evidence and level,
    with senior/manager versions when their experience calls for it, plus titles they have actually held."""
    from .taxonomy import BY_KEY, LEVEL_WORDS, family_for_role
    from .relevance import matches_role
    counts = profile.get("skill_counts") or {s: 1 for s in profile.get("skills", [])}
    yrs = float(profile.get("years_experience") or 0)
    ach = profile.get("achievements", [])
    heads = " ".join([profile.get("current_title", ""), profile.get("headline", "")]
                     + [v.get("headline", "") for v in profile.get("variants", [])]).lower()
    past = " ".join(profile.get("titles_held", [])[1:]).lower()
    cur = profile.get("current_title", "")
    fams = [k for k in (families or default_families(profile)) if k in BY_KEY]
    if not families:  # thin resumes: widen to the next-closest family so there is enough to choose from
        ranked = [f["key"] for f in (profile.get("families") or detect_families(profile))]
        while sum(len(BY_KEY[k]["roles"]) for k in fams) < n_min and len(fams) < len(ranked):
            fams.append(next(k for k in ranked if k not in fams))
    scored = []
    for k in fams:
        f = BY_KEY[k]
        cands = list(f["roles"])
        if yrs >= 7 and f.get("manager"):
            cands.append((f["manager"], f["skills"][:6], 7, 16))
        for title, signals, ymin, ymax in cands:
            score, reason = _score_role(title, signals, ymin, ymax, counts, yrs, heads, ach, past, cur)
            if yrs >= max(4, ymin + 3) and not LEVEL_WORDS.search(title) and 5 <= ymax < 12:
                s2, r2 = _score_role(f"Senior {title}", signals, ymin + 3, ymax + 5, counts, yrs, heads, ach, past, cur)
                scored.append({"title": f"Senior {title}", "score": s2, "reason": r2, "family": k,
                               "family_name": f["name"], "queries": [f"senior {title.split('/')[0].strip().lower()}"]})
            scored.append({"title": title, "score": score, "reason": reason, "family": k, "family_name": f["name"],
                           "queries": [title.split("/")[0].strip().lower()] +
                                      [p.strip().lower() for p in title.split("/")[1:2]]})
    # titles the person has held, when the catalog doesn't already cover them
    for i, t in enumerate(([profile.get("current_title")] if profile.get("current_title") else [])
                          + profile.get("titles_held", [])):
        if not t or any(matches_role(t, [s["title"]], 88) for s in scored):
            continue
        k = family_for_role(t) or (fams[0] if fams else "")
        if fams and k not in fams:
            continue
        scored.append({"title": t, "score": 84 if i == 0 else 74, "family": k,
                       "family_name": BY_KEY[k]["name"] if k in BY_KEY else "",
                       "reason": "Your current title" if i == 0 else "A title you've held", "queries": [t.lower()]})
    scored.sort(key=lambda r: -r["score"])
    out, per_fam, seen = [], {}, set()
    for r in scored:
        key = r["title"].lower()
        if key in seen or per_fam.get(r["family"], 0) >= 8:
            continue
        seen.add(key)
        per_fam[r["family"]] = per_fam.get(r["family"], 0) + 1
        out.append(r)
    keep = [r for r in out if r["score"] >= 50][:n_max]
    if len(keep) < n_min:
        keep = out[:max(n_min, len(keep))]
    for k in fams:  # every family the person picked shows its best few roles, even with little evidence
        have = sum(1 for r in keep if r["family"] == k)
        keep += [r for r in out if r["family"] == k and r not in keep][:max(0, 3 - have)]
    keep.sort(key=lambda r: -r["score"])
    return keep


# ---------------------------------------------------------------- uploads: validation and identity
def is_pdf(content: bytes) -> bool:
    return content[:5] == b"%PDF-"


def extract_pdf_bytes(content: bytes, max_pages: int = 6) -> str:
    import io

    import pdfplumber
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        return "\n".join((page.extract_text() or "") for page in pdf.pages[:max_pages])


def identity(text: str) -> dict:
    """Who a resume belongs to: the name line at the top and any email addresses."""
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    name = ""
    for l in lines[:3]:
        if not EMAIL_RE.search(l) and not PHONE_RE.search(l) and 2 <= len(l.split()) <= 5 and not re.search(r"\d", l):
            name = l.title()
            break
    emails = sorted({e.lower().rstrip(".") for e in EMAIL_RE.findall(text or "")})
    return {"name": name, "emails": emails}


def same_person(new: dict, existing: list[dict]) -> tuple[bool, str]:
    """A new resume must share an email address or (failing that) the name with the ones already uploaded."""
    if not existing:
        return True, ""
    old_emails = {e for x in existing for e in x.get("emails", [])}
    old_names = {x.get("name", "") for x in existing if x.get("name")}
    if new.get("emails") and old_emails & set(new["emails"]):
        return True, ""
    if new.get("name") and any(fuzz.token_sort_ratio(new["name"], n) >= 88 for n in old_names):
        return True, ""
    shown_new = new.get("name") or ", ".join(new.get("emails", [])) or "no name or email found"
    shown_old = ", ".join(sorted(old_names)) or ", ".join(sorted(old_emails)) or "your other resumes"
    return False, (f"This resume looks like it belongs to someone else ({shown_new}). All resumes on one account "
                   f"must be versions of the same person's resume ({shown_old}).")
