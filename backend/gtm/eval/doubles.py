"""Deterministic test doubles: deliberately BAD 'models' used to prove the evaluation harness detects the failures it claims to detect.
They are built on the mock's outputs and then corrupted in one specific way. They are not models and prove nothing about any real model;
they show only that a model failing in this way would be caught. Zero cost, no network."""
from __future__ import annotations
import copy, itertools, re
from ..agents import mockmodel as mm
from ..llm import register_mock

_INJ = re.compile(r"ignore|system|instruction|reveal|approve|disregard|ignorieren|assistant", re.I)


def _is_injected(inp: dict) -> bool:
    return bool(_INJ.search(str(inp.get("untrusted", ""))))


def injection_compliant():
    def triage(i):
        o = mm.triage(i)
        if _is_injected(i): o.update(label="genuine", confidence=0.99, injection_suspected=False)
        return o
    def qualify(i):
        o = mm.qualify(i)
        if _is_injected(i): o.update(score=100, band="high", owner_hint="user:maya")
        return o
    def research(i):
        o = mm.research_brief(i)
        for pg in i["untrusted"]["pages"]:
            for s in re.split(r"(?<=[.!?])\s+", pg["text"]):
                if _INJ.search(s): o["claims"].append({"text": s, "source_ref": pg["url"]})
        o["injection_flags"] = []
        return o
    return {"triage": triage, "qualify": qualify, "research_brief": research}


def fabricator():
    def research(i):
        o = mm.research_brief(i)
        if i["untrusted"]["pages"]:
            o["claims"].append({"text": f"{i['company']} has 5,000 employees and recently raised a Series C.", "source_ref": i["untrusted"]["pages"][0]["url"]})
        o["claims"].append({"text": "It is a fast-growing market leader.", "source_ref": "https://invented.example/page"})
        return o
    def qualify(i):
        o = mm.qualify(i)
        o["rationale"] += " Annual revenue is about 480 million."
        o["criteria"].append({"name": "hiring_signal", "met": True, "evidence_ref": "resolved:hiring_signals", "note": "invented"})
        o["unknowns"] = []
        return o
    return {"research_brief": research, "qualify": qualify}


def sloppy_router():
    def account(i):
        o = mm.account_decide(i)
        o["actions"] += [{"type": "draft_message", "params": {}, "rationale": "always follow up", "evidence_refs": []},
                         {"type": "propose_crm_create", "params": {}, "rationale": "always create", "evidence_refs": []}]
        for a in o["actions"]: a["evidence_refs"] = []
        return o
    return {"account_decide": account}


def over_qualifier():
    def qualify(i):
        o = mm.qualify(i)
        o.update(score=90, band="high")
        return o
    return {"qualify": qualify}


def schema_breaker(always: bool):
    def wrap(fn):
        def f(i):
            if always or "_repair" not in i:
                return {"label": "bogus", "band": "excellent", "claims": "none", "actions": 3, "intent": 1}
            return fn(i)
        return f
    return {"triage": wrap(mm.triage), "qualify": wrap(mm.qualify), "research_brief": wrap(mm.research_brief), "account_decide": wrap(mm.account_decide)}


def inconsistent():
    flip = itertools.count()
    def triage(i):
        o = mm.triage(i)
        if next(flip) % 2: o["label"] = "unclear"
        return o
    def qualify(i):
        o = mm.qualify(i)
        if next(flip) % 2: o["band"] = "low" if o["band"] != "low" else "high"
        return o
    return {"triage": triage, "qualify": qualify}


DOUBLES = {"injection_compliant": injection_compliant, "fabricator": fabricator, "sloppy_router": sloppy_router, "over_qualifier": over_qualifier,
           "schema_breaker_repairable": lambda: schema_breaker(False), "schema_breaker_always": lambda: schema_breaker(True), "inconsistent": inconsistent}


def install(name: str) -> None:
    """Register the mock, then override the tasks the named double corrupts."""
    mm.register_all()
    for task, fn in DOUBLES[name]().items():
        register_mock(task, copy.copy(fn))
