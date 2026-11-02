"""Adapters, alert parsing, resume parsing and a full offline (demo) refresh."""
import email
from email import policy

from core.config import FIXTURES_DIR
from core.resume import build_profile, suggest_roles
from sources.alerts import parse_message

RESUME = """JANE SAMPLE
Business Analyst | SQL · Python · Power BI · A/B Testing
Gurgaon, India | +91 9000000000 | jane@example.com | linkedin.com/in/jane
PROFESSIONAL EXPERIENCE
Business Analyst · Sample Motors · Gurgaon Sep 2023 – Present
▪ Built 12 Power BI dashboards with DAX for leadership reviews.
▪ Ran A/B tests and funnel analysis in SQL and Python, lifting conversion 18%.
Data Analyst · Sample Insurance · Noida Jan 2022 – Aug 2023
▪ Automated MIS reporting in Excel, cutting manual work by 40%.
EDUCATION
▪ B.Com, Sample University | 2018 – 2021
"""


def test_resume_profile_strips_contacts_and_counts_years():
    prof = build_profile({"Jane_Analyst.pdf": RESUME})
    assert prof["contact_removed"]
    assert "jane@example.com" not in str(prof) and "9000000000" not in str(prof)
    assert prof["current_title"] == "Business Analyst"
    assert prof["location"] == "Gurugram"
    assert 3.0 <= prof["years_experience"] <= 6
    assert {"SQL", "Python", "Power BI", "DAX", "A/B Testing"} <= set(prof["skills"])


def test_role_suggestions_have_reasons():
    roles = suggest_roles(build_profile({"Jane_Analyst.pdf": RESUME}))
    assert 8 <= len(roles) <= 12
    assert all(r["reason"] for r in roles)
    assert any("Business Intelligence" in r["title"] for r in roles)


def _eml(name):
    with open(FIXTURES_DIR / "alerts" / name, "rb") as fh:
        return email.message_from_binary_file(fh, policy=policy.default)


def test_linkedin_alert_parsing():
    items = parse_message(_eml("linkedin_alert_sample.eml"))
    titles = [i["title"] for i in items]
    assert "Business Analyst" in titles and "Senior Data Analyst" in titles
    assert "See all jobs" not in titles
    ba = next(i for i in items if i["title"] == "Business Analyst")
    assert ba["company"] == "Sample Payments Co (demo)"
    assert ba["location"].startswith("Gurugram")
    assert ba["portal"] == "LinkedIn"
    assert "linkedin.com" in ba["url"] and "trackingId" not in ba["url"]


def test_naukri_alert_unwraps_click_tracking():
    items = parse_message(_eml("naukri_alert_sample.eml"))
    assert {i["title"] for i in items} == {"BI Analyst", "Strategy Analyst"}
    bi = next(i for i in items if i["title"] == "BI Analyst")
    assert bi["url"].startswith("https://www.naukri.com/job-listings-")
    assert bi["company"] == "Sample Motors (demo)" and bi["location"] == "Gurugram"


def test_full_demo_refresh_offline(admin):
    """Runs every adapter on the fixtures, then dedup, verification, per-user scoring and selection."""
    from core import db, pipeline
    from core.select import select_buckets
    st = db.get_settings()
    st["demo_mode"] = True
    db.save_settings(st)
    uid = db.get_user_by_email("admin@example.com")["id"]
    prefs = db.get_prefs(uid)
    prefs.update(confirmed=True, profile=build_profile({"Jane_Analyst.pdf": RESUME}), exclude_companies=["Sample Excluded Co"],
                 roles=[{"title": "Business Analyst", "queries": ["business analyst"]},
                        {"title": "Product Analyst", "queries": ["product analyst"]},
                        {"title": "Data Analyst", "queries": ["data analyst"]}])
    db.save_prefs(uid, prefs)
    summary = pipeline.run_refresh("test")
    assert summary and summary["requests"] == 0  # nothing went to the internet
    jobs = db.jobs_for_user(uid, demo=True)
    titles = {j["title"] for j in jobs}
    assert "Data Engineer" not in titles and "Associate - Customer Support" not in titles
    spa = [j for j in jobs if j["title"] == "Senior Product Analyst" and j["city"] == "Gurugram"]
    assert len(spa) == 1 and len(spa[0]["links"]) == 2  # Greenhouse + Adzuna copies merged
    assert all(j.get("fit_score") is not None for j in jobs if j.get("bucket") and j["status"] == "verified")
    view = {**db.get_settings(), **db.get_prefs(uid)}
    b = select_buckets(jobs, view)
    assert 0 < b["ncr"]["count"] < 50 and b["ncr"]["shortfall"]
    assert not any(j["company"] == "Sample Excluded Co" for j in b["ncr"]["jobs"])
    assert all(j["status"] == "verified" for j in b["ncr"]["jobs"] + b["metro"]["jobs"])
    n = len(db.all_jobs())
    pipeline.run_refresh("test")
    assert len(db.all_jobs()) == n  # a second refresh adds no duplicates


def test_web_pages_render(admin):
    for path in ["/dashboard", "/dashboard?tab=metro&sort=fit", "/review", "/review?show=check", "/tracker",
                 "/health", "/import", "/profile", "/resumes", "/account", "/admin", "/admin?tab=users",
                 "/admin?tab=settings", "/export/top100.xlsx", "/export/tracker.csv"]:
        r = admin.get(path, follow_redirects=False)
        assert r.status_code in (200, 303), path
