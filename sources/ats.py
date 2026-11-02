"""Company career boards through their public job-board JSON (no login, no scraping of HTML)."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from rapidfuzz import fuzz

from core.dates import age_days, parse_posted
from core.dedup import norm_title
from core.http import RobotsDisallowed
from core.normalize import make_job, strip_html
from core.verify import EXPIRED, NEEDS_REVIEW, VERIFIED, result

from .base import Ctx, Source, demo_on, employers

ATS_NOTE = "Public job-board JSON that the company's own careers page uses. No login involved."


def _title_matches(stored: str, live: str) -> bool:
    return fuzz.token_sort_ratio(norm_title(stored), norm_title(live)) >= 85


class _Board(Source):
    kind = "ats"
    portal = "Company/ATS"
    coverage_note = ATS_NOTE
    key = ""

    def companies(self, demo: bool = False) -> list[dict]:
        return employers(demo).get(self.key) or []

    def configured(self) -> bool:
        return bool(self.companies()) or bool(self.companies(demo=True) and demo_on())

    def fetch(self, ctx: Ctx) -> list[dict]:
        jobs: list[dict] = []
        lock = threading.Lock()

        def one(emp):
            try:
                found = self.fetch_company(ctx, emp)
                with lock:
                    jobs.extend(found)
            except RobotsDisallowed as exc:
                ctx.error(self.name, f"{emp.get('name')}: {exc}")
            except Exception as exc:  # one bad board must not stop the rest
                ctx.error(self.name, f"{emp.get('name')}: {exc.__class__.__name__}: {str(exc)[:120]}")

        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            list(ex.map(one, self.companies(ctx.demo)))
        return jobs

    workers = 1  # one host per ATS: requests are serialized by the per-host rate limit anyway

    def fetch_company(self, ctx: Ctx, emp: dict) -> list[dict]:
        raise NotImplementedError


# ------------------------------------------------------------------ Greenhouse
class Greenhouse(_Board):
    name, label, key = "greenhouse", "Greenhouse boards", "greenhouse"
    API = "https://boards-api.greenhouse.io/v1/boards"

    def fetch_company(self, ctx, emp):
        token = emp["token"]
        if ctx.demo:
            data = (ctx.fixture("greenhouse") or {}).get(token) or {"jobs": []}
        else:
            r = ctx.http.get(f"{self.API}/{token}/jobs", params={"content": "true"}, cache_ttl=3 * 3600)
            if r.status == 404:
                raise ValueError("board not found (check the token in employers.yaml)")
            if not r.ok:
                raise ValueError(f"HTTP {r.status} {r.error}")
            data = r.json()
        out = []
        for x in data.get("jobs", []):
            loc = (x.get("location") or {}).get("name", "")
            offices = "; ".join(o.get("name", "") for o in x.get("offices") or [])
            loc_all = "; ".join(p for p in (loc, offices) if p)
            if not ctx.target_location(loc_all) or not ctx.relevant_title(x.get("title", "")):
                continue
            out.append(make_job(
                source_name=self.name, native_id=f"{token}:{x['id']}", title=x.get("title", ""),
                company=emp.get("name") or token, location_raw=loc_all, posted_raw=x.get("first_published"),
                source_url=x.get("absolute_url", ""), description=x.get("content", ""),
                employer_industry=emp.get("industry"), extra={"token": token, "ats_id": x["id"]}, now=ctx.now))
        return out

    def verify(self, job, ctx):
        ex = job.get("extra") or {}
        if not ex.get("token"):
            return None
        if ctx.demo:
            return None
        r = ctx.http.get(f"{self.API}/{ex['token']}/jobs/{ex['ats_id']}", retries=1)
        if r.status == 404:
            return result(EXPIRED, "Removed from the company's job board")
        if not r.ok:
            return result(NEEDS_REVIEW, f"Board check failed (HTTP {r.status} {r.error})")
        live = r.json()
        if not _title_matches(job["title"], live.get("title", "")):
            return result(NEEDS_REVIEW, f"Title on the board is now \"{live.get('title')}\"")
        return result(VERIFIED, "Live on the company's job board")


# ------------------------------------------------------------------ Lever
class Lever(_Board):
    name, label, key = "lever", "Lever boards", "lever"
    API = "https://api.lever.co/v0/postings"

    def fetch_company(self, ctx, emp):
        co = emp["company"]
        if ctx.demo:
            data = (ctx.fixture("lever") or {}).get(co) or []
        else:
            r = ctx.http.get(f"{self.API}/{co}", params={"mode": "json"}, cache_ttl=3 * 3600)
            if r.status == 404:
                raise ValueError("board not found (check the name in employers.yaml)")
            if not r.ok:
                raise ValueError(f"HTTP {r.status} {r.error}")
            data = r.json()
        out = []
        for x in data if isinstance(data, list) else []:
            cat = x.get("categories") or {}
            loc_all = "; ".join([cat.get("location") or ""] + list(cat.get("allLocations") or []))
            if not ctx.target_location(loc_all) or not ctx.relevant_title(x.get("text", "")):
                continue
            desc = x.get("descriptionPlain") or strip_html(x.get("description"))
            for lst in x.get("lists") or []:
                desc += "\n" + (lst.get("text") or "") + "\n" + strip_html(lst.get("content"))
            desc += "\n" + (x.get("additionalPlain") or "")
            out.append(make_job(
                source_name=self.name, native_id=f"{co}:{x['id']}", title=x.get("text", ""),
                company=emp.get("name") or co, location_raw=loc_all, posted_raw=x.get("createdAt"),
                source_url=x.get("hostedUrl", ""), apply_url=x.get("applyUrl"), description=desc,
                work_mode={"remote": "remote", "hybrid": "hybrid", "onsite": "onsite"}.get(x.get("workplaceType") or ""),
                employer_industry=emp.get("industry"), extra={"company": co, "ats_id": x["id"]}, now=ctx.now))
        return out

    def verify(self, job, ctx):
        ex = job.get("extra") or {}
        if not ex.get("company") or ctx.demo:
            return None
        r = ctx.http.get(f"{self.API}/{ex['company']}/{ex['ats_id']}", retries=1)
        if r.status == 404:
            return result(EXPIRED, "Removed from the company's job board")
        if not r.ok:
            return result(NEEDS_REVIEW, f"Board check failed (HTTP {r.status} {r.error})")
        if not _title_matches(job["title"], r.json().get("text", "")):
            return result(NEEDS_REVIEW, "Title on the board has changed")
        return result(VERIFIED, "Live on the company's job board")


# ------------------------------------------------------------------ Ashby
class Ashby(_Board):
    name, label, key = "ashby", "Ashby boards", "ashby"
    API = "https://api.ashbyhq.com/posting-api/job-board"

    def _board(self, ctx, org, ttl):
        if ctx.demo:
            return (ctx.fixture("ashby") or {}).get(org) or {"jobs": []}
        r = ctx.http.get(f"{self.API}/{org}", params={"includeCompensation": "true"}, cache_ttl=ttl)
        if r.status == 404:
            raise ValueError("board not found (check the name in employers.yaml)")
        if not r.ok:
            raise ValueError(f"HTTP {r.status} {r.error}")
        return r.json()

    def fetch_company(self, ctx, emp):
        org = emp["org"]
        out = []
        for x in self._board(ctx, org, 3 * 3600).get("jobs", []):
            if x.get("isListed") is False:
                continue
            locs = [x.get("location") or ""] + [s.get("location", "") for s in x.get("secondaryLocations") or []]
            loc_all = "; ".join(l for l in locs if l)
            if not ctx.target_location(loc_all) or not ctx.relevant_title(x.get("title", "")):
                continue
            comp = (x.get("compensation") or {}).get("compensationTierSummary") or ""
            out.append(make_job(
                source_name=self.name, native_id=f"{org}:{x['id']}", title=x.get("title", ""),
                company=emp.get("name") or org, location_raw=loc_all, posted_raw=x.get("publishedAt"),
                source_url=x.get("jobUrl", ""), apply_url=x.get("applyUrl"),
                description=x.get("descriptionPlain") or x.get("descriptionHtml", ""), salary_text=comp,
                employer_industry=emp.get("industry"), extra={"org": org, "ats_id": x["id"]}, now=ctx.now))
        return out

    def verify(self, job, ctx):
        ex = job.get("extra") or {}
        if not ex.get("org") or ctx.demo:
            return None
        try:
            ids = {x.get("id") for x in self._board(ctx, ex["org"], 600).get("jobs", [])}
        except Exception as exc:
            return result(NEEDS_REVIEW, f"Board check failed ({exc})")
        if ex["ats_id"] not in ids:
            return result(EXPIRED, "No longer on the company's job board")
        return result(VERIFIED, "Live on the company's job board")


# ------------------------------------------------------------------ Workable
class Workable(_Board):
    name, label, key = "workable", "Workable boards", "workable"
    API = "https://apply.workable.com/api/v1/widget/accounts"

    def _board(self, ctx, acct, ttl):
        if ctx.demo:
            return (ctx.fixture("workable") or {}).get(acct) or {"jobs": []}
        r = ctx.http.get(f"{self.API}/{acct}", params={"details": "true"}, cache_ttl=ttl)
        if r.status == 404:
            raise ValueError("account not found (check the name in employers.yaml)")
        if not r.ok:
            raise ValueError(f"HTTP {r.status} {r.error}")
        return r.json()

    def fetch_company(self, ctx, emp):
        acct = emp["account"]
        out = []
        for x in self._board(ctx, acct, 3 * 3600).get("jobs", []):
            loc_all = ", ".join(p for p in (x.get("city"), x.get("state"), x.get("country")) if p)
            for l in x.get("locations") or []:
                loc_all += "; " + ", ".join(p for p in (l.get("city"), l.get("region"), l.get("country")) if p)
            if not ctx.target_location(loc_all) or not ctx.relevant_title(x.get("title", "")):
                continue
            out.append(make_job(
                source_name=self.name, native_id=f"{acct}:{x.get('shortcode')}", title=x.get("title", ""),
                company=emp.get("name") or acct, location_raw=loc_all,
                posted_raw=x.get("published_on") or x.get("created_at"), source_url=x.get("url") or x.get("shortlink", ""),
                apply_url=x.get("application_url"), description=x.get("description", ""),
                work_mode="remote" if x.get("telecommuting") else None, employer_industry=emp.get("industry"),
                extra={"account": acct, "ats_id": x.get("shortcode")}, now=ctx.now))
        return out

    def verify(self, job, ctx):
        ex = job.get("extra") or {}
        if not ex.get("account") or ctx.demo:
            return None
        try:
            codes = {x.get("shortcode") for x in self._board(ctx, ex["account"], 600).get("jobs", [])}
        except Exception as exc:
            return result(NEEDS_REVIEW, f"Board check failed ({exc})")
        if ex["ats_id"] not in codes:
            return result(EXPIRED, "No longer on the company's job board")
        return result(VERIFIED, "Live on the company's job board")


# ------------------------------------------------------------------ SmartRecruiters
class SmartRecruiters(_Board):
    name, label, key = "smartrecruiters", "SmartRecruiters boards", "smartrecruiters"
    API = "https://api.smartrecruiters.com/v1/companies"

    def fetch_company(self, ctx, emp):
        cid = emp["id"]
        if ctx.demo:
            postings = (ctx.fixture("smartrecruiters") or {}).get(cid) or []
        else:
            postings, offset = [], 0
            while offset < 500:
                r = ctx.http.get(f"{self.API}/{cid}/postings", params={"limit": 100, "offset": offset, "country": "in"},
                                 cache_ttl=3 * 3600)
                if not r.ok:
                    raise ValueError(f"HTTP {r.status} {r.error}")
                page = r.json()
                postings += page.get("content", [])
                offset += 100
                if offset >= page.get("totalFound", 0):
                    break
        out = []
        for x in postings:
            loc = x.get("location") or {}
            loc_all = ", ".join(p for p in (loc.get("city"), loc.get("region"), loc.get("country")) if p)
            if not ctx.target_location(loc_all) or not ctx.relevant_title(x.get("name", "")):
                continue
            age = age_days(parse_posted(x.get("releasedDate"), ctx.now)[0], ctx.now.date())
            if age is not None and age > int(ctx.prefs.get("max_age_days") or 30) + 5:
                continue
            desc = x.get("_detail_text", "")
            if not ctx.demo:
                d = ctx.http.get(f"{self.API}/{cid}/postings/{x['id']}", cache_ttl=12 * 3600)
                if d.ok:
                    secs = (d.json().get("jobAd") or {}).get("sections") or {}
                    desc = "\n".join(strip_html((secs.get(k) or {}).get("text")) for k in
                                     ("jobDescription", "qualifications", "additionalInformation"))
            out.append(make_job(
                source_name=self.name, native_id=f"{cid}:{x['id']}", title=x.get("name", ""),
                company=(x.get("company") or {}).get("name") or emp.get("name") or cid, location_raw=loc_all,
                posted_raw=x.get("releasedDate"), source_url=f"https://jobs.smartrecruiters.com/{cid}/{x['id']}",
                description=desc, work_mode="remote" if loc.get("remote") else None,
                employer_industry=emp.get("industry"), extra={"company": cid, "ats_id": x["id"]}, now=ctx.now))
        return out

    def verify(self, job, ctx):
        ex = job.get("extra") or {}
        if not ex.get("company") or ctx.demo:
            return None
        r = ctx.http.get(f"{self.API}/{ex['company']}/postings/{ex['ats_id']}", retries=1)
        if r.status == 404:
            return result(EXPIRED, "Removed from the company's job board")
        if not r.ok:
            return result(NEEDS_REVIEW, f"Board check failed (HTTP {r.status} {r.error})")
        if r.json().get("active") is False:
            return result(EXPIRED, "Posting marked inactive")
        return result(VERIFIED, "Live on the company's job board")


# ------------------------------------------------------------------ Workday
class Workday(_Board):
    name, label, key = "workday", "Workday career sites", "workday"
    workers = 6  # every company has its own Workday host, so these can run side by side
    TERMS = ["analyst", "analytics", "strategy"]
    CITY_TERMS = {"Gurugram": ["gurgaon", "gurugram"], "Noida": ["noida"], "Delhi": ["delhi"],
                  "Bengaluru": ["bangalore", "bengaluru"], "Hyderabad": ["hyderabad"], "Mumbai": ["mumbai"],
                  "Pune": ["pune"]}

    @staticmethod
    def base(emp):
        return f"https://{emp['tenant']}.{emp.get('host', 'wd1')}.myworkdayjobs.com"

    def _api(self, emp):
        return f"{self.base(emp)}/wday/cxs/{emp['tenant']}/{emp['site']}"

    def fetch_company(self, ctx, emp):
        max_age = int(ctx.prefs.get("max_age_days") or 30)
        if ctx.demo:
            fx = (ctx.fixture("workday") or {}).get(emp["tenant"]) or {}
            listing, details = fx.get("jobs", []), fx.get("details", {})
        else:
            listing, details, seen = [], {}, set()
            city_terms = [t for c in ctx.cities for t in self.CITY_TERMS.get(c, [c.lower()])]
            for term in self.TERMS:
                for ct in city_terms:
                    for offset in (0, 20):
                        r = ctx.http.post(f"{self._api(emp)}/jobs",
                                          {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": f"{term} {ct}"},
                                          headers={"Accept": "application/json"}, cache_ttl=3 * 3600)
                        if r.status == 404:
                            raise ValueError("career site not found (check tenant/site in employers.yaml)")
                        if not r.ok:
                            raise ValueError(f"HTTP {r.status} {r.error}")
                        page = r.json().get("jobPostings") or []
                        for p in page:
                            if p.get("externalPath") and p["externalPath"] not in seen:
                                seen.add(p["externalPath"])
                                listing.append(p)
                        if len(page) < 20:
                            break
        out = []
        for p in listing:
            title = p.get("title", "")
            if not ctx.relevant_title(title):
                continue
            rel, _ = parse_posted(p.get("postedOn"), ctx.now)
            if rel and age_days(rel, ctx.now.date()) > max_age + 2:
                continue
            loc_text = (p.get("locationsText") or "") + " " + p["externalPath"].replace("-", " ")
            if not ctx.target_location(loc_text) and "Locations" not in (p.get("locationsText") or ""):
                continue
            path = p["externalPath"]
            if ctx.demo:
                info = (details.get(path) or {}).get("jobPostingInfo")
                org = (details.get(path) or {}).get("hiringOrganization") or {}
            else:
                d = ctx.http.get(f"{self._api(emp)}{path}", headers={"Accept": "application/json"}, cache_ttl=12 * 3600)
                if not d.ok:
                    ctx.error(self.name, f"{emp['name']}: detail HTTP {d.status} for {title}")
                    continue
                dj = d.json()
                info, org = dj.get("jobPostingInfo"), dj.get("hiringOrganization") or {}
            if not info:
                continue
            loc_all = "; ".join([info.get("location") or ""] + list(info.get("additionalLocations") or []))
            if not ctx.target_location(loc_all):
                continue
            url = info.get("externalUrl") or f"{self.base(emp)}/en-US/{emp['site']}{path}"
            out.append(make_job(
                source_name=self.name, native_id=f"{emp['tenant']}:{info.get('jobReqId') or path}",
                title=info.get("title") or title, company=emp.get("name") or org.get("name", ""),
                location_raw=loc_all, posted_raw=info.get("startDate") or info.get("postedOn"),
                source_url=url, description=info.get("jobDescription", ""), employer_industry=emp.get("industry"),
                extra={"tenant": emp["tenant"], "host": emp.get("host", "wd1"), "site": emp["site"], "path": path,
                       "posted_on": info.get("postedOn") or p.get("postedOn")}, now=ctx.now))
        return out

    def verify(self, job, ctx):
        ex = job.get("extra") or {}
        if not ex.get("tenant") or ctx.demo:
            return None
        emp = {"tenant": ex["tenant"], "host": ex["host"], "site": ex["site"]}
        r = ctx.http.get(f"{self._api(emp)}{ex['path']}", headers={"Accept": "application/json"}, retries=1)
        if r.status in (404, 410):
            return result(EXPIRED, "Removed from the company's career site")
        if not r.ok:
            return result(NEEDS_REVIEW, f"Career site check failed (HTTP {r.status} {r.error})")
        info = r.json().get("jobPostingInfo") or {}
        if not info:
            return result(EXPIRED, "Posting no longer published")
        if info.get("canApply") is False or info.get("posted") is False:
            return result(EXPIRED, "Career site says applications are closed")
        if not _title_matches(job["title"], info.get("title", "")):
            return result(NEEDS_REVIEW, f"Title on the site is now \"{info.get('title')}\"")
        res = result(VERIFIED, "Live on the company's career site")
        if info.get("startDate"):
            res["page_date"], res["page_conf"] = info["startDate"], "exact"
        return res
