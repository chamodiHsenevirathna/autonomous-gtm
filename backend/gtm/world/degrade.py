"""Deterministic noise shared by the world generator and the provider simulators.

Every decision is a pure function of (seed, provider, entity, field): no global RNG state, no clock.
"""
from __future__ import annotations
import hashlib, random
from typing import Any

# Entities every provider knows (so the golden thread can show a full waterfall). See world/README.md.
FORCED_COVERAGE = {"co_001", "ct_001", "ct_002", "ct_003"}

INDUSTRIES = ["Logistics", "Healthcare", "Financial Services", "Retail", "Manufacturing", "Energy", "Insurance",
              "Media", "Telecommunications", "Public Sector", "Education", "Hospitality", "Construction", "Agriculture"]
REGIONS = ["EMEA", "NA", "APAC", "LATAM"]
COUNTRIES = ["United Kingdom", "Germany", "Netherlands", "United States", "Canada", "Singapore", "Australia", "Brazil", "Ireland", "Sweden"]
BANDS = ["<10M", "10-50M", "50-250M", "250M-1B", ">1B"]
SENIORITIES = ["c_level", "vp", "director", "manager", "ic"]
TITLES = ["Chief Technology Officer", "VP Engineering", "Director of Data Platforms", "Engineering Manager", "Data Engineer",
          "Head of IT", "Product Manager", "Software Engineer", "Chief Operating Officer", "Director of IT"]
TECH_POOL = ["AWS", "Azure", "GCP", "Snowflake", "Databricks", "Airflow", "dbt", "Kafka", "Kubernetes", "Terraform", "Java", "COBOL",
             ".NET", "Python", "SAP", "Oracle", "Salesforce", "PyTorch", "LangChain", "Mainframe"]
HIRING_POOL = ["Hiring: Senior Data Engineer", "Hiring: ML Engineer", "Hiring: Cloud Platform Engineer", "Hiring: Solutions Architect",
               "Hiring: Head of Data", "Hiring: Site Reliability Engineer", "Hiring: Java Modernisation Lead"]


def unit(seed: int, *parts: Any) -> float:
    """Uniform float in [0, 1) derived from a hash of seed and parts."""
    h = hashlib.sha256("|".join([str(seed), *map(str, parts)]).encode()).digest()
    return int.from_bytes(h[:8], "big") / 2**64


def rng_for(seed: int, *parts: Any) -> random.Random:
    return random.Random(int.from_bytes(hashlib.sha256("|".join([str(seed), *map(str, parts)]).encode()).digest()[:8], "big"))


def covers(seed: int, provider: str, coverage: float, entity_id: str) -> bool:
    if entity_id in FORCED_COVERAGE:
        return True
    return unit(seed, provider, entity_id, "coverage") < coverage


def is_correct(seed: int, provider: str, accuracy: float, entity_id: str, field: str) -> bool:
    if entity_id in FORCED_COVERAGE and field == "name":
        return True
    return unit(seed, provider, entity_id, field, "acc") < accuracy


def _typo(s: str, r: random.Random) -> str:
    if len(s) < 4:
        return s + "x"
    i = r.randrange(1, len(s) - 2)
    out = s[:i] + s[i + 1] + s[i] + s[i + 2:]
    return out if out != s else s[:-1]


def wrong_value(field: str, truth: Any, r: random.Random, *, domain_hint: str = "") -> Any:
    """A plausible but incorrect value. Never equals the truth."""
    if field in ("employee_count",):
        f = r.choice([0.45, 0.6, 0.7, 1.35, 1.6, 2.2])
        v = int(round(int(truth) * f))
        return v if v != truth else int(truth) + 7
    if field == "revenue_band":
        i = BANDS.index(truth) if truth in BANDS else 0
        j = i + 1 if i == 0 else (i - 1 if i == len(BANDS) - 1 else i + r.choice([-1, 1]))
        return BANDS[j]
    pools = {"industry": INDUSTRIES, "region": REGIONS, "hq_country": COUNTRIES, "title": TITLES, "seniority": SENIORITIES}
    if field in pools:
        return r.choice([x for x in pools[field] if x != truth])
    if field in ("name", "legal_name", "full_name"):
        s = str(truth)
        if field != "full_name" and " " in s and r.random() < 0.5:
            return s.rsplit(" ", 1)[0] + " Group"
        return _typo(s, r)
    if field == "domain":
        label = str(truth).split(".")[0]
        return f"{label}-group.example"
    if field in ("tech_stack", "hiring_signals"):
        pool = TECH_POOL if field == "tech_stack" else HIRING_POOL
        items = list(truth or [])
        if items:
            items.pop(r.randrange(len(items)))
        extra = r.choice([p for p in pool if p not in items])
        return items + [extra]
    if field == "parent_id":
        return None if truth else "co_001"
    return f"{truth}?"
