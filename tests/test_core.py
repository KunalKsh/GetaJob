from datetime import date, datetime, timedelta

import pytest

from core.config import IST
from core.dates import age_days, parse_posted, tier_for_age
from core.dedup import dedupe, merge, norm_company, norm_title, same_posting
from core.locations import METRO, NCR, REMOTE, map_location
from core.normalize import make_job, parse_experience, parse_salary, portal_from_url
from core.scoring import score_job
from core.select import select_buckets
from core.verify import detect_expiry, detect_login_wall, is_generic_redirect, quality_flags

NOW = datetime(2026, 10, 30, 10, 0, tzinfo=IST)
TODAY = NOW.date()


# ------------------------------------------------------------------ relative and absolute dates
@pytest.mark.parametrize("raw,days,conf", [
    ("Posted Today", 0, "relative"),
    ("Just posted", 0, "relative"),
    ("5 hours ago", 0, "relative"),
    ("Posted Yesterday", 1, "relative"),
    ("2 days ago", 2, "relative"),
    ("Posted 3 Days Ago", 3, "relative"),
    ("1 week ago", 7, "relative"),
    ("2 weeks ago", 14, "relative"),
    ("a month ago", 30, "relative"),
    ("Posted 30+ Days Ago", 31, "relative"),
    ("2026-10-14", 16, "exact"),
    ("2026-10-14T03:53:37-04:00", 16, "exact"),
    ("2026-10-29T20:00:00Z", 0, "exact"),  # 1:30 am on 30 Oct in India
    ("14 Oct 2026", 16, "exact"),
])
def test_parse_posted(raw, days, conf):
    d, c = parse_posted(raw, NOW)
    assert c == conf
    assert (TODAY - d).days == days


@pytest.mark.parametrize("raw", [None, "", "Not mentioned", "Hiring now", "Apply by Friday"])
def test_unknown_dates_are_never_guessed(raw):
    assert parse_posted(raw, NOW) == (None, "unknown")


def test_epoch_milliseconds():
    ms = int((NOW - timedelta(days=4)).timestamp() * 1000)
    d, c = parse_posted(ms, NOW)
    assert c == "exact" and (TODAY - d).days == 4


# ------------------------------------------------------------------ freshness tiers
@pytest.mark.parametrize("age,tier", [(0, 1), (3, 1), (4, 2), (7, 2), (8, 3), (15, 3), (16, 4), (30, 4), (31, None),
                                      (None, None)])
def test_tiers(age, tier):
    assert tier_for_age(age) == tier


# ------------------------------------------------------------------ location mapping
@pytest.mark.parametrize("raw,city,bucket", [
    ("Gurgaon, Haryana", "Gurugram", NCR),
    ("DLF Cyber City, Gurugram", "Gurugram", NCR),
    ("Greater Noida", "Noida", NCR),
    ("Ghaziabad, UP", "Noida", NCR),
    ("New Delhi", "Delhi", NCR),
    ("India, Delhi NCR", "Delhi NCR", NCR),
    ("Gurugram, Delhi NCR", "Gurugram", NCR),
    ("Bangalore", "Bengaluru", METRO),
    ("Navi Mumbai, Maharashtra", "Mumbai", METRO),
    ("Thane", "Mumbai", METRO),
    ("Secunderabad", "Hyderabad", METRO),
    ("Hinjewadi, Pune", "Pune", METRO),
    ("Chennai", "Chennai", METRO),
    ("Trivandrum, Kerala", "Thiruvananthapuram", METRO),
    ("Remote", "Remote", REMOTE),
    ("Singapore", None, None),
])
def test_location_mapping(raw, city, bucket):
    loc = map_location(raw)
    assert loc["city"] == city and loc["bucket"] == bucket


def test_multi_city_prefers_ncr_and_remote_needs_base_city():
    assert map_location("Bengaluru; Gurugram; Pune")["city"] == "Gurugram"
    loc = map_location("Remote - Noida")
    assert loc["remote"] and loc["city"] == "Noida"


# ------------------------------------------------------------------ salary, experience, portals
@pytest.mark.parametrize("text,expected", [
    ("₹12-18 LPA", (12, 18)),
    ("12 - 18 Lacs P.A.", (12, 18)),
    ("INR 1,200,000 - 1,800,000", (12, 18)),
    ("₹50,000 - ₹80,000 a month", (6, 9.6)),
    ("Not disclosed", (None, None)),
    ("$90,000 - $120,000", (None, None)),
    ("", (None, None)),
])
def test_salary(text, expected):
    assert parse_salary(text) == expected


def test_experience():
    assert parse_experience("We need 3-5 years of experience")[:2] == (3, 5)
    assert parse_experience("Minimum 2 years in analytics")[:2] == (2, None)
    assert parse_experience("4+ yrs with SQL")[:2] == (4, None)
    assert parse_experience("No experience mentioned")[:2] == (None, None)


def test_portal_from_url():
    assert portal_from_url("https://www.linkedin.com/jobs/view/123") == "LinkedIn"
    assert portal_from_url("https://www.naukri.com/job-listings-x") == "Naukri"
    assert portal_from_url("https://www.iimjobs.com/j/x") == "IIMJobs/Hirist"
    assert portal_from_url("https://careers.example.com/x") == "Company/ATS"


# ------------------------------------------------------------------ de-duplication
def _job(**kw):
    base = dict(source_name="adzuna", native_id="1", title="Senior Product Analyst", company="Sample Fintech Pvt Ltd",
                location_raw="Gurgaon", posted_raw="2026-10-28", source_url="https://example.com/a", now=NOW)
    base.update(kw)
    return make_job(**base)


def test_norms():
    assert norm_title("Sr. Analyst - BI, Reporting (4B)") == norm_title("Senior Analyst - BI, Reporting")
    assert norm_company("India: Mastercard India Services Private Limited") == "mastercard"


def test_same_posting_across_portals_merges_links_and_keeps_ats_record():
    a = _job()
    b = _job(source_name="greenhouse", native_id="tok:9", company="Sample Fintech", location_raw="Gurugram, Haryana",
             posted_raw="2026-10-27", source_url="https://boards.example.com/9")
    assert same_posting(a, b)
    out = dedupe([a, b])
    assert len(out) == 1
    m = out[0]
    assert m["source_name"] == "greenhouse"
    assert {l["url"] for l in m["links"]} == {"https://example.com/a", "https://boards.example.com/9"}
    assert m["posted_date"] == "2026-10-27"  # equal confidence: keep the older date


def test_different_city_or_title_is_not_a_duplicate():
    assert not same_posting(_job(), _job(location_raw="Pune"))
    assert not same_posting(_job(), _job(title="Product Manager"))


def test_merge_prefers_exact_date_over_relative():
    a = _job(posted_raw="3 days ago")
    b = _job(source_name="lever", native_id="x", posted_raw="2026-10-20")
    m = merge(a, b)
    assert m["posted_date"] == "2026-10-20" and m["posted_date_confidence"] == "exact"


# ------------------------------------------------------------------ verification helpers
@pytest.mark.parametrize("text", [
    "This job is no longer accepting applications",
    "Sorry, this position has been filled.",
    "The job has expired",
    "This job posting is no longer active",
    "Applications are now closed",
])
def test_expiry_detected(text):
    assert detect_expiry(text)


@pytest.mark.parametrize("text", ["Apply now for this exciting role", "We are accepting applications until 30 Nov"])
def test_live_text_not_expired(text):
    assert detect_expiry(text) is None


def test_login_wall_and_generic_redirect():
    assert detect_login_wall("https://www.linkedin.com/authwall?trk=x", "")
    assert detect_login_wall("https://x.com/job/1", '<p>Please sign in to continue</p><input type="password">')
    assert not detect_login_wall("https://x.com/job/1", "<h1>Data Analyst</h1>")
    assert is_generic_redirect("https://x.com/careers/jobs/12345-data-analyst", "https://x.com/careers")
    assert not is_generic_redirect("https://x.com/jobs/123", "https://x.com/jobs/123/")


def test_scam_flags():
    j = _job(description="Pay a registration fee of Rs 2000. Send CV to hr.jobs@gmail.com")
    flags = quality_flags(j)
    assert "Asks for a payment or deposit" in flags
    assert "Recruiter uses a personal email address" in flags


# ------------------------------------------------------------------ bucket selection
PREFS = {"bucket_size": 50, "max_age_days": 30, "exclude_companies": ["Sample Excluded Co"], "exclude_title_words": ["director"],
         "salary_hard_filter": True, "salary_min_lpa": 12, "salary_max_lpa": 18, "roles": [{"title": "Data Analyst"}],
         "profile": {}}


def _sel_job(i, age, fit, bucket=NCR, **kw):
    j = {"id": f"j{i}", "title": f"Data Analyst {i}", "company": f"Co {i}", "bucket": bucket, "city": "Gurugram",
         "posted_date": (TODAY - timedelta(days=age)).isoformat(), "posted_date_confidence": "exact",
         "status": "verified", "fit_score": fit, "salary_min_lpa": None, "salary_max_lpa": None}
    j.update(kw)
    return j


def test_selection_fills_by_tier_then_fit_and_caps_at_50():
    jobs = [_sel_job(i, age=20, fit=99) for i in range(30)]           # tier 4, very high fit
    jobs += [_sel_job(100 + i, age=2, fit=40 + i) for i in range(40)]  # tier 1, lower fit
    out = select_buckets(jobs, PREFS, TODAY)["primary"]
    assert out["count"] == 50
    assert out["shortfall"] is None
    chosen = out["jobs"]
    assert all(age_days(j["posted_date"], TODAY) <= 3 for j in chosen[:40])  # every tier-1 job first
    assert [j["fit_score"] for j in chosen[:40]] == sorted([j["fit_score"] for j in chosen[:40]], reverse=True)
    assert out["tiers"] == {1: 40, 2: 0, 3: 0, 4: 10}


def test_selection_under_50_reports_real_count_and_reasons():
    jobs = [_sel_job(i, age=5, fit=70) for i in range(12)]
    jobs.append(_sel_job(50, age=45, fit=90))                                   # too old
    jobs.append(_sel_job(51, age=1, fit=90, posted_date=None, posted_date_confidence="unknown"))
    jobs.append(_sel_job(52, age=1, fit=90, status="login_required"))          # not verified
    jobs.append(_sel_job(53, age=1, fit=90, status="login_required", manual_verified=True))  # confirmed by user
    jobs.append(_sel_job(54, age=1, fit=90, company="Sample Excluded Co Group"))         # excluded company
    jobs.append(_sel_job(55, age=1, fit=90, salary_min_lpa=5, salary_max_lpa=7))  # stated salary too low
    jobs.append(_sel_job(56, age=1, fit=90, title="Director, Analytics"))      # outside seniority band
    jobs.append(_sel_job(57, age=1, fit=90, status="expired"))
    jobs.append(_sel_job(58, age=1, fit=90, title="Senior Fund Accounting Analyst"))  # not an analytics role
    out = select_buckets(jobs, PREFS, TODAY)["primary"]
    assert out["count"] == 13
    assert "Only 13" in out["shortfall"]
    assert out["reasons"] == {"too_old": 1, "date_unknown": 1, "not_verified": 1, "excluded_company": 1,
                              "salary": 1, "excluded_title": 1, "off_target": 1}


def test_unknown_salary_passes_hard_filter():
    out = select_buckets([_sel_job(1, age=1, fit=80)], PREFS, TODAY)["primary"]
    assert out["count"] == 1


# ------------------------------------------------------------------ scoring
def test_scoring_explains_matches_and_gaps():
    prefs = {"roles": [{"title": "Product Analyst"}], "salary_min_lpa": 12, "salary_max_lpa": 18,
             "prefer_industries": ["Fintech"], "profile": {"skills": ["SQL", "Python", "A/B Testing", "Power BI"],
                                                            "years_experience": 3}}
    desc = ("We are a fintech lending company.\nRequirements\n• 2-4 years of experience\n• SQL and Python\n"
            "• A/B testing\nNice to have\n• Snowflake\n") * 3
    j = _job(title="Product Analyst", description=desc, salary_text="₹14-18 LPA")
    score, det = score_job(j, prefs)
    assert 70 <= score <= 100
    assert {"SQL", "Python", "A/B Testing"} <= set(det["matched"])
    assert "Snowflake (nice to have)" in det["gaps"]
    assert det["parts"]["experience"] == 15 and det["parts"]["salary"] == 10 and det["parts"]["industry"] == 10


# ------------------------------------------------------------------ relevance
@pytest.mark.parametrize("title,ok", [
    ("Senior Business Data Analyst", True), ("Associate Analyst, Insights & Enablement", True),
    ("Product Analyst II", True), ("SAS SQL - BI Analyst", True), ("Strategic Pricing Analyst", True),
    ("Sr. Analyst - BI, Reporting and Data Visualization 4A", True), ("Associate Data Scientist", True),
    ("Analyst - Abstractions", False), ("Senior Fund Accounting Analyst", False), ("Senior Compliance Analyst", False),
    ("Senior Analyst - HR Operations", False), ("Senior Vendor Management Analyst", False),
    ("Data Engineer", False), ("Senior GST Analyst", False), ("Analyst", False),
])
def test_relevance(title, ok):
    from core.relevance import is_relevant
    assert is_relevant(title, [{"title": "Business Analyst"}, {"title": "Product Analyst"}]) is ok
