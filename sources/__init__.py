"""Source adapters. To add one: subclass sources.base.Source, implement fetch(), add it to ALL_SOURCES."""
from .aggregators import Adzuna, Jooble, JSearch, SerpApi
from .alerts import EmailAlerts
from .ats import Ashby, Greenhouse, Lever, SmartRecruiters, Workable, Workday
from .manual import Manual

ALL_SOURCES = [Greenhouse(), Lever(), Ashby(), Workable(), SmartRecruiters(), Workday(),
               Adzuna(), Jooble(), JSearch(), SerpApi(), EmailAlerts(), Manual()]
BY_NAME = {s.name: s for s in ALL_SOURCES}

# How each of the 7 portals the user asked about is covered, and by which adapters.
PORTAL_COVERAGE = {
    "LinkedIn": {
        "adapters": ["jsearch", "serpapi", "alerts", "manual"],
        "how": "Public listings through Google-Jobs APIs, your LinkedIn alert emails, and Import by URL/JD.",
        "limit": "No logged-in access. LinkedIn job pages sit behind a login wall and its robots.txt blocks "
                 "automated checks, so LinkedIn-only jobs need your one-click 'Mark as verified by me'.",
    },
    "Naukri": {
        "adapters": ["jsearch", "serpapi", "jooble", "alerts", "manual"],
        "how": "Google-Jobs API and Jooble results that link to Naukri, Naukri alert emails, and Import by URL/JD.",
        "limit": "No logged-in access and no scraping of Naukri search pages.",
    },
    "Indeed": {
        "adapters": ["jsearch", "serpapi", "jooble", "alerts", "manual"],
        "how": "Through the aggregator APIs and Indeed alert emails.",
        "limit": "Indeed's robots.txt does not allow automated reading of its search pages, so they are not fetched.",
    },
    "IIMJobs/Hirist": {
        "adapters": ["alerts", "manual", "jsearch", "serpapi"],
        "how": "IIMJobs/Hirist alert emails, Import by URL/JD, and any Google-Jobs results that link there.",
        "limit": "No public API.",
    },
    "Instahyre": {
        "adapters": ["alerts", "manual"],
        "how": "Instahyre alert emails and Import by URL/JD only.",
        "limit": "Instahyre jobs need a login to view, so they can't be checked automatically.",
    },
    "Foundit": {
        "adapters": ["jsearch", "serpapi", "jooble", "manual"],
        "how": "Through the aggregator APIs and Import by URL/JD.",
        "limit": "Foundit search pages are not fetched directly.",
    },
    "Company/ATS": {
        "adapters": ["greenhouse", "lever", "ashby", "workable", "smartrecruiters", "workday", "adzuna", "jooble"],
        "how": "Public job-board JSON for the companies in config/employers.yaml (Greenhouse, Lever, Ashby, Workable, "
               "SmartRecruiters, Workday) plus the Adzuna and Jooble APIs.",
        "limit": "Only companies listed in employers.yaml are searched directly. Add more from Settings.",
    },
}
