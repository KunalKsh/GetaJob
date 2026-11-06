"""Licensed job-search APIs. Only search keywords and city names are sent; never resume data."""
from __future__ import annotations

import os
import re
from datetime import datetime

from core import db
from core.config import IST
from core.normalize import make_job, portal_from_name, portal_from_url

from .base import Ctx, Source

API_CITY = {"Gurugram": "Gurgaon", "Noida": "Noida", "Delhi": "Delhi", "Bengaluru": "Bangalore",
            "Hyderabad": "Hyderabad", "Mumbai": "Mumbai", "Pune": "Pune"}


def _pairs(ctx: Ctx, limit: int) -> list[tuple[str, str]]:
    """(query, city) pairs: every role in every city, highest-priority roles first, capped by the budget."""
    pairs = [(q, c) for q in ctx.role_queries for c in ctx.search_cities]
    return pairs[:max(0, limit)]


def _due(source: str, hours: float) -> bool:
    for h in db.health_all():
        if h["source"] == source and h.get("last_run"):
            try:
                last = datetime.fromisoformat(h["last_run"])
                return (datetime.now(IST) - last).total_seconds() >= hours * 3600
            except ValueError:
                return True
    return True


def _clean(t: str) -> str:
    return re.sub(r"<[^>]+>", "", t or "").strip()


# ------------------------------------------------------------------ Adzuna
class Adzuna(Source):
    name, label, kind = "adzuna", "Adzuna API", "api"
    requires_keys = ["ADZUNA_APP_ID", "ADZUNA_APP_KEY"]
    coverage_note = "Licensed API (free key). Broad India coverage; links go through Adzuna to the original listing."

    def fetch(self, ctx):
        budget = int(ctx.prefs["api_budget"].get("adzuna", 80))
        out = []
        pairs = [("demo", "demo")] if ctx.demo else _pairs(ctx, budget)
        for q, city in pairs:
            if ctx.demo:
                data = ctx.fixture("adzuna") or {"results": []}
            else:
                r = ctx.http.get("https://api.adzuna.com/v1/api/jobs/in/search/1", check_robots=False, cache_ttl=6 * 3600,
                                 params={"app_id": os.getenv("ADZUNA_APP_ID"), "app_key": os.getenv("ADZUNA_APP_KEY"),
                                         "title_only": q, "where": API_CITY.get(city, city), "max_days_old": 30,
                                         "results_per_page": 50, "sort_by": "date", "content-type": "application/json"})
                if r.status in (401, 403):
                    ctx.error(self.name, "Key rejected: check ADZUNA_APP_ID / ADZUNA_APP_KEY in .env")
                    break
                if r.status == 429:
                    ctx.error(self.name, "Daily limit reached; remaining queries skipped")
                    break
                if not r.ok:
                    ctx.error(self.name, f"'{q}' in {city}: HTTP {r.status} {r.error}")
                    continue
                data = r.json()
            for x in data.get("results", []):
                loc = (x.get("location") or {})
                loc_raw = ", ".join([loc.get("display_name") or ""] + list(loc.get("area") or [])[1:])
                title = _clean(x.get("title"))
                if not ctx.target_location(loc_raw) or not ctx.relevant_title(title):
                    continue
                predicted = str(x.get("salary_is_predicted", "1")) == "1"
                smin = smax = None
                if not predicted and x.get("salary_min"):  # Adzuna estimates are not real salaries: ignore them
                    smin, smax = round(float(x["salary_min"]) / 1e5, 1), round(float(x.get("salary_max") or x["salary_min"]) / 1e5, 1)
                url = x.get("redirect_url", "")
                out.append(make_job(
                    source_name=self.name, native_id=str(x.get("id")), title=title,
                    company=(x.get("company") or {}).get("display_name", ""), location_raw=loc_raw,
                    posted_raw=x.get("created"), source_url=url, description=_clean(x.get("description")),
                    salary_min_lpa=smin, salary_max_lpa=smax,
                    salary_text=f"₹{smin}–{smax} LPA (stated)" if smin else "",
                    source_portal="Company/ATS", links=[{"portal": "Company/ATS", "url": url, "source": "adzuna"}],
                    extra={"short_description": True}, now=ctx.now))
        return out


# ------------------------------------------------------------------ Jooble
class Jooble(Source):
    name, label, kind = "jooble", "Jooble API", "api"
    requires_keys = ["JOOBLE_KEY"]
    coverage_note = "Licensed API (free key). Listings often come from Naukri, Indeed and company sites."

    def fetch(self, ctx):
        budget = int(ctx.prefs["api_budget"].get("jooble", 60))
        out = []
        pairs = [("demo", "demo")] if ctx.demo else _pairs(ctx, budget)
        for q, city in pairs:
            if ctx.demo:
                data = ctx.fixture("jooble") or {"jobs": []}
            else:
                r = ctx.http.post(f"https://jooble.org/api/{os.getenv('JOOBLE_KEY')}",
                                  {"keywords": q, "location": API_CITY.get(city, city), "page": "1"},
                                  check_robots=False, cache_ttl=6 * 3600)
                if r.status in (401, 403):
                    ctx.error(self.name, "Key rejected: check JOOBLE_KEY in .env")
                    break
                if not r.ok:
                    ctx.error(self.name, f"'{q}' in {city}: HTTP {r.status} {r.error}")
                    continue
                data = r.json()
            for x in data.get("jobs", []):
                title = _clean(x.get("title"))
                if not ctx.target_location(x.get("location", "")) or not ctx.relevant_title(title):
                    continue
                link = x.get("link", "")
                portal = portal_from_name(x.get("source")) or "Company/ATS"
                out.append(make_job(
                    source_name=self.name, native_id=str(x.get("id")), title=title, company=x.get("company", ""),
                    location_raw=x.get("location", ""), posted_raw=x.get("updated"), date_confidence="aggregator",
                    source_url=link, description=_clean(x.get("snippet")), salary_text=x.get("salary", ""),
                    source_portal=portal, links=[{"portal": portal, "url": link, "source": "jooble"}],
                    extra={"short_description": True, "via": x.get("source", "")}, now=ctx.now))
        return out


def _apply_links(options: list[dict], fallback_url: str, source: str) -> tuple[list[dict], str, str]:
    links, direct = [], None
    for o in options or []:
        url = o.get("apply_link") or o.get("link") or ""
        if not url:
            continue
        name = o.get("publisher") or o.get("title") or ""
        portal = portal_from_name(name) or portal_from_url(url)
        links.append({"portal": portal, "url": url, "source": source, "via": name})
        if o.get("is_direct") or (portal == "Company/ATS" and not direct):
            direct = url
    if not links and fallback_url:
        links.append({"portal": portal_from_url(fallback_url), "url": fallback_url, "source": source})
    apply_url = direct or (links[0]["url"] if links else fallback_url)
    primary = "Company/ATS" if direct else (links[0]["portal"] if links else "Company/ATS")
    return links, apply_url, primary


# ------------------------------------------------------------------ JSearch (Google Jobs via RapidAPI)
class JSearch(Source):
    name, label, kind = "jsearch", "JSearch (Google Jobs)", "api"
    requires_keys = ["RAPIDAPI_KEY"]
    coverage_note = ("Google-for-Jobs results via a licensed API. This is how public LinkedIn, Naukri, Indeed and "
                     "Foundit listings reach the site without logging in to them.")

    def fetch(self, ctx):
        hours = float(ctx.prefs.get("google_jobs_every_hours") or 24)
        if not ctx.demo and not _due(self.name, hours):
            ctx.note(self.name, f"Skipped this refresh: runs once every {hours:g} hours to stay inside the free quota")
            return []
        budget = int(ctx.prefs["api_budget"].get("jsearch", 8))
        out = []
        pairs = [("demo", "demo")] if ctx.demo else _pairs_google(ctx, budget)
        for q, place in pairs:
            if ctx.demo:
                data = ctx.fixture("jsearch") or {"data": []}
            else:
                r = ctx.http.get("https://jsearch.p.rapidapi.com/search", check_robots=False, cache_ttl=12 * 3600,
                                 params={"query": f"{q} in {place}", "page": 1, "num_pages": 1, "country": "in",
                                         "date_posted": "month"},
                                 headers={"X-RapidAPI-Key": os.getenv("RAPIDAPI_KEY", ""),
                                          "X-RapidAPI-Host": "jsearch.p.rapidapi.com"})
                if r.status in (401, 403):
                    ctx.error(self.name, "Key rejected or not subscribed to JSearch on RapidAPI")
                    break
                if r.status == 429:
                    ctx.error(self.name, "Monthly quota reached")
                    break
                if not r.ok:
                    ctx.error(self.name, f"'{q} in {place}': HTTP {r.status} {r.error}")
                    continue
                data = r.json()
            for x in data.get("data", []) or []:
                loc_raw = ", ".join(p for p in (x.get("job_city"), x.get("job_state"), x.get("job_country")) if p)
                title = x.get("job_title", "")
                if not ctx.target_location(loc_raw) or not ctx.relevant_title(title):
                    continue
                links, apply_url, portal = _apply_links(x.get("apply_options"), x.get("job_apply_link", ""), self.name)
                smin = smax = None
                if (x.get("job_salary_currency") or "").upper() == "INR" and x.get("job_min_salary"):
                    mult = {"YEAR": 1, "MONTH": 12}.get((x.get("job_salary_period") or "").upper())
                    if mult:
                        smin = round(float(x["job_min_salary"]) * mult / 1e5, 1)
                        smax = round(float(x.get("job_max_salary") or x["job_min_salary"]) * mult / 1e5, 1)
                out.append(make_job(
                    source_name=self.name, native_id=str(x.get("job_id")), title=title,
                    company=x.get("employer_name", ""), location_raw=loc_raw,
                    posted_raw=x.get("job_posted_at_datetime_utc") or x.get("job_posted_at_timestamp"),
                    source_url=x.get("job_google_link") or apply_url, apply_url=apply_url,
                    description=x.get("job_description", ""), salary_min_lpa=smin, salary_max_lpa=smax,
                    salary_text=f"₹{smin}–{smax} LPA" if smin else "", source_portal=portal, links=links,
                    work_mode="remote" if x.get("job_is_remote") else None,
                    extra={"via": x.get("job_publisher", "")}, now=ctx.now))
        return out


def _pairs_google(ctx: Ctx, budget: int) -> list[tuple[str, str]]:
    places = ctx.search_places
    pairs = [(q, p) for q in ctx.role_queries for p in places]
    return pairs[:max(0, budget)]


# ------------------------------------------------------------------ SerpAPI (Google Jobs)
class SerpApi(Source):
    name, label, kind = "serpapi", "SerpAPI (Google Jobs)", "api"
    requires_keys = ["SERPAPI_KEY"]
    coverage_note = "Alternative Google-for-Jobs API. Dates are relative (\"3 days ago\"), so they are marked as such."

    def fetch(self, ctx):
        hours = float(ctx.prefs.get("google_jobs_every_hours") or 24)
        if not ctx.demo and not _due(self.name, hours):
            ctx.note(self.name, f"Skipped this refresh: runs once every {hours:g} hours to stay inside the free quota")
            return []
        budget = int(ctx.prefs["api_budget"].get("serpapi", 8))
        out = []
        pairs = [("demo", "demo")] if ctx.demo else _pairs_google(ctx, budget)
        for q, place in pairs:
            if ctx.demo:
                data = ctx.fixture("serpapi") or {"jobs_results": []}
            else:
                r = ctx.http.get("https://serpapi.com/search.json", check_robots=False, cache_ttl=12 * 3600,
                                 params={"engine": "google_jobs", "q": f"{q} {place}", "location": "India", "gl": "in",
                                         "hl": "en", "api_key": os.getenv("SERPAPI_KEY")})
                if r.status in (401, 403):
                    ctx.error(self.name, "Key rejected: check SERPAPI_KEY in .env")
                    break
                if not r.ok:
                    ctx.error(self.name, f"'{q} {place}': HTTP {r.status} {r.error}")
                    continue
                data = r.json()
            for x in data.get("jobs_results", []) or []:
                title = x.get("title", "")
                if not ctx.target_location(x.get("location", "")) or not ctx.relevant_title(title):
                    continue
                ext = x.get("detected_extensions") or {}
                links, apply_url, portal = _apply_links(x.get("apply_options"), x.get("share_link", ""), self.name)
                out.append(make_job(
                    source_name=self.name, native_id=str(x.get("job_id", ""))[:80] or apply_url, title=title,
                    company=x.get("company_name", ""), location_raw=x.get("location", ""),
                    posted_raw=ext.get("posted_at"), source_url=apply_url, apply_url=apply_url,
                    description=x.get("description", ""), salary_text=ext.get("salary", ""), source_portal=portal,
                    links=links, work_mode="remote" if ext.get("work_from_home") else None,
                    extra={"via": x.get("via", "")}, now=ctx.now))
        return out
