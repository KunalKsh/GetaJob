"""Map raw location strings to a target city and bucket (Delhi NCR or other metros)."""
from __future__ import annotations

import re

NCR = "ncr"      # job is in Delhi NCR
METRO = "metro"  # job is in another Indian city we know
REMOTE = "remote"  # remote role with no base city

# Order matters: specific names before generic ones ("new delhi" before "delhi", "delhi ncr" generic last).
CITY_PATTERNS: list[tuple[str, str, str]] = [
    ("Gurugram", NCR, r"\bgurugram\b|\bgurgaon\b|\bggn\b|\bdlf cyber ?city\b|\bmanesar\b"),
    ("Noida", NCR, r"\bgreater noida\b|\bnoida\b|\bghaziabad\b"),
    ("Bengaluru", METRO, r"\bbengaluru\b|\bbangalore\b|\bbengalore\b"),
    ("Hyderabad", METRO, r"\bhyderabad\b|\bsecunderabad\b|\bhitec city\b"),
    ("Mumbai", METRO, r"\bnavi mumbai\b|\bmumbai\b|\bthane\b|\bbombay\b|\bpowai\b"),
    ("Pune", METRO, r"\bpune\b|\bhinjewadi\b|\bhinjawadi\b"),
    ("Chennai", METRO, r"\bchennai\b|\bmadras\b"),
    ("Kolkata", METRO, r"\bkolkata\b|\bcalcutta\b"),
    ("Ahmedabad", METRO, r"\bahmedabad\b|\bgandhinagar\b|\bgift city\b"),
    ("Jaipur", METRO, r"\bjaipur\b"),
    ("Chandigarh", METRO, r"\bchandigarh\b|\bmohali\b|\bpanchkula\b|\btricity\b"),
    ("Kochi", METRO, r"\bkochi\b|\bcochin\b|\bernakulam\b"),
    ("Thiruvananthapuram", METRO, r"\bthiruvananthapuram\b|\btrivandrum\b|\btechnopark\b"),
    ("Coimbatore", METRO, r"\bcoimbatore\b"),
    ("Indore", METRO, r"\bindore\b"),
    ("Lucknow", METRO, r"\blucknow\b"),
    ("Bhubaneswar", METRO, r"\bbhubaneswar\b|\bbhubaneshwar\b"),
    ("Nagpur", METRO, r"\bnagpur\b"),
    ("Vadodara", METRO, r"\bvadodara\b|\bbaroda\b"),
    ("Surat", METRO, r"\bsurat\b"),
    ("Visakhapatnam", METRO, r"\bvisakhapatnam\b|\bvizag\b"),
    ("Mysuru", METRO, r"\bmysuru\b|\bmysore\b"),
    ("Delhi", NCR, r"\bnew delhi\b|\bdelhi\b(?!\s*ncr)|\bfaridabad\b"),
    ("Delhi NCR", NCR, r"\bdelhi[\s-]*ncr\b|\bncr\b|\bnational capital region\b"),
]
_COMPILED = [(c, b, re.compile(p, re.I)) for c, b, p in CITY_PATTERNS]
NCR_CITIES = ["Gurugram", "Delhi", "Noida"]
ALL_CITIES = NCR_CITIES + [c for c, b, _ in CITY_PATTERNS if b == METRO] + ["Remote"]
MAJOR_METROS = ["Bengaluru", "Hyderabad", "Mumbai", "Pune", "Chennai"]
BUCKET_LABEL = {NCR: "Delhi NCR (Gurugram, Delhi, Noida)", METRO: "Bengaluru, Hyderabad, Mumbai, Pune"}


def region_label(cities: list[str]) -> str:
    """A short name for a list of cities: "Delhi NCR", "Bengaluru", "Bengaluru, Pune +2"."""
    cs = list(cities or [])
    if not cs:
        return "No cities chosen"
    ncr = [c for c in cs if c in NCR_CITIES]
    rest = [c for c in cs if c not in NCR_CITIES]
    names = (["Delhi NCR"] if len(ncr) == len(NCR_CITIES) else ncr) + rest
    return ", ".join(names[:3]) + (f" +{len(names) - 3}" if len(names) > 3 else "")


def expand(cities: list[str]) -> set[str]:
    """Cities a list covers, counting a generic "Delhi NCR" posting as every NCR city."""
    out = set(cities or [])
    if out & set(NCR_CITIES):
        out.add("Delhi NCR")
    return out


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
    if primary is None and remote:
        return {"city": "Remote", "bucket": REMOTE, "cities": ["Remote"], "remote": True}
    return {"city": primary, "bucket": bucket_of(primary), "cities": cities, "remote": remote}
