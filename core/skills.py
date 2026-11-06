"""Skill and industry vocabulary used for resume parsing, JD parsing and fit scoring."""
from __future__ import annotations

import re

# canonical skill -> regex aliases (case-insensitive)
SKILLS: dict[str, list[str]] = {
    "Python": [r"\bpython\b"],
    "SQL": [r"\bsql\b", r"\bt-?sql\b", r"\bpl/sql\b", r"\bmysql\b", r"\bpostgres(?:ql)?\b", r"\bsql server\b"],
    "R": [r"(?:python|sql|sas)\s*(?:/|,|or|and|&)\s*r\b(?![-&'’])", r"\br\s*(?:/|,|or|and|&)\s*(?:python|sql|sas)\b",
          r"\br programming\b", r"\brstudio\b", r"\bin r\b(?=[\s,.)])"],
    "SAS": [r"\bsas\b"],
    "Excel": [r"\bexcel\b", r"\bpivot tables?\b", r"\bvlookup\b", r"\bxlookup\b", r"\bpower query\b", r"\bspreadsheets?\b"],
    "VBA": [r"\bvba\b", r"\bmacros?\b"],
    "Power BI": [r"\bpower ?bi\b", r"\bpowerbi\b"],
    "DAX": [r"\bdax\b"],
    "Tableau": [r"\btableau\b"],
    "Looker Studio": [r"\blooker studio\b", r"\bdata studio\b"],
    "Looker": [r"\blooker\b(?! studio)", r"\blookml\b"],
    "Qlik": [r"\bqlik(?:view| sense)?\b"],
    "Google Apps Script": [r"\bapps script\b", r"\bappscript\b"],
    "Pandas": [r"\bpandas\b"],
    "NumPy": [r"\bnumpy\b"],
    "Scikit-Learn": [r"\bscikit[- ]?learn\b", r"\bsklearn\b"],
    "spaCy": [r"\bspacy\b"],
    "Machine Learning": [r"\bmachine learning\b", r"\bml models?\b", r"\bpredictive model", r"\brandom forest\b",
                         r"\bgradient boosting\b", r"\bxgboost\b", r"\blogistic regression\b"],
    "NLP": [r"\bnlp\b", r"\bnatural language processing\b", r"\btext mining\b", r"\bsentiment analysis\b"],
    "GenAI / LLMs": [r"\bgen ?ai\b", r"\bgenerative ai\b", r"\bllms?\b", r"\blarge language models?\b",
                     r"\bprompt engineering\b", r"\bgemini\b", r"\bgpt\b", r"\bai agents?\b", r"\bllm agents?\b"],
    "Statistics": [r"\bstatistic(?:s|al)\b", r"\bhypothesis testing\b", r"\bsignificance test", r"\bregression analysis\b",
                   r"\bprobability\b"],
    "A/B Testing": [r"\ba/?b test", r"\bab test", r"\bexperimentation\b", r"\bexperiments?\b", r"\bsplit test",
                    r"\btest[- ]and[- ]learn\b"],
    "Regression": [r"\bregression\b"],
    "Segmentation / Clustering": [r"\bsegmentation\b", r"\bclustering\b", r"\bk-?means\b", r"\bcohorts?\b"],
    "Forecasting": [r"\bforecast(?:ing|s)?\b", r"\btime[- ]series\b", r"\barima\b"],
    "ETL": [r"\betl\b", r"\belt\b", r"\bdata pipelines?\b", r"\bdata ingestion\b"],
    "Data Modeling": [r"\bdata model(?:l)?ing\b", r"\bstar schema\b", r"\bdimensional model"],
    "Data Validation / Quality": [r"\bdata (?:validation|quality|cleaning|governance)\b", r"\bdedup(?:lication)?\b",
                                  r"\breconciliation\b"],
    "Data Visualization": [r"\bdata visuali[sz]ation\b", r"\bvisuali[sz]ations?\b", r"\bmatplotlib\b", r"\bseaborn\b",
                           r"\bplotly\b"],
    "Dashboards": [r"\bdashboard(?:s|ing)?\b"],
    "MIS Reporting": [r"\bmis\b", r"\breporting\b", r"\breports?\b"],
    "KPI Design": [r"\bkpis?\b", r"\bmetrics?\b", r"\bnorth star\b"],
    "Funnel Analysis": [r"\bfunnels?\b", r"\bconversion (?:rate|analysis|optimi[sz]ation)\b"],
    "Product Analytics": [r"\bproduct analytics\b", r"\buser behaviou?r\b", r"\bfeature adoption\b", r"\bretention\b",
                          r"\bengagement metrics\b"],
    "Stakeholder Management": [r"\bstakeholders?\b", r"\bcross[- ]functional\b"],
    "Requirement Gathering": [r"\brequirements? gathering\b", r"\bbrds?\b", r"\bfrds?\b", r"\buser stories\b",
                              r"\bbusiness requirements?\b"],
    "Problem Structuring": [r"\bproblem[- ]solving\b", r"\bproblem structuring\b", r"\bhypothesis[- ]driven\b",
                            r"\bstructured thinking\b"],
    "Root Cause Analysis": [r"\broot[- ]cause\b", r"\brca\b", r"\bdeep[- ]dives?\b"],
    "Data Storytelling": [r"\bstorytelling\b", r"\bpresentations?\b", r"\bexecutive (?:summaries|presentations)\b",
                          r"\bcommunicat(?:e|ion) (?:insights|findings)\b"],
    "Process Optimization": [r"\bprocess (?:improvement|optimi[sz]ation)\b", r"\blean\b", r"\bsix sigma\b"],
    "Automation": [r"\bautomat(?:e|ed|ion|ing)\b"],
    "FastAPI": [r"\bfastapi\b"],
    "MongoDB": [r"\bmongo(?:db)?\b"],
    "Google Analytics": [r"\bgoogle analytics\b", r"\bga4\b"],
    "Mixpanel / Amplitude": [r"\bmixpanel\b", r"\bamplitude\b", r"\bclevertap\b", r"\bmoengage\b"],
    "BigQuery": [r"\bbigquery\b"],
    "Snowflake": [r"\bsnowflake\b"],
    "Redshift": [r"\bredshift\b"],
    "Databricks": [r"\bdatabricks\b"],
    "Spark": [r"\bpyspark\b", r"\bspark\b"],
    "Hive / Hadoop": [r"\bhive\b", r"\bhadoop\b"],
    "Airflow": [r"\bairflow\b"],
    "dbt": [r"\bdbt\b"],
    "Cloud (AWS/Azure/GCP)": [r"\baws\b", r"\bazure\b", r"\bgcp\b", r"\bgoogle cloud\b"],
    "Git": [r"\bgit(?:hub|lab)?\b"],
    "JIRA / Agile": [r"\bjira\b", r"\bagile\b", r"\bscrum\b"],
    "Salesforce": [r"\bsalesforce\b"],
    "SAP": [r"\bsap\b"],
    "Financial Modeling": [r"\bfinancial model", r"\bvaluation\b", r"\bp&l\b", r"\bunit economics\b"],
    "Pricing": [r"\bpricing\b"],
    "Marketing Analytics": [r"\bmarketing analytics\b", r"\bcampaigns?\b", r"\broi\b", r"\bmarketing mix\b",
                            r"\bperformance marketing\b", r"\bcac\b"],
    "Risk Analytics": [r"\brisk analytics\b", r"\bcredit risk\b", r"\bfraud\b", r"\bcollections? analytics\b",
                       r"\bunderwriting\b"],
    "Growth Strategy": [r"\bgrowth strategy\b", r"\bgo[- ]to[- ]market\b", r"\bmarket (?:expansion|sizing|entry)\b",
                        r"\bstrategic (?:planning|initiatives)\b"],
}

def _alias_patterns(spec: str) -> list[str]:
    """Taxonomy alias spec -> regexes. "re:..." is a raw regex; otherwise "|"-separated phrases matched as whole words."""
    if spec.startswith("re:"):
        return [spec[3:]]
    parts, depth, cur = [], 0, ""
    for ch in spec:  # split on top-level "|" only, so "(?:e|es)" stays whole
        depth += ch in "([" and 1 or (ch in ")]" and -1 or 0)
        if ch == "|" and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return [r"(?<![A-Za-z0-9])(?:" + a.strip() + r")(?![A-Za-z0-9])" for a in parts if a.strip()]


from .taxonomy import FAMILY_SKILLS  # noqa: E402  (after the base vocabulary on purpose)

for _name, _spec in FAMILY_SKILLS.items():
    SKILLS.setdefault(_name, _alias_patterns(_spec))

# Skills too generic to count as a "gap" when a JD mentions them in passing.
SOFT_GAP_EXCLUDE = {"MIS Reporting", "KPI Design", "Automation", "Dashboards", "Stakeholder Management",
                    "Data Storytelling", "Regression", "A/B Testing", "MS Office", "Customer Service", "Negotiation",
                    "Excel", "Problem Structuring", "Troubleshooting", "Data Entry", "Onboarding (HR)"}

INDUSTRIES: dict[str, list[str]] = {
    "Insurance": [r"\binsurance\b", r"\binsurer", r"\binsurtech\b", r"\bunderwriting\b", r"\bclaims\b",
                  r"\bpolicyholders?\b", r"\bbrokerage\b", r"\bhmo\b"],
    "Fintech": [r"\bfintech\b", r"\bpayments?\b", r"\blending\b", r"\bloans?\b", r"\bcredit cards?\b", r"\bnbfc\b",
                r"\bupi\b", r"\bwallets?\b", r"\bneobank"],
    "Banking & Financial Services": [r"\bbank(?:ing|s)?\b", r"\bfinancial services\b", r"\bwealth\b", r"\binvestment\b",
                                     r"\basset management\b", r"\bmutual funds?\b", r"\bcapital markets?\b", r"\bbfsi\b"],
    "Automotive": [r"\bautomotive\b", r"\bautomobiles?\b", r"\bvehicles?\b", r"\btwo[- ]wheeler", r"\b(?:ev|evs)\b",
                   r"\boems?\b", r"\bmobility\b", r"\bdealers?(?:hips?)?\b", r"\bcars?\b"],
    "E-commerce": [r"\be-?commerce\b", r"\bmarketplace\b", r"\bd2c\b", r"\bquick commerce\b", r"\bonline shopping\b"],
    "Retail & FMCG": [r"\bretail\b", r"\bfmcg\b", r"\bcpg\b", r"\bconsumer goods\b", r"\bstores?\b", r"\bbeverages?\b"],
    "Consulting": [r"\bconsulting\b", r"\badvisory\b", r"\bconsultancy\b", r"\bbig 4\b"],
    "IT Services": [r"\bit services\b", r"\bsoftware services\b", r"\bsystem integrator", r"\boutsourced (?:development|it)\b",
                    r"\bdigital transformation\b"],
    "SaaS / Tech": [r"\bsaas\b", r"\bsoftware\b", r"\bcloud platform\b", r"\bb2b\b", r"\bproduct company\b", r"\bstartup\b"],
    "Healthcare": [r"\bhealthcare\b", r"\bhealth ?tech\b", r"\bhospitals?\b", r"\bclinical\b", r"\bmedical\b", r"\bpatients?\b"],
    "Pharma & Life Sciences": [r"\bpharma", r"\bbiotech", r"\blife sciences\b", r"\bdrug", r"\bcro\b", r"\bvaccines?\b"],
    "Manufacturing": [r"\bmanufactur", r"\bplant\b", r"\bfactory\b", r"\bindustrial\b", r"\bshop floor\b"],
    "Construction & Real Estate": [r"\bconstruction\b", r"\breal estate\b", r"\binfrastructure projects?\b", r"\bbuilders?\b",
                                   r"\bproperty\b", r"\bepc\b"],
    "Energy & Utilities": [r"\benergy\b", r"\bpower plant", r"\brenewable", r"\bsolar\b", r"\boil (?:and|&) gas\b", r"\butilities\b"],
    "Telecom": [r"\btelecom", r"\b5g\b", r"\bnetwork operator", r"\bbroadband\b"],
    "Logistics": [r"\blogistics\b", r"\bsupply chain\b", r"\bfreight\b", r"\bshipping\b", r"\bcourier\b", r"\bwarehous"],
    "Education & EdTech": [r"\bedtech\b", r"\beducation\b", r"\bschools?\b", r"\buniversit", r"\blearning platform\b", r"\bstudents?\b"],
    "Media & Entertainment": [r"\bmedia\b", r"\bentertainment\b", r"\bott\b", r"\bstreaming\b", r"\bpublishing\b", r"\bgaming\b"],
    "Advertising & Marketing": [r"\badvertising\b", r"\bad agency\b", r"\bmarketing agency\b", r"\bdigital agency\b", r"\bcreative agency\b"],
    "Travel & Hospitality": [r"\btravel\b", r"\bhotels?\b", r"\bhospitality\b", r"\bairlines?\b", r"\btourism\b"],
    "Government & Public Sector": [r"\bgovernment\b", r"\bpublic sector\b", r"\bpsu\b", r"\bministry\b", r"\bngo\b", r"\bnon-?profit\b"],
    "Legal Services": [r"\blaw firm\b", r"\blegal services\b", r"\blitigation\b"],
    "BPO / KPO": [r"\bbpo\b", r"\bkpo\b", r"\boutsourcing\b", r"\bshared services\b", r"\bgcc\b", r"\bcaptive\b"],
}

_COMPILED = {k: [re.compile(p, re.I) for p in v] for k, v in SKILLS.items()}
_IND_COMPILED = {k: [re.compile(p, re.I) for p in v] for k, v in INDUSTRIES.items()}


def custom_patterns(names: list[str]) -> dict[str, list]:
    """Whole-phrase patterns for skills the vocabulary doesn't know (taken from a resume's skills section)."""
    out = {}
    for n in names or []:
        n = n.strip()
        if n and n not in _COMPILED:
            out[n] = [re.compile(r"(?<![A-Za-z0-9])" + re.escape(n).replace(r"\ ", r"[\s-]+") + r"(?![A-Za-z0-9])", re.I)]
    return out


def all_patterns(extra: list[str] | None = None) -> dict[str, list]:
    if not extra:
        return _COMPILED
    return {**_COMPILED, **custom_patterns(extra)}


def extract_skills(text: str, extra: list[str] | None = None) -> list[str]:
    """Canonical skills mentioned in text, in vocabulary order."""
    if not text:
        return []
    return [name for name, pats in all_patterns(extra).items() if any(p.search(text) for p in pats)]


def skill_counts(text: str, extra: list[str] | None = None) -> dict[str, int]:
    out = {}
    for name, pats in all_patterns(extra).items():
        n = sum(len(p.findall(text)) for p in pats)
        if n:
            out[name] = n
    return out


def detect_industries(text: str, min_hits: int = 1) -> list[str]:
    if not text:
        return []
    found = []
    for name, pats in _IND_COMPILED.items():
        hits = sum(len(p.findall(text)) for p in pats)
        if hits >= min_hits:
            found.append((hits, name))
    return [n for _, n in sorted(found, reverse=True)]
