"""The matching works for any profession, not just analytics."""
from datetime import date, timedelta

import pytest

from core.relevance import is_relevant
from core.resume import build_profile, default_families, suggest_roles
from core.scoring import pick_resume, score_job
from core.select import select_buckets
from core.taxonomy import BAND_NAMES, default_bands, title_level
from sources.discover import slugs
from tests.sample_resumes import ACCOUNTANT, NURSE, SALES, SOFTWARE

TODAY = date(2026, 11, 2)


@pytest.mark.parametrize("text,family,role", [
    (SOFTWARE, "software", "Backend Developer"),
    (NURSE, "healthcare", "Staff Nurse"),
    (ACCOUNTANT, "finance", "Accountant"),
    (SALES, "sales", "Business Development Manager"),
])
def test_families_and_roles_come_from_the_resume(text, family, role):
    prof = build_profile({"resume.pdf": text})
    assert default_families(prof)[0] == family
    titles = [r["title"] for r in suggest_roles(prof)]
    assert any(role in t for t in titles[:8]), titles
    assert not any("Analyst" in t for t in titles[:5]) or family == "finance"


def test_resume_location_and_free_form_skills():
    prof = build_profile({"nurse.pdf": NURSE})
    assert prof["location"] == "Kochi"
    assert "Infection Control" in prof["custom_skills"]
    assert build_profile({"a.pdf": ACCOUNTANT})["location"] == "Delhi"


def test_credentials_keep_nurses_away_from_doctor_roles():
    titles = [r["title"] for r in suggest_roles(build_profile({"n.pdf": NURSE}))[:5]]
    assert "Medical Officer" not in titles and "Senior Medical Officer" not in titles


@pytest.mark.parametrize("title,fams,ok", [
    ("Senior Backend Engineer", ["software"], True),
    ("Java Developer - Spring Boot", ["software"], True),
    ("Mechanical Design Engineer", ["software"], False),
    ("Data Analyst", ["software"], False),
    ("Staff Nurse - ICU", ["healthcare"], True),
    ("Senior Accountant", ["finance"], True),
    ("Key Account Manager", ["finance"], False),
    ("Key Account Manager", ["sales"], True),
    ("Area Sales Manager", ["sales"], True),
    ("Salesforce Developer", ["sales"], False),
    ("HR Business Partner", ["hr"], True),
    ("UI/UX Designer", ["design"], True),
    ("Civil Site Engineer", ["core_eng"], True),
    ("Analyst", ["finance"], False),
])
def test_relevance_follows_chosen_families(title, fams, ok):
    assert is_relevant(title, [], fams) is ok


def test_custom_role_counts_outside_family_patterns():
    roles = [{"title": "Clinical Data Manager"}]
    assert is_relevant("Senior Clinical Data Manager", roles, ["software"]) is True   # typed-in role still counts
    assert is_relevant("Data Manager", roles, ["software"]) is False
    # a role match is overruled when the person's family explicitly rules that kind of title out
    assert is_relevant("Business Analyst - Accounts Payable", [{"title": "Business Analyst"}], ["analytics"]) is False


def test_seniority_levels():
    assert title_level("Head of Sales")[1] == ["Director / Head"]
    assert "Entry level" in title_level("Junior Accountant")[1]
    assert title_level("Accountant") == ("Mid level", [])
    assert default_bands(0.5) == ["Entry level", "Mid level"]
    assert default_bands(3) == ["Mid level", "Senior"]
    assert set(default_bands(10)) <= set(BAND_NAMES)


def _job(i, title, city="Bengaluru", age=2, **kw):
    j = {"id": f"p{i}", "title": title, "company": f"Co {i}", "bucket": "metro", "city": city, "cities": [city],
         "posted_date": (TODAY - timedelta(days=age)).isoformat(), "posted_date_confidence": "exact",
         "status": "verified", "fit_score": 70, "salary_min_lpa": None, "salary_max_lpa": None}
    j.update(kw)
    return j


def test_lists_follow_chosen_cities_levels_and_job_types():
    prefs = {"bucket_size": 50, "max_age_days": 30, "families": ["software"], "roles": [{"title": "Backend Developer"}],
             "primary_cities": ["Bengaluru"], "secondary_cities": ["Pune", "Remote"],
             "seniority_bands": ["Mid level", "Senior"], "role_types": ["Full-time"]}
    jobs = [_job(1, "Backend Developer"), _job(2, "Senior Software Engineer", "Pune"),
            _job(3, "Director of Engineering"),                      # level outside the chosen bands
            _job(4, "Software Engineering Intern"),                  # internships not chosen
            _job(5, "Backend Engineer", exp_min=12, exp_max=15),     # asks for far more experience
            _job(6, "Java Developer", "Remote", bucket="remote"),
            _job(7, "Java Developer", "Chennai"),                    # city not chosen
            _job(8, "Accountant")]                                   # not a chosen job type
    out = select_buckets(jobs, prefs, TODAY)
    assert [j["id"] for j in out["primary"]["jobs"]] == ["p1"]
    assert {j["id"] for j in out["secondary"]["jobs"]} == {"p2", "p6"}
    assert out["primary"]["label"] == "Bengaluru"
    assert out["primary"]["reasons"] == {"excluded_title": 3, "off_target": 1}


def test_preferred_company_boost_and_resume_pick():
    prof = build_profile({"Arjun_Backend_Developer.pdf": SOFTWARE, "Arjun_Resume.pdf": SOFTWARE.replace("Senior", "Lead")})
    prefs = {"profile": prof, "roles": [{"title": "Backend Developer"}], "families": ["software"],
             "prefer_companies": ["Sample Payments"]}
    desc = "Requirements\n• Java, Spring Boot, Microservices, Kafka\n• 5-8 years\n" * 6
    base = {"title": "Senior Backend Developer", "description": desc, "city": "Bengaluru", "cities": ["Bengaluru"]}
    s1, d1 = score_job({**base, "company": "Other Co"}, prefs)
    s2, d2 = score_job({**base, "company": "Sample Payments Pvt Ltd"}, prefs)
    assert d2["preferred"] and not d1["preferred"] and s2 == min(100, s1 + 5)
    assert pick_resume(base, prefs) == "Arjun Backend Developer"


def test_board_slugs_from_company_names():
    assert slugs("Acme Robotics Pvt Ltd")[:2] == ["acmerobotics", "acme-robotics"]
    assert slugs("") == []
