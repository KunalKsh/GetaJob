"""Common interface for every source adapter, plus the shared search context."""
from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import yaml
from rapidfuzz import fuzz

from core.config import EMPLOYERS_PATH, FIXTURES_DIR, IST
from core.dedup import norm_title
from core.http import Http
from core.locations import NCR_CITIES, expand, map_location
from core.relevance import is_relevant, relevant_any

def employers(demo: bool = False) -> dict:
    """Company list. The admin can edit it on the site (kept in the database); otherwise config/employers.yaml.
    Demo mode uses fictional sample companies from fixtures/employers_demo.yaml."""
    if demo:
        text = (FIXTURES_DIR / "employers_demo.yaml").read_text(encoding="utf-8")
    else:
        text = employers_text()
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        data = {}
    if not demo:
        from .discover import discovered_entries
        from core.dedup import norm_company
        for ats, rows in discovered_entries().items():
            have = {norm_company(e.get("name", "")) for e in data.get(ats) or []}
            data[ats] = list(data.get(ats) or []) + [r for r in rows if norm_company(r["name"]) not in have]
    return data


def employers_text() -> str:
    try:
        from core import db
        saved = db.get_settings().get("employers_yaml")
        if saved:
            return saved
    except Exception:
        pass
    try:
        return EMPLOYERS_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


def demo_on() -> bool:
    from core import db
    try:
        return bool(db.get_settings().get("demo_mode"))
    except Exception:
        return False


def load_fixture(name: str, now: datetime | None = None):
    """Fixtures use {{days_ago:N}}, {{days_ago_ms:N}}, {{date_ago:N}} and {{rel_days:N}} so demo data stays fresh."""
    now = now or datetime.now(IST)
    path = FIXTURES_DIR / f"{name}.json"
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8")

    def sub(m):
        kind, n = m.group(1), int(m.group(2))
        t = now - timedelta(days=n)
        if kind == "days_ago":
            return t.isoformat(timespec="seconds")
        if kind == "days_ago_ms":
            return str(int(t.timestamp() * 1000))
        if kind == "date_ago":
            return t.date().isoformat()
        if kind == "rel_days":
            return "Posted Today" if n == 0 else ("Posted Yesterday" if n == 1 else f"Posted {n} Days Ago")
        return m.group(0)

    raw = re.sub(r"\{\{(days_ago_ms|days_ago|date_ago|rel_days):(\d+)\}\}", sub, raw)
    return json.loads(raw)


@dataclass
class Ctx:
    prefs: dict
    http: Http
    demo: bool = False
    now: datetime = field(default_factory=lambda: datetime.now(IST))
    errors: dict = field(default_factory=dict)
    notes: dict = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def roles(self) -> list[dict]:
        out = []
        for r in self.prefs.get("roles") or []:
            if isinstance(r, str):
                r = {"title": r, "queries": [r.lower()]}
            out.append(r)
        return out

    @property
    def role_queries(self) -> list[str]:
        """One search phrase per confirmed role, in the user's priority order."""
        seen, out = set(), []
        for r in self.roles:
            for q in (r.get("queries") or [r["title"].lower()])[:1]:
                q = re.sub(r"\s*/\s*.*$", "", q).strip().lower()
                if q and q not in seen:
                    seen.add(q)
                    out.append(q)
        return out

    @property
    def cities(self) -> list[str]:
        p = self.prefs
        if p.get("cities") is not None:
            return list(p["cities"])
        out = list(p.get("primary_cities") or p.get("ncr_cities") or []) + \
            list(p.get("secondary_cities") or p.get("metro_cities") or [])
        return list(dict.fromkeys(out))

    @property
    def search_cities(self) -> list[str]:
        """Cities to send to job-search APIs (remote roles are found through every city's results)."""
        return [c for c in self.cities if c != "Remote"]

    @property
    def search_places(self) -> list[str]:
        """Like search_cities, but the NCR cities collapse to one "Delhi NCR" search."""
        cs = self.search_cities
        return (["Delhi NCR"] if set(cs) & set(NCR_CITIES) else []) + [c for c in cs if c not in NCR_CITIES]

    def error(self, source: str, msg: str):
        with self._lock:
            self.errors.setdefault(source, [])
            if msg not in self.errors[source] and len(self.errors[source]) < 12:
                self.errors[source].append(msg)

    def note(self, source: str, msg: str):
        with self._lock:
            self.notes[source] = msg

    def relevant_title(self, title: str) -> bool:
        specs = self.prefs.get("relevance_specs")
        if specs:
            return relevant_any(title, specs)
        return is_relevant(title, self.roles, self.prefs.get("families"))

    def target_location(self, raw: str) -> bool:
        loc = map_location(raw or "")
        allowed = expand(self.cities)
        if "Remote" in allowed and loc["remote"]:
            return True
        return any(c in allowed for c in loc["cities"])

    def fixture(self, name: str):
        return load_fixture(name, self.now)


class Source:
    name = "base"
    label = "Base"
    portal = "Company/ATS"
    kind = "ats"  # ats | api | alerts | manual
    requires_keys: list[str] = []
    coverage_note = ""

    def configured(self) -> bool:
        if self.kind == "api" and demo_on():
            return True  # demo mode reads sample responses, no key needed
        return all(os.getenv(k) for k in self.requires_keys)

    def fetch(self, ctx: Ctx) -> list[dict]:
        raise NotImplementedError

    def verify(self, job: dict, ctx: Ctx) -> dict | None:
        """Adapter-specific check (e.g. the ATS's own JSON). None means use the generic page check."""
        return None
