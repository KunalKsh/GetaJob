"""Excel and CSV exports."""
from __future__ import annotations

import re

import csv
import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .dates import age_days, tier_for_age, today_ist
from .normalize import FIELDS
from .verify import STATUS_LABEL

EXTRA = ["tier", "age_days", "fit_score", "resume_variant", "matched_skills", "skill_gaps", "verify_note",
         "flags", "reposted", "all_links", "tracker_status", "tracker_notes", "follow_up"]


def _row(job: dict, tracker: dict) -> list:
    today = today_ist()
    a = age_days(job.get("posted_date"), today)
    det = job.get("fit_detail") or {}
    t = tracker.get(job["id"], {})
    vals = []
    for f in FIELDS:
        v = job.get(f)
        if f == "status":
            v = STATUS_LABEL.get(v, v) + (" (confirmed by you)" if job.get("manual_verified") else "")
        if f == "skills_extracted":
            v = ", ".join(v or [])
        if f == "description":
            v = (v or "")[:3000]
        if v is None or v == "":
            v = "Unknown" if f in ("salary_text", "company", "posted_date", "experience_required") else ""
        vals.append(v)
    vals += [tier_for_age(a) or "", a if a is not None else "", job.get("fit_score"), job.get("resume_variant", ""),
             ", ".join(det.get("matched") or []), ", ".join(det.get("gaps") or []), job.get("verify_note", ""),
             "; ".join(job.get("flags") or []), "Yes" if job.get("reposted") else "",
             " | ".join(f"{l.get('portal')}: {l.get('url')}" for l in job.get("links") or []),
             t.get("status", ""), t.get("notes", ""), t.get("follow_up", "")]
    return vals


def _sheet(ws, title: str, jobs: list[dict], tracker: dict):
    ws.title = title[:31]
    head = FIELDS + EXTRA
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F4FA8")
        c.alignment = Alignment(vertical="center", wrap_text=True)
    for j in jobs:
        ws.append(_row(j, tracker))
    widths = {"title": 38, "company": 24, "description": 60, "apply_url": 40, "source_url": 40, "all_links": 50,
              "matched_skills": 34, "skill_gaps": 30, "verify_note": 34}
    for i, h in enumerate(head, start=1):
        ws.column_dimensions[get_column_letter(i)].width = widths.get(h, 15)
    url_cols = [head.index("apply_url") + 1, head.index("source_url") + 1]
    for r in range(2, ws.max_row + 1):
        for col in url_cols:
            cell = ws.cell(row=r, column=col)
            if isinstance(cell.value, str) and cell.value.startswith("http"):
                cell.hyperlink = cell.value
                cell.font = Font(color="1F4FA8", underline="single")
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions


def _sheet_name(label: str, fallback: str = "First choice") -> str:
    name = re.sub(r"[\[\]:*?/\\]", " ", label or "").strip()[:31]
    return name or fallback


def top100_xlsx(buckets: dict, tracker: dict) -> bytes:
    wb = Workbook()
    _sheet(wb.active, _sheet_name(buckets["primary"]["label"]), buckets["primary"]["jobs"], tracker)
    _sheet(wb.create_sheet(), _sheet_name(buckets["secondary"]["label"], "Other cities"), buckets["secondary"]["jobs"], tracker)
    info = wb.create_sheet("About")
    info.append(["Bucket", "Postings", "Note"])
    for b in ("primary", "secondary"):
        info.append([buckets[b]["label"], buckets[b]["count"], buckets[b]["shortfall"] or "Full list of the strongest, freshest verified postings"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def tracker_rows(jobs: dict[str, dict], tracker: dict) -> list[list]:
    rows = [["Status", "Follow-up", "Notes", "Title", "Company", "City", "Posted", "Fit", "Resume to send", "Apply link",
             "Updated"]]
    for jid, t in sorted(tracker.items(), key=lambda kv: str(kv[1].get("updated_at") or ""), reverse=True):
        j = jobs.get(jid) or {}
        rows.append([t["status"], t.get("follow_up", ""), t.get("notes", ""), j.get("title", ""), j.get("company", ""),
                     j.get("city", ""), j.get("posted_date") or "Unknown", j.get("fit_score", ""),
                     j.get("resume_variant", ""), j.get("apply_url", ""), str(t.get("updated_at") or "")[:16]])
    return rows


def tracker_csv(jobs: dict, tracker: dict) -> str:
    buf = io.StringIO()
    csv.writer(buf).writerows(tracker_rows(jobs, tracker))
    return "﻿" + buf.getvalue()  # BOM so Excel opens it as UTF-8


def tracker_xlsx(jobs: dict, tracker: dict) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Tracker"
    for r in tracker_rows(jobs, tracker):
        ws.append(r)
    for c in ws[1]:
        c.font = Font(bold=True)
    for i, w in enumerate([12, 12, 40, 38, 24, 12, 12, 6, 20, 50, 20], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
