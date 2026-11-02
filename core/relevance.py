"""Is a job title the kind of analytics role you target?

"Analyst" alone isn't enough: Indian job boards are full of accounting, compliance, HR-ops and
lease-abstraction roles titled "Analyst". A title counts when it names analytics work
(data, insights, BI, reporting, product, strategy...) or closely matches a confirmed role,
and doesn't name an unrelated function.
"""
from __future__ import annotations

import re

from rapidfuzz import fuzz

from .dedup import norm_title

CORE = re.compile(
    r"\bdata\b|analytics|analytical|insight|business intelligence|\bbi\b|reporting|\bmis\b|\bmi\b|"
    r"business analyst|product analyst|strateg|decision scien|data scien|growth|pricing|"
    r"market(?:ing)? (?:analyst|analytics|intelligence|research)|revenue (?:analyst|operations)|"
    r"business operations|bizops|metrics|dashboard|visuali[sz]ation|research analyst|"
    r"(?:analytics|strategy|management|business) consultant", re.I)

OFF_TARGET = re.compile(
    # engineering, IT and support
    r"engineer|developer|architect|devops|programmer|sdet|\bqa\b|tester|testing|quality assurance|it quality|"
    r"quality tech|security analyst|\bsoc\b|cyber|penetration|network|infrastructure|service desk|"
    r"systems integration|professional services|managed services|deep learning|"
    # sales, support, ops
    r"sales executive|telecaller|tele-?sales|customer (?:care|support|service)|voice|call cent|"
    r"sales compensation|training|"
    # finance & accounting operations
    r"account(?:ing|ant)|accounts payable|accounts receivable|\bap\b|\bar\b|r2r|p2p|o2c|i2c|controllership|"
    r"treasury|\bcash\b|fund accounting|\btax\b|audit|reconciliation analyst|financial operations|"
    r"finance & accounting|billing|credit control|securities|derivatives|settlement|"
    r"credit analyst|underwriting|model validation|valuation|"
    # legal, risk-compliance, HR, procurement, real estate
    r"legal|lawyer|paralegal|compliance|\bkyc\b|\baml\b|financial crime|\bhr\b|human resources|"
    r"people operations|payroll|recruit|talent acquisition|vendor|procurement|sourcing|"
    r"abstraction|lease|portfolio analyst|\bgst\b|indirect tax|investor relations|facilities|property|"
    r"fincrime|financial crime|fraud reporting|\bsar\b|enforcement|lms admin|"
    # very senior grades (Indian titles)
    r"general manager|\bgm\b|\bdgm\b|\bsvp\b|"
    # creative, project management, other
    r"creative|graphic|designer|motion|content writer|copywriter|project manager|program manager|scrum|"
    r"workday|servicenow|salesforce (?:developer|admin)|sap (?:abap|basis|fico)|"
    r"nurse|teacher|driver|technician|mechanic|travel consultant|claims (?:associate|processor)", re.I)


def is_relevant(title: str, roles: list) -> bool:
    if not title or OFF_TARGET.search(title):
        return False
    if CORE.search(title):
        return True
    nt = norm_title(title)
    names = [r["title"] if isinstance(r, dict) else r for r in roles or []]
    return any(fuzz.token_sort_ratio(nt, norm_title(n)) >= 85 for n in names)
