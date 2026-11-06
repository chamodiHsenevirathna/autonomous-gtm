"""inbound_intake: lead.received -> triage -> entity resolution -> enrichment -> research -> qualify -> lead.qualified | G3 proposal."""
from __future__ import annotations
from psycopg.types.json import Jsonb
from gtm.contracts.events import EventEnvelope
from gtm.data import ensure_account, ensure_contact, propose_match, resolve_contact, resolve_fields
from gtm.data.entity_resolution import account_domain_key
from gtm.data.waterfall import CAPABILITIES, fetch_provider
from gtm.mcp.registry import ToolSession
from gtm.orchestration import Graph, emit
from .mockmodel import ICP

ENRICH_COST_CAP = 20.0          # simulated provider cost units per lead (A=1, C=5, B=10)
PROVIDER_ORDER = ("provider_a", "provider_c", "provider_b")     # cheapest first
ACCOUNT_FIELDS = ("employee_count", "region", "industry", "revenue_band", "hq_country", "tech_stack", "hiring_signals", "domain")
CONTACT_FIELDS = ("title", "seniority")
HOLD_LABELS = ("vendor", "recruiter", "spam")


def submit_enquiry(conn, clock, enquiry) -> int:
    """Insert the gtm.lead (idempotent on 'enq:<id>'), emit lead.received, return the lead id. Caller commits."""
    e = enquiry if isinstance(enquiry, dict) else enquiry.model_dump()
    raw = {k: e.get(k) for k in ("full_name", "email", "company_name", "message", "service_interest")} | {"enquiry_id": e["id"]}
    now = clock.now()
    conn.execute("INSERT INTO gtm.lead(channel, raw_payload, idempotency_key, status, created_at, updated_at) VALUES ('form',%s,%s,'new',%s,%s) "
                 "ON CONFLICT (idempotency_key) DO NOTHING", (Jsonb(raw), f"enq:{e['id']}", now, now))
    lead_id = conn.execute("SELECT id FROM gtm.lead WHERE idempotency_key=%s", (f"enq:{e['id']}",)).fetchone()["id"]
    emit(conn, clock, EventEnvelope(type="lead.received", entity_ref=f"lead:{lead_id}", payload={"lead_id": lead_id, "enquiry_id": e["id"]},
                                    occurred_at=now, source="webhook", dedupe_key=f"lead.received:{e['id']}"))
    return lead_id


def _lead_id(ctx) -> int:
    return int(ctx.trigger.payload["lead_id"])


def _load(ctx):
    lead = ctx.conn.execute("SELECT * FROM gtm.lead WHERE id=%s", (_lead_id(ctx),)).fetchone()
    raw = lead["raw_payload"]
    email = (raw.get("email") or "").strip().lower()
    known = resolve_contact(ctx.conn, ctx.clock, email=email, full_name=raw.get("full_name") or "", company_name=raw.get("company_name"))
    return {"lead_id": lead["id"], "enquiry_id": raw.get("enquiry_id"), "email": email, "full_name": raw.get("full_name"),
            "company": raw.get("company_name"), "domain": account_domain_key(email.split("@")[-1]), "message": raw.get("message") or "",
            "service_interest": raw.get("service_interest"), "existing_contact": known.band == "same"}


def _set_lead(ctx, **cols):
    cols["updated_at"] = ctx.clock.now()
    ctx.conn.execute("UPDATE gtm.lead SET " + ", ".join(f"{k}=%s" for k in cols) + " WHERE id=%s",
                     [Jsonb(v) if isinstance(v, (dict, list)) else v for v in cols.values()] + [_lead_id(ctx)])


def _gate(ctx):
    return triage_gate(ctx.state["triage"], ctx.state["load"]["existing_contact"])


def _hold(ctx):
    tri = ctx.state["triage"]
    reason = "injection_suspected" if tri["injection_suspected"] else f"triage:{tri['label']}"
    _set_lead(ctx, status="held", held_reason=reason, triage_class=tri["label"], triage_confidence=tri["confidence"])
    ctx.audit("lead.held", {"reason": reason, "confidence": tri["confidence"]}, entity_ref=f"lead:{_lead_id(ctx)}")
    if tri["injection_suspected"]:
        ctx.audit("lead.injection_suspected", {"label": tri["label"], "note": "text treated as data; behaviour unchanged"}, entity_ref=f"lead:{_lead_id(ctx)}")
    return {"held": True, "reason": reason}          # never destroyed: the row stays, a human can release it


def _resolve(ctx):
    ld, c = ctx.state["load"], ctx.conn
    rs = ctx.trigger.payload.get("resume")
    if rs:      # resumed after a human decided the match proposal(s): use the decided records, never auto-merge
        _set_lead(ctx, account_id=rs["account_id"], contact_id=rs["contact_id"], status="new", held_reason=None)
        ctx.audit("lead.resumed", {"resume": rs}, entity_ref=f"lead:{_lead_id(ctx)}")
        return {"account_id": rs["account_id"], "contact_id": rs["contact_id"], "account_band": "resumed", "contact_band": "resumed", "match_proposals": [], "pending": False}
    aid, ad = ensure_account(c, ctx.clock, name=ld["company"] or ld["domain"] or "Unknown", domain=ld["domain"])
    cid, cd = ensure_contact(c, ctx.clock, email=ld["email"], full_name=ld["full_name"] or ld["email"], company_name=ld["company"], account_id=aid)
    if cd.band == "same":
        row = c.execute("SELECT account_id FROM gtm.contact WHERE id=%s", (cid,)).fetchone()
        aid = row["account_id"] or aid
    proposals = []
    for d, new in ((ad, aid), (cd, cid)):
        if d.band == "possible":
            pid = propose_match(c, ctx.clock, d, new, account_id=aid)
            if pid:
                proposals.append(pid)
    _set_lead(ctx, account_id=aid, contact_id=cid)
    pending = ad.band == "possible" or cd.band == "possible"
    return {"account_id": aid, "contact_id": cid, "account_band": ad.band, "contact_band": cd.band, "match_proposals": proposals, "pending": pending}


def _er_gate(ctx):
    return "pending" if ctx.state["resolve"]["pending"] else "ok"


def _er_pending(ctx):
    _set_lead(ctx, status="held", held_reason="match_pending")
    return {"held": True, "reason": "match_pending"}


def _enrich_items(ctx):
    out = []
    for p in PROVIDER_ORDER:
        for et, wanted in (("account", ACCOUNT_FIELDS), ("contact", CONTACT_FIELDS)):
            f = [x for x in wanted if x in CAPABILITIES[p][et]]
            if f:
                out.append({"provider": p, "entity_type": et, "fields": f})
    spent, kept = 0.0, []
    costs = {"provider_a": 1.0, "provider_c": 5.0, "provider_b": 10.0}
    for it in out:
        if spent + costs[it["provider"]] <= ENRICH_COST_CAP:
            kept.append(it); spent += costs[it["provider"]]
    return kept


def _fetch(ctx, it):
    r = ctx.state["resolve"]
    eid = r["account_id"] if it["entity_type"] == "account" else r["contact_id"]
    client = ctx.services.providers[it["provider"]]
    out = ctx.call(f"provider.{it['provider']}", fetch_provider, ctx.conn, ctx.clock, client, it["provider"], it["entity_type"], eid, it["fields"], run_id=ctx.run_id)
    return {k: out[k] for k in ("provider", "found", "cost_units", "partial")} | {"fields": sorted(out["observation_ids"])}


def _reduce(ctx, res):
    ok = [v["output"] for v in res.values() if v["ok"]]
    return {"cost_units": sum(o["cost_units"] for o in ok), "gaps": [k for k, v in res.items() if not v["ok"] or not v["output"]["found"]],
            "providers_ok": sorted({o["provider"] for o in ok if o["found"]})}


def _resolve_fields(ctx):
    r = ctx.state["resolve"]
    acc = resolve_fields(ctx.conn, ctx.clock, "account", r["account_id"])
    con = resolve_fields(ctx.conn, ctx.clock, "contact", r["contact_id"])
    pick = lambda d: {f: {"value": v.get("value"), "confidence": v.get("confidence")} for f, v in d.items()}
    return {"account": pick(acc), "contact": pick(con)}


def _research(ctx):
    """Bounded agent: web search + fetch via the research-agent ToolSession. Page text is untrusted data."""
    r = ctx.state["resolve"]
    sess = ToolSession(ctx.conn, ctx.clock, ctx.services, profile="research-agent", principal="agent:research-agent", account_id=r["account_id"], run_id=ctx.run_id)
    name = ctx.state["load"]["company"] or ""
    ctx.tick()
    hits = sess.call("search_web_sim", query=name)["untrusted"]
    pages = []
    for h in (hits or [])[:3]:
        ctx.tick()
        if not str(h.get("url", "")).startswith("https://") or name.split()[0].lower() not in h["url"]:
            continue
        p = sess.call("fetch_page_sim", url=h["url"])
        pages.append({"url": p["source_url"], "title": p["untrusted"]["title"], "text": p["untrusted"]["text"]})
    ctx.tick()
    brief = ctx.llm("research_brief", {"company": name, "untrusted": {"pages": pages}})
    claims = [c for c in brief["claims"] if c.get("source_ref")]      # a claim without a source is dropped, never kept
    return {"claims": claims, "unknowns": brief["unknowns"], "injection_flags": brief["injection_flags"], "pages": [p["url"] for p in pages]}


def _qualify_input(ctx):
    ld, rf = ctx.state["load"], ctx.state["resolve_fields"]
    resolved = dict(rf["account"])
    texts = " ".join(c["text"] for c in ctx.state["research"]["claims"])
    return {"resolved": resolved, "contact": {"seniority": (rf["contact"].get("seniority") or {}).get("value")},
            "untrusted": {"message": ld["message"], "service_interest": ld["service_interest"], "research": texts}}


HARD_CONSTRAINT_MIN_CONFIDENCE = 0.6     # DEFAULT of the configurable business-policy threshold (config.Settings.hard_constraint_min_confidence); not statistically validated


def _threshold() -> float:
    from gtm.config import get_settings
    t = get_settings().hard_constraint_min_confidence
    if not 0.0 <= t <= 1.0:
        raise ValueError(f"GTM_HARD_CONSTRAINT_MIN_CONFIDENCE must be between 0 and 1, got {t}")
    return t


def apply_hard_constraints(band: str, acct: dict, min_confidence: float | None = None) -> tuple[str, list[str], list[dict]]:
    """Code-enforced hard constraints on MANDATORY company facts (employee count, region). They can only downgrade a band, never upgrade it.
    Owner policy 2026-11-07, identical for both fields:
      - confidence >= threshold: the rule may influence qualification (a breach caps the band at low)
      - confidence below the threshold, or missing: treated as LOW confidence -> NEVER downgrades; the field is listed in evidence_needed for human verification
      - value missing: nothing to decide on; listed in evidence_needed (the criterion is mandatory and unverified)
    Returns (band, reasons_for_downgrade, evidence_needed). Nothing is rejected silently: every uncertain mandatory fact is reported."""
    t = _threshold() if min_confidence is None else min_confidence
    why, needed = [], []

    def check(field: str, breaches, describe: str):
        e = acct.get(field) or {}
        v, c = e.get("value"), e.get("confidence")
        if v is None:
            needed.append({"field": field, "value": None, "confidence": c, "would_have_applied": False,
                           "reason": f"{field} is unknown and is a mandatory criterion: human verification requested"})
        elif c is None or c < t:
            needed.append({"field": field, "value": v, "confidence": c, "would_have_applied": bool(breaches(v)),
                           "reason": f"{field} has confidence {c} (below the {t} policy threshold or missing): not used to hold or disqualify the lead; human verification requested"})
        elif breaches(v):
            why.append(f"hard: {describe(v)}")

    check("employee_count", lambda v: int(v) < ICP["min_employees"], lambda v: f"employee_count {v} < {ICP['min_employees']}")
    check("region", lambda v: v not in ICP["regions"], lambda v: f"region {v} not served")
    if why:
        band = "low" if band in ("high", "medium", "low") else band
    return band, why, needed


def triage_gate(tri: dict, existing_contact: bool) -> str:
    """Hold for human review (never archived, never destroyed) when: an injection is suspected; the intent is unclear (policy 8); the message is spam or
    phishing at ANY confidence and from ANY sender (policy 7); or it is confidently vendor/recruiter from an unknown sender. Held leads keep their row and a human can release them."""
    if tri["injection_suspected"] or tri["label"] in ("unclear", "spam") or (tri["label"] in HOLD_LABELS and tri["confidence"] >= 0.8 and not existing_contact):
        return "hold"
    return "go"


def _decide(ctx):
    q, rf = ctx.state["qualify"], ctx.state["resolve_fields"]["account"]
    band, why, needed = apply_hard_constraints(q["band"], rf)
    note = (" Overridden: " + "; ".join(why) if why else "") + (" Evidence requested: " + "; ".join(f"{n['field']} ({n['value']} at confidence {n['confidence']})" for n in needed) if needed else "")
    return {"score": q["score"], "band": band, "model_band": q["band"], "hard_constraints": why, "evidence_needed": needed, "owner_hint": q.get("owner_hint"),
            "service_line": q.get("service_line"), "rationale": q["rationale"] + note, "unknowns": q["unknowns"]}


def _route_gate(ctx):
    return "qualified" if ctx.state["decide"]["band"] in ("high", "medium") else "low"


def _qualified(ctx):
    d, r, tri = ctx.state["decide"], ctx.state["resolve"], ctx.state["triage"]
    _set_lead(ctx, status="qualified", fit_score=d["score"], fit_band=d["band"], triage_class=tri["label"], triage_confidence=tri["confidence"],
              fit_rationale={"rationale": d["rationale"], "criteria": ctx.state["qualify"]["criteria"], "unknowns": d["unknowns"],
                             "hard_constraints": d["hard_constraints"], "evidence_needed": d["evidence_needed"], "service_line": d["service_line"], "mode": "mock"})
    if d["evidence_needed"]:
        ctx.audit("lead.evidence_needed", {"lead_id": _lead_id(ctx), "needed": d["evidence_needed"], "note": "low-confidence value not used to hold or disqualify; human to confirm"}, entity_ref=f"lead:{_lead_id(ctx)}")
    if d["owner_hint"]:
        ctx.conn.execute("UPDATE gtm.account SET owner_principal=%s, updated_at=%s WHERE id=%s AND owner_principal IS NULL", (d["owner_hint"], ctx.clock.now(), r["account_id"]))
        ctx.audit("account.routed", {"owner": d["owner_hint"], "reason": "initial routing of a new, unowned account"}, entity_ref=f"account:{r['account_id']}")
    ctx.emit("lead.qualified", {"lead_id": _lead_id(ctx), "band": d["band"], "service_line": d["service_line"]}, entity_ref=f"lead:{_lead_id(ctx)}", account_id=r["account_id"])
    return {"qualified": True}


def _low(ctx):
    from gtm.approvals import create_proposal
    d, r, tri = ctx.state["decide"], ctx.state["resolve"], ctx.state["triage"]
    disp = "disqualified" if d["band"] == "none" else "nurture"
    _set_lead(ctx, status="held", held_reason="low_fit", fit_score=d["score"], fit_band=d["band"], triage_class=tri["label"], triage_confidence=tri["confidence"],
              fit_rationale={"rationale": d["rationale"], "hard_constraints": d["hard_constraints"], "evidence_needed": d["evidence_needed"], "unknowns": d["unknowns"], "mode": "mock"})
    if d["evidence_needed"]:
        ctx.audit("lead.evidence_needed", {"lead_id": _lead_id(ctx), "needed": d["evidence_needed"], "note": "low-confidence value not used to hold or disqualify; human to confirm"}, entity_ref=f"lead:{_lead_id(ctx)}")
    pid = create_proposal(ctx.conn, ctx.clock, type="lead_disposition", proposed_by="system:orchestrator", account_id=r["account_id"], run_id=ctx.run_id,
                          payload={"lead_id": _lead_id(ctx), "disposition": disp, "score": d["score"]}, evidence=[{"ref": f"lead:{_lead_id(ctx)}"}],
                          rationale=d["rationale"], confidence=0.7, idempotency_key=f"disp:{_lead_id(ctx)}")
    return {"proposal_id": pid, "disposition": disp}


def build_graph() -> Graph:
    g = Graph("inbound_intake", "1")
    g.trigger("on_lead_received", "lead.received")
    g.code("load", _load)
    g.llm("triage", "triage", lambda ctx: {"untrusted": {"message": ctx.state["load"]["message"]}, "company_known": ctx.state["load"]["existing_contact"]}, after="load")
    g.conditional("gate", _gate, after="triage")
    g.code("hold", _hold, after="gate", when=("gate", "hold"))
    g.code("resolve", _resolve, after="gate", when=("gate", "go"))
    g.conditional("er_gate", _er_gate, after="resolve")
    g.code("er_pending", _er_pending, after="er_gate", when=("er_gate", "pending"))
    g.map("enrich", _enrich_items, _fetch, after="er_gate", key=lambda it: f"{it['provider']}:{it['entity_type']}", concurrency=3, when=("er_gate", "ok"))
    g.reduce("enriched", "enrich", _reduce)
    g.code("resolve_fields", _resolve_fields, after="enriched")
    g.agent("research", _research, after="resolve_fields", max_steps=8)
    g.llm("qualify", "qualify", _qualify_input, after="research")
    g.code("decide", _decide, after="qualify")
    g.conditional("route", _route_gate, after="decide")
    g.code("qualified", _qualified, after="route", when=("route", "qualified"))
    g.code("low", _low, after="route", when=("route", "low"))
    return g
