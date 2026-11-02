import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Every test run uses a throwaway SQLite database, never a real one.
_tmp = tempfile.mkdtemp(prefix="getajob_test_")
os.environ["GETAJOB_DATA"] = _tmp
# Set TEST_DATABASE_URL to run the same tests against Postgres (as CI does).
os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL") or f"sqlite:///{Path(_tmp, 'test.db').as_posix()}"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["CRON_SECRET"] = "test-cron-secret"
os.environ["ADMIN_EMAIL"] = "admin@example.com"
for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "ADZUNA_APP_ID", "JOOBLE_KEY", "RAPIDAPI_KEY", "SERPAPI_KEY"):
    os.environ.pop(k, None)


def make_pdf(lines: list[str]) -> bytes:
    """A minimal text PDF, so upload tests don't need real resumes."""
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    body = "BT /F1 10 Tf 50 780 Td 14 TL " + " ".join(f"({esc(l)}) Tj T*" for l in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(body)} >>\nstream\n{body}\nendstream",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, start=1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def resume_lines(name: str, email: str, focus: str) -> list[str]:
    return [name.upper(), f"Business Analyst | {focus} | SQL | Python | Power BI", f"Gurgaon, India | {email}",
            "PROFESSIONAL EXPERIENCE",
            "Business Analyst - Sample Motors - Gurgaon Sep 2023 - Present",
            "- Built 12 Power BI dashboards with DAX for leadership reviews and KPI design.",
            "- Ran A/B tests and funnel analysis in SQL and Python, lifting conversion 18%.",
            "- Automated MIS reporting in Excel and Google Apps Script, cutting manual work 40%.",
            "Data Analyst - Sample Insurance - Noida Jan 2022 - Aug 2023",
            "- Analysed 600K records with Pandas for stakeholder management and root cause analysis.",
            "EDUCATION", "- B.Com, Sample University 2018 - 2021"]


@pytest.fixture(scope="session")
def app_client():
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        yield c


def csrf_of(client, path="/") -> str:
    return re.search(r'name="csrf-token" content="([^"]+)"', client.get(path).text).group(1)


@pytest.fixture(scope="session")
def admin(app_client):
    """The admin account, created through the one-time setup link."""
    from core import db
    tok = db.create_token("admin@example.com", "setup", None)
    c = app_client
    c.post(f"/invite/{tok}", data={"csrf_token": csrf_of(c, f"/invite/{tok}"), "name": "Admin Person",
                                   "password": "admin-pass-12345", "confirm": "admin-pass-12345"})
    return c
