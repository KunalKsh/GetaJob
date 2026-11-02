"""Polite HTTP: robots.txt checks, ≤1 request/second per host, retries, timeouts and a disk cache."""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from .config import CACHE_DIR, USER_AGENT

log = logging.getLogger("jobfinder.http")


class RobotsDisallowed(Exception):
    pass


@dataclass
class Resp:
    status: int
    text: str
    url: str
    redirects: list[str] = field(default_factory=list)
    error: str = ""
    from_cache: bool = False

    def json(self):
        return json.loads(self.text)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class Http:
    def __init__(self, min_interval: float = 1.0, timeout: float = 20.0, cache: bool = True):
        self.min_interval = min_interval
        self.cache = cache
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-IN,en;q=0.9"},
            timeout=timeout, follow_redirects=True, max_redirects=8)
        self._host_locks: dict[str, threading.Lock] = {}
        self._last: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}
        self._intervals: dict[str, float] = {"api.adzuna.com": 2.6}  # Adzuna allows 25 calls/minute
        self._meta = threading.Lock()
        self.request_count = 0

    def close(self):
        self._client.close()

    # -------------------------------------------------------------- rate limit
    def _wait(self, host: str):
        with self._meta:
            lock = self._host_locks.setdefault(host, threading.Lock())
        with lock:
            interval = max(self.min_interval, self._intervals.get(host, 0))
            wait = self._last.get(host, 0) + interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last[host] = time.monotonic()
        with self._meta:
            self.request_count += 1

    # -------------------------------------------------------------- robots.txt
    def robots_allowed(self, url: str) -> bool:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        with self._meta:
            known = base in self._robots
            rp = self._robots.get(base)
        if not known:
            rp = RobotFileParser()
            try:
                self._wait(p.netloc)
                r = self._client.get(base + "/robots.txt", timeout=10)
                if 400 <= r.status_code < 500:
                    rp = None  # RFC 9309: robots.txt unavailable (any 4xx) means no crawl restrictions
                elif r.status_code >= 500:
                    rp.parse(["User-agent: *", "Disallow: /"])  # server error: assume everything is off limits
                else:
                    rp.parse(r.text.splitlines())
            except httpx.HTTPError:
                rp = None  # unreachable host: the real request will fail and be reported
            with self._meta:
                self._robots[base] = rp
        if rp is None:
            return True
        return rp.can_fetch(USER_AGENT, url) and rp.can_fetch("*", url)

    # -------------------------------------------------------------- cache
    def _cache_path(self, key: str):
        return CACHE_DIR / (hashlib.sha1(key.encode()).hexdigest() + ".json")

    def _cache_get(self, key: str, ttl: float) -> Resp | None:
        if not (self.cache and ttl > 0):
            return None
        path = self._cache_path(key)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - data["ts"] <= ttl:
                return Resp(data["status"], data["text"], data["url"], from_cache=True)
        except (OSError, ValueError, KeyError):
            return None
        return None

    def _cache_put(self, key: str, resp: Resp, ttl: float):
        if not (self.cache and ttl > 0 and resp.ok):
            return
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            self._cache_path(key).write_text(json.dumps(
                {"ts": time.time(), "status": resp.status, "text": resp.text, "url": resp.url}), encoding="utf-8")
        except OSError:
            pass

    # -------------------------------------------------------------- requests
    def request(self, method: str, url: str, *, params=None, json_body=None, headers=None,
                check_robots: bool = True, cache_ttl: float = 0, retries: int = 2,
                timeout: float | None = None) -> Resp:
        if check_robots and not self.robots_allowed(url):
            raise RobotsDisallowed(f"robots.txt disallows {urlparse(url).netloc}{urlparse(url).path}")
        key = json.dumps([method, url, params, json_body], sort_keys=True, default=str)
        cached = self._cache_get(key, cache_ttl)
        if cached:
            return cached
        host = urlparse(url).netloc
        delay = 2.0
        last_err = ""
        for attempt in range(retries + 1):
            self._wait(host)
            try:
                r = self._client.request(method, url, params=params, json=json_body, headers=headers,
                                         timeout=timeout or httpx.USE_CLIENT_DEFAULT)
                resp = Resp(r.status_code, r.text, str(r.url), [str(h.url) for h in r.history])
                if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                    ra = r.headers.get("retry-after", "")
                    time.sleep(min(float(ra), 30) if ra.isdigit() else delay)
                    delay *= 2
                    continue
                self._cache_put(key, resp, cache_ttl)
                return resp
            except httpx.TooManyRedirects:
                return Resp(0, "", url, error="redirect loop")
            except httpx.ConnectError as exc:
                last_err = "DNS or connection failure" if "Name or service" in str(exc) or "getaddrinfo" in str(exc) \
                    else f"connection failed: {exc}"
            except httpx.TimeoutException:
                last_err = "timed out"
            except httpx.HTTPError as exc:
                last_err = str(exc) or exc.__class__.__name__
            if attempt < retries:
                time.sleep(delay)
                delay *= 2
        return Resp(0, "", url, error=last_err)

    def get(self, url: str, **kw) -> Resp:
        return self.request("GET", url, **kw)

    def post(self, url: str, json_body=None, **kw) -> Resp:
        return self.request("POST", url, json_body=json_body, **kw)
