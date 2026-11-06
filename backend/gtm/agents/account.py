"""account_wake: event/heartbeat -> lifecycle filter -> change detector -> context pack -> one LLM call -> validated action menu
-> applied ONLY through the account-agent ToolSession (proposals, ai_* fields, state patch). Never executes anything."""
from __future__ import annotations
from datetime import timedelta
from psycopg.types.json import Jsonb
from gtm.approvals import supersede
from gtm.contracts.errors import PermanentError
from gtm.contracts.proposals import MessagePayload
from gtm.mcp.registry import ToolSession, VersionConflict
from gtm.orchestration import Graph, add_schedule
from .context import build_context_pack, change_detector

TRIGGERS = ["lead.qualified", "reply.received", "meeting.booked", "deal.flagged", "feedback.captured", "heartbeat.due"]
REACTIVATION = {"reply.received", "meeting.booked", "lead.qualified"}
HEARTBEAT_DAYS = 7
MENU = {"no_action", "update_agent_fields", "recommend_task", "draft_message", "propose_field_change", "propose_crm_create",
        "request_enrichment", "flag_risk", "recommend_human_touch"}
PRINCIPAL = "agent:account-agent"


def lifecycle_filter(conn, env, workflow: str) -> bool:
    """Dispatcher hook: events for dormant/archived accounts wake the agent only if they are reactivation triggers."""
    if workflow != "account_wake":
        return True
    if env.account_id is None:
        return False
    st = conn.execute("SELECT lifecycle FROM gtm.account_agent_state WHERE account_id=%s", (env.account_id,)).fetchone()
    if st and st["lifecycle"] == "archived":
        return False
    if st and st["lifecycle"] == "dormant" and env.type not in REACTIVATION:
        return False
    return True


def _session(ctx) -> ToolSession:
    return ToolSession(ctx.conn, ctx.clock, ctx.services, profile="account-agent", principal=PRINCIPAL, account_id=ctx.account_id, run_id=ctx.run_id)


def _state(conn, aid):
    return conn.execute("SELECT * FROM gtm.account_agent_state WHERE account_id=%s", (aid,)).fetchone()


def _load(ctx):
    sess = _session(ctx)
    if _state(ctx.conn, ctx.account_id) is None:
        sess.call("patch_agent_state", account_id=ctx.account_id, version=0, patch={"summary": ""})
    ctx.conn.execute("UPDATE gtm.account_agent_state SET lifecycle='active' WHERE account_id=%s AND lifecycle IN ('unprovisioned','dormant','quiet')", (ctx.account_id,))
    return {"account_id": ctx.account_id, "event": ctx.trigger.type, "events": [e.type for e in ctx.events]}


def _detect(ctx):
    types = [e.type for e in ctx.events]
    mat = {"material": False, "reasons": []}
    for t in types or [ctx.trigger.type]:
        d = change_detector(ctx.conn, ctx.clock, ctx.account_id, t)
        mat["material"] |= d["material"]; mat["reasons"] += [r for r in d["reasons"] if r not in mat["reasons"]]
    return mat


def _gate(ctx):
    return "model" if ctx.state["detect"]["material"] else "idle"


def _focus_contact(ctx, ev):
    c, p = ctx.conn, ev.payload
    cid = p.get("contact_id")
    if cid is None and p.get("lead_id"):
        cid = (c.execute("SELECT contact_id FROM gtm.lead WHERE id=%s", (p["lead_id"],)).fetchone() or {}).get("contact_id")
    if cid is None:
        r = c.execute("SELECT id FROM gtm.contact WHERE account_id=%s AND merged_into_id IS NULL ORDER BY id LIMIT 1", (ctx.account_id,)).fetchone()
        cid = r and r["id"]
    ct = c.execute("SELECT id, full_name, email FROM gtm.contact WHERE id=%s AND account_id=%s", (cid, ctx.account_id)).fetchone() if cid else None
    if ct is None:      # never hand the agent a contact of another account
        ct = c.execute("SELECT id, full_name, email FROM gtm.contact WHERE account_id=%s AND merged_into_id IS NULL ORDER BY id LIMIT 1", (ctx.account_id,)).fetchone()
    return ct


def _pack(ctx):
    c, aid, ev = ctx.conn, ctx.account_id, ctx.trigger
    pack = build_context_pack(c, ctx.clock, aid)
    acct = pack["account"]
    ct = _focus_contact(ctx, ev)
    sess = _session(ctx)
    sup = sess.call("get_suppression_status", contact_id=ct["id"]) if ct else {}
    crm = c.execute("SELECT count(*) n FROM ops.proposal WHERE account_id=%s AND type='crm_write' AND status NOT IN ('rejected','expired','superseded','failed')", (aid,)).fetchone()["n"]
    opp = c.execute("SELECT id, name, stage, is_stalled FROM gtm.opportunity WHERE account_id=%s ORDER BY id LIMIT 1", (aid,)).fetchone()
    new = pack["interactions_since_review"]["items"]
    intent = ev.payload.get("intent")
    inp = {"event": {"type": ev.type, "intent": intent, "interaction_id": ev.payload.get("interaction_id"), "lead_id": ev.payload.get("lead_id")},
           "account": {"id": aid, "name": acct["name"], "owner": acct["owner"], "has_crm_ids": bool(acct["external_ids"].get("crm")) or crm > 0},
           "contact": {"id": ct["id"], "name": ct["full_name"], "email": ct["email"], "suppressed": bool(sup.get("suppressed") or sup.get("blocked"))} if ct else {},
           "opportunity": dict(opp) if opp else None, "stalled": any(o["is_stalled"] for o in pack["opportunities"]["items"]),
           "material_change": ctx.state["detect"]["material"], "pending_proposals": len(pack["constraints"]["pending_proposals"]),
           "untrusted": {"interactions": [{"subject": i["subject"], "body": (i["body"] or "")[:500]} for i in new]}}
    return {"hash": pack["content_hash"], "tokens": pack["meta"]["tokens_est"], "trimmed": pack["meta"]["trimmed"], "decide_input": inp,
            "state_version": (pack["agent_state"] or {}).get("version")}


def _validate(ctx):
    inp, dec = ctx.state["pack"]["decide_input"], ctx.state["decide"]
    ok, rejected = [], []
    for i, a in enumerate(dec["actions"][:8]):
        why = None
        if a["type"] not in MENU:
            why = "not in action menu"
        elif a["type"] == "draft_message" and (not inp["contact"] or inp["contact"].get("suppressed")):
            why = "contact missing or suppressed"
        elif a["type"] == "propose_crm_create" and inp["account"]["has_crm_ids"]:
            why = "CRM record or proposal already exists"
        elif a["type"] == "update_agent_fields" and set(a["params"]) - {"ai_summary", "ai_risk_level", "ai_next_action"}:
            why = "non agent-owned field"
        if why:
            rejected.append({"index": i, "type": a["type"], "reason": why})
        else:
            ok.append({"index": i, **a})
    if not ok:
        ok = [{"index": 0, "type": "no_action", "params": {}, "rationale": "all proposed actions rejected by validation", "evidence_refs": []}]
    return {"actions": ok, "rejected": rejected}


def _supersede_stale(ctx):
    """S21: a human acted since our pending proposal was written -> supersede it (the system, not the agent, does this)."""
    n = 0
    rows = ctx.conn.execute("SELECT id, created_at FROM ops.proposal WHERE account_id=%s AND status='pending' AND proposed_by=%s AND type IN ('message','task') "
                            "AND (proposed_by_run_id IS NULL OR proposed_by_run_id<>%s)", (ctx.account_id, PRINCIPAL, ctx.run_id)).fetchall()
    for r in rows:
        acted = ctx.conn.execute("SELECT 1 FROM gtm.interaction WHERE account_id=%s AND occurred_at>%s AND (direction='inbound' OR classification='human_touch') LIMIT 1", (ctx.account_id, r["created_at"])).fetchone() \
            or ctx.conn.execute("SELECT 1 FROM gtm.stage_history h JOIN gtm.opportunity o ON o.id=h.opportunity_id WHERE o.account_id=%s AND h.at>%s AND h.from_stage IS NOT NULL LIMIT 1", (ctx.account_id, r["created_at"])).fetchone()
        if acted:
            supersede(ctx.conn, ctx.clock, r["id"], "human acted or context changed since this proposal was written"); n += 1
    return n


def _ensure_opportunity(ctx, acct, lead_id):
    c = ctx.conn
    o = c.execute("SELECT id FROM gtm.opportunity WHERE account_id=%s ORDER BY id LIMIT 1", (ctx.account_id,)).fetchone()
    if o:
        return o["id"]
    now = ctx.clock.now()
    line = ((c.execute("SELECT fit_rationale FROM gtm.lead WHERE id=%s", (lead_id,)).fetchone() or {}).get("fit_rationale") or {}).get("service_line") if lead_id else None
    oid = c.execute("INSERT INTO gtm.opportunity(account_id, name, service_line, stage, owner_principal, source_lead_id, created_at, updated_at) VALUES (%s,%s,%s,'qualified',%s,%s,%s,%s) RETURNING id",
                    (ctx.account_id, f"{(line or 'Inbound enquiry').title()} - {acct['name']}", line, acct["owner"], lead_id, now, now)).fetchone()["id"]
    c.execute("INSERT INTO gtm.stage_history(opportunity_id, from_stage, to_stage, changed_by, at) VALUES (%s,NULL,'qualified','system:orchestrator',%s)", (oid, now))
    return oid


_ACTION_OF = {"crm_write": "propose_crm_create", "message": "draft_message", "task": "recommend_task", "field_change": "propose_field_change"}
_STATUS_OF = {"pending": "pending_approval", "approved": "pending_approval", "approved_edited": "pending_approval", "parked": "pending_approval",
              "executing": "pending_approval", "executed": "done", "rejected": "dismissed", "expired": "dismissed", "superseded": "dismissed",
              "blocked": "dismissed", "failed": "dismissed"}
_STANCE = {"interested": "champion", "meeting_booked": "champion", "not_now": "neutral", "not_interested": "blocker", "unsubscribe": "blocker", "bounce": "blocker"}


def _proposal_text(p) -> str:
    pl = p["payload"]
    if p["type"] == "crm_write":
        return "Create the company, contact and deal in the CRM"
    if p["type"] == "message":
        return f"Send reply: {pl.get('subject', '')}".strip()
    if p["type"] == "task":
        return pl.get("title", "Task for the owner")
    return f"Change {pl.get('field', 'field')} on {pl.get('entity', 'record')}"


def _build_state(ctx, dec, created, ev, ct):
    """Deterministic state sections from facts (DB rows, trusted router/pipeline outputs, validated decision). Reply text is never used."""
    from gtm.data import get_resolved
    c, aid, now = ctx.conn, ctx.account_id, ctx.clock.now()
    old = _state(c, aid)
    # stakeholders
    prior = {x.get("name"): x for x in (old["stakeholder_map"] or []) if isinstance(x, dict)}
    stake = []
    for k in c.execute("SELECT id, full_name, title FROM gtm.contact WHERE account_id=%s AND merged_into_id IS NULL ORDER BY id", (aid,)).fetchall():
        e = dict(prior.get(k["full_name"], {}))
        stance, ref = e.get("stance", "unknown"), e.get("source_ref") or f"contact:{k['id']}"
        if ct and ct.get("id") == k["id"] and ev.get("intent") in _STANCE:
            stance, ref = _STANCE[ev["intent"]], f"interaction:{ev['interaction_id']}" if ev.get("interaction_id") else ref
        elif ct and ct.get("id") == k["id"] and not e and ev.get("lead_id"):
            ref = f"lead:{ev['lead_id']}"
        stake.append({"name": k["full_name"], "role": k["title"] or "Contact", "stance": stance, "source_ref": ref})
    # risks
    risks = [{"text": r, "severity": "high" if "unsubscribe" in r or "bounce" in r else "medium", "refs": [f"event:{ev.get('type')}"]} for r in dec["risks"]]
    for f, r in get_resolved(c, "account", aid).items():
        if r.get("conflict_flag"):
            risks.append({"text": f"Conflicting provider values for {f}", "severity": "medium", "refs": [f"resolved:{f}"]})
        elif r.get("confidence") is not None and float(r["confidence"]) < 0.6:
            risks.append({"text": f"Low-confidence value for {f}", "severity": "low", "refs": [f"resolved:{f}"]})
    lead = c.execute("SELECT id, fit_rationale FROM gtm.lead WHERE account_id=%s ORDER BY id DESC LIMIT 1", (aid,)).fetchone()
    for u in ((lead or {}).get("fit_rationale") or {}).get("unknowns", []):
        risks.append({"text": f"Unknown at qualification: {u}", "severity": "low", "refs": [f"lead:{lead['id']}"]})
    last = c.execute("SELECT max(occurred_at) t FROM gtm.interaction WHERE account_id=%s", (aid,)).fetchone()["t"]
    if last and (now - last).days >= 14:
        risks.append({"text": f"No contact for {(now - last).days} days", "severity": "medium", "refs": ["silence"]})
    # commitments
    com = []
    for m in c.execute("SELECT id, status, payload->>'subject' AS subj FROM ops.proposal WHERE account_id=%s AND type='message' ORDER BY id", (aid,)).fetchall():
        if m["status"] in ("executed", "pending", "approved", "approved_edited", "parked", "executing"):
            com.append({"party": "us", "text": f"Reply to the customer: {m['subj']}", "due": None, "status": "done" if m["status"] == "executed" else "proposed", "refs": [f"proposal:{m['id']}"]})
    for i in c.execute("SELECT id, classification FROM gtm.interaction WHERE account_id=%s AND direction='inbound' AND classification IN ('interested','meeting_booked') ORDER BY id", (aid,)).fetchall():
        com.append({"party": "customer", "text": "Customer open to a call" if i["classification"] == "interested" else "Discovery call booked by the customer",
                    "due": None, "status": "proposed" if i["classification"] == "interested" else "open", "refs": [f"interaction:{i['id']}"]})
    # next actions: refresh every proposal this agent made, newest last
    nxt = []
    for p in c.execute("SELECT id, type, status, rationale, payload FROM ops.proposal WHERE account_id=%s AND proposed_by=%s AND type = ANY(%s) ORDER BY id", (aid, PRINCIPAL, list(_ACTION_OF))).fetchall():
        nxt.append({"id": p["id"], "action": _ACTION_OF[p["type"]], "text": _proposal_text(p), "status": _STATUS_OF.get(p["status"], "pending_approval"),
                    "proposal_id": p["id"], "rationale": p["rationale"] or ""})
    for k, a in enumerate(ctx.state["validate"]["actions"]):
        if a["type"] in ("flag_risk", "recommend_human_touch", "request_enrichment"):
            nxt.append({"id": 1_000_000 + ctx.run_id * 100 + k, "action": a["type"], "text": a["params"].get("risk") or a["params"].get("reason") or a["rationale"],
                        "status": "done", "proposal_id": None, "rationale": a["rationale"]})
    nxt = nxt[-20:]
    if not nxt:
        nxt = [{"id": 1_000_000 + ctx.run_id * 100, "action": "no_action", "text": dec["summary"], "status": "done", "proposal_id": None, "rationale": ctx.state["validate"]["actions"][0]["rationale"]}]
    refs = sorted({r for a in ctx.state["validate"]["actions"] for r in (a.get("evidence_refs") or [])})
    hyp = [h for h in (old["hypotheses"] or []) if isinstance(h, dict) and "would_change_mind" in h][-9:]
    hyp.append({"text": f"{dec['summary']} (confidence {dec['confidence']:.2f})", "would_change_mind": dec["what_would_change"] or "new evidence", "evidence_refs": refs})
    open_q = [dec["what_would_change"]] if dec["what_would_change"] else []
    open_q += [f"What is the {u}?" for u in ((lead or {}).get("fit_rationale") or {}).get("unknowns", [])]
    sev = {"high": 3, "medium": 2, "low": 1}
    level = max((r["severity"] for r in risks), key=lambda x: sev[x], default="low")
    pend = next((a for a in nxt if a["status"] == "pending_approval"), None)
    ai = {"ai_summary": dec["summary"], "ai_risk_level": level, "ai_next_action": pend["text"] if pend else "No action needed; keep monitoring"}
    patch = {"summary": dec["summary"], "stakeholder_map": stake, "risks": risks, "commitments": com, "open_questions": open_q, "next_actions": nxt, "hypotheses": hyp}
    return patch, ai


def _apply(ctx):
    sess, inp, c = _session(ctx), ctx.state["pack"]["decide_input"], ctx.conn
    acct, ct, ev = inp["account"], inp["contact"], inp["event"]
    done, created, p_a, ai_fields = [], [], None, {}
    superseded = _supersede_stale(ctx)
    owner = acct["owner"] or "user:maya"
    for a in ctx.state["validate"]["actions"]:
        i, t, p = a["index"], a["type"], a["params"]
        key = f"run{ctx.run_id}:a{i}"
        ev_refs = [{"ref": r} for r in (a.get("evidence_refs") or [f"event:{ev['type']}"])]
        if t == "propose_crm_create":
            oid = _ensure_opportunity(ctx, acct, ev.get("lead_id"))
            company = c.execute("SELECT name, primary_domain FROM gtm.account WHERE id=%s", (ctx.account_id,)).fetchone()
            opp = c.execute("SELECT name FROM gtm.opportunity WHERE id=%s", (oid,)).fetchone()
            ops = [{"object": "company", "action": "create", "local_ref": {"type": "account", "id": ctx.account_id}, "properties": {"name": company["name"], "domain": company["primary_domain"]}},
                   {"object": "contact", "action": "create", "local_ref": {"type": "contact", "id": ct["id"]}, "properties": {"email": ct["email"], "full_name": ct["name"]}},
                   {"object": "deal", "action": "create", "local_ref": {"type": "opportunity", "id": oid}, "properties": {"dealname": opp["name"]}}]
            r = sess.call("create_proposal", type="crm_write", payload={"operations": ops}, evidence=ev_refs, rationale=a["rationale"], confidence=ctx.state["decide"]["confidence"], idempotency_key=f"{key}:crm")
            p_a = r["proposal_id"]
            c.execute("UPDATE ops.proposal SET group_id=id WHERE id=%s AND group_id IS NULL", (p_a,))
            created.append(("crm_write", p_a))
        elif t == "draft_message":
            purpose = p.get("purpose", "inbound_response")
            lead = c.execute("SELECT raw_payload FROM gtm.lead WHERE id=%s", (ev["lead_id"],)).fetchone() if ev.get("lead_id") else None
            raw = (lead or {}).get("raw_payload") or {}
            d = ctx.llm("draft_message", {"purpose": purpose, "contact": {"name": ct["name"]}, "company": acct["name"], "service_interest": raw.get("service_interest"),
                                          "source_ref": f"enquiry:{raw.get('enquiry_id')}" if raw else f"interaction:{ev.get('interaction_id')}",
                                          "untrusted": {"their_message": raw.get("message", "")}})
            dr = sess.call("create_draft", contact_id=ct["id"], purpose=purpose, content=d, sources=[x["source_ref"] for x in d["claims"]])
            if dr["screen"]["blocked"]:
                done.append({"index": i, "type": t, "skipped": "draft blocked by screen", "flags": dr["screen"]["flags"]}); continue
            payload = MessagePayload(contact_id=ct["id"], resolved_recipient=ct["email"], sender_identity=f"{owner.split(':', 1)[-1]}@corvane.example",
                                     subject=d["subject"], body=d["body"], claims=d["claims"]).model_dump()
            kw = dict(depends_on=p_a, group_id=p_a) if p_a else {}
            r = sess.call("create_proposal", type="message", payload=payload, evidence=ev_refs + [{"draft_id": dr["draft_id"]}], rationale=a["rationale"],
                          confidence=ctx.state["decide"]["confidence"], idempotency_key=f"{key}:msg",
                          target_entity={"purpose": "inbound_response" if purpose == "inbound_response" else "opportunity_followup"}, **kw)
            created.append(("message", r["proposal_id"]))
        elif t in ("recommend_task", "recommend_human_touch"):
            if t == "recommend_human_touch":
                sess.call("flag_risk", account_id=ctx.account_id, risk=p.get("reason", "human touch recommended"), evidence=ev_refs); done.append({"index": i, "type": t}); continue
            r = sess.call("create_proposal", type="task", payload={"owner": p.get("owner") or owner, "title": p["title"], "detail": p.get("detail")}, evidence=ev_refs,
                          rationale=a["rationale"], confidence=ctx.state["decide"]["confidence"], idempotency_key=f"{key}:task")
            created.append(("task", r["proposal_id"]))
        elif t == "propose_field_change":
            r = sess.call("create_proposal", type="field_change", payload=p, evidence=ev_refs, rationale=a["rationale"], confidence=ctx.state["decide"]["confidence"], idempotency_key=f"{key}:fc")
            created.append(("field_change", r["proposal_id"]))
        elif t == "update_agent_fields":
            ai_fields = dict(p)
        elif t == "flag_risk":
            sess.call("flag_risk", account_id=ctx.account_id, risk=p["risk"], evidence=p.get("evidence") or ev_refs)
        elif t == "request_enrichment":
            sess.call("request_enrichment", entity={"type": "account", "id": ctx.account_id}, fields=p.get("fields") or ["employee_count"], budget=min(float(p.get("budget", 0.5)), 1.0))
        done.append({"index": i, "type": t})
    # structured state (exact shapes consumed by the API/UI), then an optimistic patch
    dec = ctx.state["decide"]
    patch, ai = _build_state(ctx, dec, created, ev, ct)
    fields = {**ai_fields, **ai}
    sess.call("update_agent_fields", account_id=ctx.account_id, fields=fields)
    for attempt in (0, 1):
        ver = _state(c, ctx.account_id)["version"]
        try:
            new_version = sess.call("patch_agent_state", account_id=ctx.account_id, version=ver, patch=patch)["version"]; break
        except VersionConflict:
            if attempt:
                raise
    return {"done": done, "created": created, "superseded": superseded, "state_version": new_version, "pack_hash": ctx.state["pack"]["hash"]}


def _finish(ctx, reviewed: bool):
    now = ctx.clock.now()
    c = ctx.conn
    nxt = now + timedelta(days=HEARTBEAT_DAYS)
    sets, vals = "next_wake_at=%s, consecutive_failures=0", [nxt]
    if reviewed:
        sets += ", last_woken_at=%s, context_hash=%s"; vals += [now, ctx.state["pack"]["hash"]]
    c.execute(f"UPDATE gtm.account_agent_state SET {sets} WHERE account_id=%s", vals + [ctx.account_id])
    add_schedule(c, ctx.clock, "heartbeat", f"account:{ctx.account_id}", HEARTBEAT_DAYS * 86400, first_at=nxt)
    c.execute("UPDATE ops.schedule SET next_run_at=%s WHERE kind='heartbeat' AND target=%s", (nxt, f"account:{ctx.account_id}"))
    return {"next_wake_at": nxt.isoformat()}


def build_graph() -> Graph:
    g = Graph("account_wake", "1", lease=True, coalesce_seconds=60, coalesce_key=lambda env: f"account:{env.account_id}" if env.account_id else None)
    g.trigger("on_account_event", TRIGGERS)
    g.conditional("ready", lambda ctx: "yes" if lifecycle_filter(ctx.conn, ctx.trigger, "account_wake") else "no")
    g.code("load", _load, after="ready", when=("ready", "yes"))
    g.code("detect", _detect, after="load")
    g.conditional("gate", _gate, after="detect")
    g.code("idle", lambda ctx: {"model_call": False, **_finish(ctx, False)}, after="gate", when=("gate", "idle"))
    g.code("pack", _pack, after="gate", when=("gate", "model"))
    g.llm("decide", "account_decide", lambda ctx: ctx.state["pack"]["decide_input"], after="pack")
    g.code("validate", _validate, after="decide")
    g.code("apply", _apply, after="validate")
    g.code("schedule", lambda ctx: _finish(ctx, True), after="apply")
    return g
