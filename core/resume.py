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
    r"^(professional summary|summary|key achievements|core skills|skills|professional experience|work experience|"
    r"experience|internships?|projects|education|certifications?|achievements)\s*$", re.I)
RANGE_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{4})\s*[–—-]+\s*"
    r"(present|current|now|(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{4}))", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE_RE = re.compile(r"(?:\+?\d[\d\s-]{8,}\d)")
LINK_RE = re.compile(r"\b(?:https?://)?(?:www\.)?(?:linkedin|github)\.com/\S+", re.I)
CITY_WORDS = ["gurgaon", "gurugram", "noida", "new delhi", "delhi", "bengaluru", "bangalore", "hyderabad",
              "mumbai", "pune", "chennai", "kolkata"]

# Variant label from file name -> focus keywords used to pick which resume to send per job.
VARIANT_RULES = [
    ("Product Analyst", ["product"], r"product|growth|experiment|funnel|user|app|retention|lifecycle"),
    ("Business Intelligence", ["business_intelligence", "bi_", "_bi"], r"\bbi\b|business intelligence|reporting|mis|dashboard|power ?bi|tableau|visuali"),
    ("Strategy & Consulting", ["strategy", "consult"], r"strateg|consult|advisory|pricing|business operations|bizops|revenue|planning|corporate development"),
    ("Analyst", ["analyst"], r""),
]


def extract_pdf_text(path: Path) -> str:
    import pdfplumber
    with pdfplumber.open(str(path)) as pdf:
        return "\n".join((page.extract_text() or "") for page in pdf.pages)


def variant_label(filename: str) -> str:
    """Focus of a resume version from its file name ("..._Product_Analyst.pdf" -> "Product Analyst"), else ""."""
    low = filename.lower()
    for label, keys, _ in VARIANT_RULES:
        if label != "Analyst" and any(k in low for k in keys):
            return label
    return ""


def variant_focus(filename: str, headline: str) -> str:
    focus = variant_label(filename)
    if focus:
        return focus
    if re.search(r"analyst|general|master|main|resume|cv", filename, re.I) and not headline:
        return "General"
    if re.search(r"_analyst\b|\banalyst\.pdf$", filename.lower()):
        return "General"
    for label, _, rx in VARIANT_RULES:
        if rx and re.search(rx, headline or "", re.I):
            return label
    return "General"


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
        parts = [p.strip() for p in re.split(r"\s[·|]\s|\s+at\s+|,\s", head) if p.strip()]
        if parts:
            roles.append((parts[0], parts[1] if len(parts) > 1 else ""))
    return len(months), roles


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

    location = ""
    for line in first_lines[:4]:
        low = line.lower()
        for c in CITY_WORDS:
            if c in low:
                location = "Gurugram" if c in ("gurgaon", "gurugram") else ("Bengaluru" if c == "bangalore" else c.title())
                break
        if location:
            break

    best_months, roles, exp_lines, edu, achievements = 0, [], [], [], []
    variants = []
    for fname, text in resumes.items():
        sec = _sections(text)
        exp = sec.get("professional experience") or sec.get("work experience") or sec.get("experience") or []
        months, r = _months_worked(exp, today)
        if months > best_months:
            best_months, roles = months, r
        exp_lines.extend(exp)
        edu.extend(_clean_bullet(l) for l in sec.get("education", []))
        for l in exp:
            if l.startswith(("▪", "•", "-", "*", "●")) and re.search(r"\d", l):
                achievements.append(_clean_bullet(l))
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        head = LINK_RE.sub("", EMAIL_RE.sub("", PHONE_RE.sub("", lines[1] if len(lines) > 1 else ""))).strip(" |")
        variants.append({
            "label": display_name(fname),
            "file": fname,
            "focus": variant_focus(fname, head),
            "headline": head,
            "skills": extract_skills(text),
        })

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

    counts = skill_counts(all_text)
    skills = sorted(counts, key=lambda s: -counts[s])
    edu_unique = []
    for e in edu:
        if e and e not in edu_unique:
            edu_unique.append(e)

    return {
        "name": name,
        "headline": LINK_RE.sub("", EMAIL_RE.sub("", headline)).strip(" |"),
        "location": location,
        "current_title": roles[0][0] if roles else "",
        "current_company": roles[0][1] if roles else "",
        "companies": [c for _, c in roles],
        "years_experience": years,
        "skills": skills,
        "skill_counts": counts,
        "industries": detect_industries("\n".join(exp_lines), min_hits=2)[:4],
        "achievements": unique[:14],
        "education": edu_unique[:4],
        "variants": variants,
        "contact_removed": contact_found,
        "source_files": list(resumes.keys()),
    }


def load_resumes(folder: Path) -> dict[str, str]:
    out = {}
    for p in sorted(folder.glob("*.pdf")):
        try:
            out[p.name] = extract_pdf_text(p)
        except Exception as exc:  # unreadable PDF: show it, don't crash setup
            out[p.name] = ""
            print(f"[resume] could not read {p.name}: {exc}")
    return {k: v for k, v in out.items() if v.strip()}


# ---------------------------------------------------------------- role suggestions
ROLE_CATALOG = [
    # title, signal skills, search queries, min years (soft), max years (soft)
    ("Business Analyst", ["SQL", "Excel", "Stakeholder Management", "Requirement Gathering", "KPI Design", "Dashboards", "Root Cause Analysis"],
     ["business analyst"], 0, 6),
    ("Senior Business Analyst", ["SQL", "Excel", "Stakeholder Management", "Requirement Gathering", "KPI Design", "Data Storytelling"],
     ["senior business analyst"], 3, 8),
    ("Data Analyst", ["SQL", "Python", "Excel", "Statistics", "Data Visualization", "Power BI", "Pandas"],
     ["data analyst"], 0, 5),
    ("Senior Data Analyst", ["SQL", "Python", "Statistics", "Power BI", "ETL", "Data Modeling", "A/B Testing"],
     ["senior data analyst"], 3, 8),
    ("Business Intelligence Analyst", ["Power BI", "DAX", "Tableau", "SQL", "Data Modeling", "MIS Reporting", "ETL", "Dashboards"],
     ["business intelligence analyst", "bi analyst"], 1, 7),
    ("Product Analyst", ["SQL", "A/B Testing", "Funnel Analysis", "Product Analytics", "Segmentation / Clustering", "Python", "KPI Design"],
     ["product analyst"], 1, 6),
    ("Strategy Analyst / Analytics Consultant", ["Problem Structuring", "Stakeholder Management", "Data Storytelling", "Growth Strategy", "Excel", "Forecasting"],
     ["strategy analyst", "analytics consultant"], 1, 7),
    ("Decision Scientist / Marketing Analytics", ["Python", "Machine Learning", "Segmentation / Clustering", "Statistics", "A/B Testing", "Marketing Analytics"],
     ["decision scientist", "marketing analyst"], 1, 7),
    ("Business / Revenue Operations Analyst", ["KPI Design", "Funnel Analysis", "Excel", "SQL", "Forecasting", "Process Optimization", "Automation"],
     ["business operations analyst", "revenue operations analyst"], 1, 7),
    ("MIS / Reporting Analyst", ["Excel", "MIS Reporting", "Automation", "SQL", "Dashboards", "Google Apps Script"],
     ["mis analyst", "reporting analyst"], 0, 6),
    ("Data Scientist (Associate)", ["Python", "Machine Learning", "Scikit-Learn", "NLP", "Statistics", "Regression"],
     ["associate data scientist"], 1, 5),
    ("Pricing / Insights Analyst", ["Pricing", "Excel", "SQL", "Statistics", "Data Storytelling", "Forecasting"],
     ["pricing analyst", "insights analyst"], 1, 6),
    ("Analytics Manager", ["Stakeholder Management", "SQL", "Power BI", "Data Storytelling", "KPI Design", "Problem Structuring"],
     ["analytics manager"], 5, 12),
]


def _evidence(skills: list[str], achievements: list[str]) -> str:
    from .skills import _COMPILED
    for sk in skills:
        for a in achievements:
            if any(p.search(a) for p in _COMPILED.get(sk, [])):
                short = re.split(r";| via | across | for (?=[a-z])", a)[0].strip().rstrip(",")
                return short if len(short) <= 95 else short[:92].rsplit(" ", 1)[0] + "…"
    return ""


def suggest_roles(profile: dict, n_min: int = 8, n_max: int = 12) -> list[dict]:
    """Rank catalog roles by how strongly the resume evidences each role's signal skills."""
    counts = profile.get("skill_counts") or {s: 1 for s in profile.get("skills", [])}
    yrs = float(profile.get("years_experience") or 0)
    ach = profile.get("achievements", [])
    heads = " ".join([profile.get("current_title", ""), profile.get("headline", "")]
                     + [v.get("headline", "") for v in profile.get("variants", [])]).lower()
    scored = []
    for title, signals, queries, ymin, ymax in ROLE_CATALOG:
        matched = [s for s in signals if counts.get(s)]
        strength = sum(min(counts.get(s, 0), 6) / 6 for s in signals) / len(signals)
        words = [w for w in re.findall(r"[a-z]+", title.lower())
                 if w not in ("senior", "analyst", "associate", "and", "manager")]
        if any(fuzz.partial_ratio(q, heads) >= 90 for q in queries):
            affinity = 1.0
        elif words and any(w in heads for w in words):
            affinity = 0.6
        else:
            affinity = 0.3
        if ymin <= yrs <= ymax:
            senior = 1.0
        elif yrs < ymin:
            senior = max(0.0, 1 - (ymin - yrs) / 3)
        else:
            senior = max(0.3, 1 - (yrs - ymax) / 6)
        score = round(70 * strength + 20 * affinity + 10 * senior) - (10 if yrs < ymin else 0)
        reason = (", ".join(matched[:3]) + " on your resume") if matched else "Adjacent to your experience"
        generic = {"SQL", "Excel", "Python", "Stakeholder Management"}
        ev = _evidence([m for m in matched if m not in generic] + [m for m in matched if m in generic], ach)
        if ev:
            reason += f". Evidence: {ev}"
        if yrs < ymin:
            reason += f" (stretch: usually {ymin}+ years)"
        scored.append({"title": title, "score": score, "reason": reason, "queries": queries})
    scored.sort(key=lambda r: -r["score"])
    keep = [r for r in scored if r["score"] >= 55][:n_max]
    if len(keep) < n_min:
        keep = scored[:n_min]
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
