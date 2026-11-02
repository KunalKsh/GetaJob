"""Map raw location strings to a target city and bucket (Delhi NCR or other metros)."""
from __future__ import annotations

import re

NCR = "ncr"
METRO = "metro"

# Order matters: specific names before generic ones ("new delhi" before "delhi", "delhi ncr" generic last).
CITY_PATTERNS: list[tuple[str, str, str]] = [
    ("Gurugram", NCR, r"\bgurugram\b|\bgurgaon\b|\bggn\b|\bdlf cyber ?city\b|\bmanesar\b"),
    ("Noida", NCR, r"\bgreater noida\b|\bnoida\b|\bghaziabad\b"),
    ("Bengaluru", METRO, r"\bbengaluru\b|\bbangalore\b|\bbengalore\b"),
    ("Hyderabad", METRO, r"\bhyderabad\b|\bsecunderabad\b|\bhitec city\b"),
    ("Mumbai", METRO, r"\bnavi mumbai\b|\bmumbai\b|\bthane\b|\bbombay\b|\bpowai\b"),
    ("Pune", METRO, r"\bpune\b|\bhinjewadi\b|\bhinjawadi\b"),
    ("Delhi", NCR, r"\bnew delhi\b|\bdelhi\b(?!\s*ncr)|\bfaridabad\b"),
    ("Delhi NCR", NCR, r"\bdelhi[\s-]*ncr\b|\bncr\b|\bnational capital region\b"),
]
_COMPILED = [(c, b, re.compile(p, re.I)) for c, b, p in CITY_PATTERNS]
BUCKET_LABEL = {NCR: "Delhi NCR (Gurugram, Delhi, Noida)", METRO: "Bengaluru, Hyderabad, Mumbai, Pune"}
REMOTE_RE = re.compile(r"\bremote\b|\bwork from home\b|\bwfh\b|\banywhere in india\b", re.I)


def find_cities(raw: str) -> list[str]:
    if not raw:
        return []
    found = []
    for city, _, pat in _COMPILED:
        if pat.search(raw) and city not in found:
            found.append(city)
    # "Gurugram, Delhi NCR" is one city, not two
    if "Delhi NCR" in found and any(c in found for c in ("Gurugram", "Noida", "Delhi")):
        found.remove("Delhi NCR")
    return found


def bucket_of(city: str | None) -> str | None:
    for c, b, _ in _COMPILED:
        if c == city:
            return b
    return None


def map_location(raw: str, prefer: tuple[str, ...] = ("Gurugram", "Noida", "Delhi", "Delhi NCR")) -> dict:
    """Primary city (NCR preferred when a posting lists several), bucket, all cities, remote flag.

    Remote roles count toward a bucket only when the posting names a base city.
    """
    cities = find_cities(raw or "")
    remote = bool(REMOTE_RE.search(raw or ""))
    primary = None
    for p in prefer:
        if p in cities:
            primary = p
            break
    if primary is None and cities:
        primary = cities[0]
    return {"city": primary, "bucket": bucket_of(primary), "cities": cities, "remote": remote}
