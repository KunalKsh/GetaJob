"""Is a job title the kind of role this person is looking for?

Each person picks job families (Software Engineering, Finance & Accounting, Nursing...) and roles.
A title counts when it closely matches one of their roles, or falls in one of their families
(by that family's title words) without naming an unrelated function. "Analyst" or "Manager"
alone is never enough.
"""
from __future__ import annotations

from rapidfuzz import fuzz

from .dedup import norm_title
from .taxonomy import BY_KEY, family_for_role, strip_level, title_in_family

# kept for callers that want the analytics patterns directly
CORE = None


def role_titles(roles: list) -> list[str]:
    return [r["title"] if isinstance(r, dict) else r for r in roles or []]


def families_from(roles: list, families: list[str] | None = None) -> list[str]:
    """The person's chosen families, or (for older profiles) the families their roles belong to."""
    if families:
        return [f for f in families if f in BY_KEY]
    out = []
    for t in role_titles(roles):
        k = family_for_role(t)
        if k and k not in out:
            out.append(k)
    return out


def matches_role(title: str, roles: list, threshold: int = 85) -> bool:
    nt = norm_title(strip_level(title))
    if not nt:
        return False
    for r in role_titles(roles):
        for part in r.split("/"):
            nr = norm_title(strip_level(part))
            if nr and (fuzz.token_sort_ratio(nt, nr) >= threshold or (len(nr.split()) >= 2 and nr in nt)):
                return True
    return False


def is_relevant(title: str, roles: list, families: list[str] | None = None) -> bool:
    if not title:
        return False
    if not roles and not families:
        return True  # nothing chosen yet: don't hide anything
    fams = families_from(roles, families)
    for k in fams:
        if title_in_family(title, BY_KEY[k]):
            return True
    # an exact-ish role match counts even outside the family patterns (custom roles),
    # unless one of the person's families explicitly rules that kind of title out
    if matches_role(title, roles):
        from .taxonomy import _rx
        return not any((ex := _rx(BY_KEY[k].get("exclude_rx", ""))) and ex.search(title) for k in fams)
    return False


def relevant_any(title: str, specs: list[tuple[list, list]]) -> bool:
    """Relevant to at least one person (used while collecting, before per-person ranking)."""
    return any(is_relevant(title, roles, fams) for roles, fams in specs)
