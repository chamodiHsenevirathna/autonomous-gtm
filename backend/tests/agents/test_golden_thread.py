"""Golden thread end to end: enquiry -> intake -> account wake -> two linked proposals -> human approval -> gateway (sync lag) ->
reply -> sim_ingest -> account wake -> next proposal. Real sims, real gateway, mock model (SIMULATED)."""
from datetime import timedelta
from gtm import audit
from gtm.agents.ingest import pull_and_route
from gtm.approvals import decide


def test_golden_thread(system):
    s, c, clock = system, system.conn, system.clock
    lead = s.enquiry("enq_001")
    s.run(advance_clock=False)
    row = c.execute("SELECT * FROM gtm.lead WHERE id=%s", (lead,)).fetchone()
    assert row["status"] == "qualified" and row["fit_band"] == "high" and row["raw_payload"]["enquiry_id"] == "enq_001", row
    props = s.q("SELECT * FROM ops.proposal ORDER BY id")
    assert [p["type"] for p in props] == ["crm_write", "message", "task"] or {"crm_write", "message"} <= {p["type"] for p in props}
    pa = next(p for p in props if p["type"] == "crm_write")
    pb = next(p for p in props if p["type"] == "message")
    assert pa["status"] == pb["status"] == "pending" and pb["depends_on_proposal_id"] == pa["id"] and len(pa["payload_hash"]) == 64
    assert pb["target_entity"] == {"purpose": "inbound_response"} and pb["proposed_by"] == "agent:account-agent"
    assert s.q("SELECT 1 FROM ops.execution") == []            # nothing happened without approval
    st = c.execute("SELECT * FROM gtm.account_agent_state WHERE account_id=%s", (pa["account_id"],)).fetchone()
    v1 = st["version"]
    assert v1 >= 2 and st["lifecycle"] == "active"
    assert c.execute("SELECT ai_summary FROM gtm.account WHERE id=%s", (pa["account_id"],)).fetchone()["ai_summary"]
    assert s.q("SELECT 1 FROM ops.schedule WHERE kind='heartbeat'")
    # human approval (execute_proposal starts only after proposal.approved)
    for p in (pa, pb):
        decide(c, clock, proposal_id=p["id"], decided_by="user:maya", decision="approve")
    c.commit()
    s.run()                                                      # advance clock through the sync lag
    assert c.execute("SELECT status FROM ops.proposal WHERE id=%s", (pa["id"],)).fetchone()["status"] == "executed"
    assert c.execute("SELECT status FROM ops.proposal WHERE id=%s", (pb["id"],)).fetchone()["status"] == "executed"
    assert s.q("SELECT 1 FROM ops.run_step WHERE status='parked'"), "message waited on sync lag"
    # scripted reply -> ingest -> account wake
    ct = c.execute("SELECT email FROM gtm.contact WHERE id=%s", (pb["payload"]["contact_id"],)).fetchone()
    s.sims.control.script("rpl_001", clock.now() + timedelta(seconds=10), to_email=ct["email"])
    clock.advance(seconds=30)
    assert pull_and_route(c, clock, s.services)["routed"] >= 1
    assert pull_and_route(c, clock, s.services)["routed"] == 0       # idempotent
    s.run()
    st2 = c.execute("SELECT * FROM gtm.account_agent_state WHERE account_id=%s", (pa["account_id"],)).fetchone()
    assert st2["version"] > v1
    nxt = s.q("SELECT * FROM ops.proposal WHERE status='pending' AND id > %s", pb["id"])
    assert any(p["type"] == "message" for p in nxt)
    # safety
    assert audit.verify_chain(c)[0]
    try:
        from gtm.eval.invariants import check_all
    except ImportError:
        return
    bad = [r for r in check_all(c) if not r.passed]
    assert not bad, [(r.name, r.violations[:2]) for r in bad]


def test_held_enquiries_never_produce_proposals(system):
    for e in ("enq_008", "enq_009", "enq_010", "enq_013"):
        system.enquiry(e)
    system.run(advance_clock=False)
    leads = system.q("SELECT status, held_reason FROM gtm.lead ORDER BY id")
    assert [l["status"] for l in leads] == ["held"] * 4, leads
    assert leads[3]["held_reason"] == "injection_suspected"
    assert system.q("SELECT 1 FROM ops.proposal") == [] and system.q("SELECT 1 FROM gtm.account") == []
    assert system.q("SELECT 1 FROM gtm.lead")  # never destroyed


def test_duplicate_enquiry_does_not_create_second_contact(system):
    system.enquiry("enq_002"); system.run(advance_clock=False)
    system.enquiry("enq_003"); system.run(advance_clock=False)
    assert len(system.q("SELECT 1 FROM gtm.contact WHERE lower(email)='viktor.quinn@wexcombe-farms.example'")) == 1
    assert len(system.q("SELECT 1 FROM ops.proposal WHERE type='crm_write'")) <= 1      # never two CRM creates for one account
    assert len(system.q("SELECT 1 FROM gtm.lead")) == 2


def test_state_shapes_after_golden_thread_and_reply(system):
    s, c, clock = system, system.conn, system.clock
    s.enquiry("enq_001"); s.run(advance_clock=False)
    pa, pb = (c.execute("SELECT * FROM ops.proposal WHERE type=%s", (t,)).fetchone() for t in ("crm_write", "message"))
    for p in (pa, pb):
        decide(c, clock, proposal_id=p["id"], decided_by="user:maya", decision="approve")
    c.commit(); s.run()
    ct = c.execute("SELECT email FROM gtm.contact WHERE id=%s", (pb["payload"]["contact_id"],)).fetchone()
    s.sims.control.script("rpl_001", clock.now() + timedelta(seconds=10), to_email=ct["email"])
    clock.advance(seconds=30); pull_and_route(c, clock, s.services); s.run()
    st = c.execute("SELECT * FROM gtm.account_agent_state WHERE account_id=%s", (pa["account_id"],)).fetchone()
    marta = next(x for x in st["stakeholder_map"] if "Marta" in x["name"])
    assert set(marta) == {"name", "role", "stance", "source_ref"} and marta["stance"] == "champion" and marta["source_ref"].startswith("interaction:")
    for r in st["risks"]:
        assert set(r) == {"text", "severity", "refs"} and r["severity"] in ("low", "medium", "high") and isinstance(r["refs"], list)
    com = st["commitments"]
    assert all(set(x) == {"party", "text", "due", "status", "refs"} and x["status"] in ("open", "proposed", "done") for x in com)
    assert any(x["party"] == "customer" and x["text"] == "Customer open to a call" and x["status"] == "proposed" for x in com)
    assert any(x["party"] == "us" and x["status"] == "done" for x in com)
    assert st["open_questions"] and all(isinstance(q, str) for q in st["open_questions"])
    na = st["next_actions"]
    assert all(set(a) == {"id", "action", "text", "status", "proposal_id", "rationale"} and a["status"] in ("proposed", "pending_approval", "done", "dismissed") and a["text"] for a in na)
    assert any(a["action"] == "propose_crm_create" and a["status"] == "done" for a in na) and not any(a["action"] == "no_action" for a in na)
    assert any(a["action"] == "draft_message" and a["status"] == "pending_approval" for a in na)
    assert len({a["id"] for a in na}) == len(na) and all(isinstance(a["id"], int) for a in na)
    assert st["hypotheses"] and all(set(h) == {"text", "would_change_mind", "evidence_refs"} for h in st["hypotheses"]) and len(st["hypotheses"]) >= 2
    ai = c.execute("SELECT ai_next_action FROM gtm.account WHERE id=%s", (pa["account_id"],)).fetchone()["ai_next_action"]
    assert ai == next(a["text"] for a in na if a["status"] == "pending_approval")
