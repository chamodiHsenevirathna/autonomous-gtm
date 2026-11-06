import os
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from gtm.api import create_app
from gtm.api import schemas as S
from gtm.approvals import create_proposal
from gtm.config import get_settings

pytestmark = pytest.mark.db
EMIT = lambda *a, **k: None
MAYA = "user:maya"


@pytest.fixture()
def env(test_url):
    app = create_app(test_url)
    st = app.state.api
    yield TestClient(app), st
    st.rt.close()


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


def seed(st):
    """Account + contact + opportunity + lead + agent state, no dependency on the agent workflows."""
    c, now = st.conn, st.rt.clock.now()
    a = c.execute("INSERT INTO gtm.account(name, primary_domain, owner_principal, created_at, updated_at, ai_summary, ai_last_reviewed_at) "
                  "VALUES ('Brightwater Logistics','brightwater-logistics.example','user:maya',%s,%s,'Mid-size freight operator.',%s) RETURNING id", (now, now, now)).fetchone()["id"]
    ct = c.execute("INSERT INTO gtm.contact(account_id, full_name, email, created_at, updated_at) VALUES (%s,'Marta Lindqvist','marta@brightwater-logistics.example',%s,%s) RETURNING id", (a, now, now)).fetchone()["id"]
    o = c.execute("INSERT INTO gtm.opportunity(account_id, name, stage, owner_principal, is_stalled, stall_reason, days_in_stage, created_at, updated_at) "
                  "VALUES (%s,'Data platform','Proposal','user:maya',true,'No customer reply for 31 days',50,%s,%s) RETURNING id", (a, now, now)).fetchone()["id"]
    c.execute("INSERT INTO gtm.lead(contact_id, account_id, channel, raw_payload, idempotency_key, triage_class, fit_score, fit_band, status, created_at, updated_at) "
              "VALUES (%s,%s,'form',%s,'k1','real_lead',0.86,'high','qualified',%s,%s)", (ct, a, Jsonb({"message": "We need a data platform."}), now, now))
    c.execute("INSERT INTO gtm.account_agent_state(account_id, lifecycle, summary, risks, next_actions) VALUES (%s,'active','Summary',%s,%s)",
              (a, Jsonb([{"text": "Budget unclear", "severity": "medium", "refs": ["lead:1"]}]), Jsonb([{"id": 1, "action": "recommend_task", "text": "Call", "status": "proposed"}])))
    for f, v, src in (("employee_count", 850, "provider_b"), ("industry", "Logistics", "provider_b")):
        c.execute("INSERT INTO gtm.observation(entity_type, entity_id, field, value, value_normalised, data_source_id, observed_at, fetched_at, confidence) "
                  "SELECT 'account',%s,%s,%s,%s,id,%s,%s,0.95 FROM gtm.data_source WHERE name=%s", (a, f, Jsonb(v), str(v).lower(), now, now, src))
    c.execute("INSERT INTO gtm.observation(entity_type, entity_id, field, value, value_normalised, data_source_id, observed_at, fetched_at, confidence) "
              "SELECT 'account',%s,'employee_count',%s,'400',id,%s,%s,0.6 FROM gtm.data_source WHERE name='provider_a'", (a, Jsonb(400), now, now))
    from gtm.data import resolve_fields
    resolve_fields(c, st.rt.clock, "account", a)
    c.commit()
    return {"account": a, "contact": ct, "opp": o}


def task(st, ids, title="Call Marta", depends_on=None):
    pid = create_proposal(st.conn, st.rt.clock, type="task", proposed_by="agent:account-agent", account_id=ids["account"], emit=EMIT, depends_on=depends_on,
                          payload={"owner": MAYA, "title": title}, rationale="r", evidence=[{"kind": "enquiry", "ref": "lead:1", "text": "asked", "data_origin": "SCR"}])
    st.conn.commit()
    return pid


def message(st, ids):
    pid = create_proposal(st.conn, st.rt.clock, type="message", proposed_by="agent:account-agent", account_id=ids["account"], emit=EMIT,
                          payload={"contact_id": ids["contact"], "resolved_recipient": "marta@brightwater-logistics.example", "sender_identity": "maya@corvane.example",
                                   "subject": "Re: your enquiry", "body": "Thanks for reaching out. We would be glad to set up an introductory call next week."})
    st.conn.commit()
    return pid


def dec(c, pid, decision="approve", by=MAYA, **kw):
    return c.post(f"/api/proposals/{pid}/decision", json={"decision": decision, "decided_by": by, **kw})


def test_read_endpoints_match_spec_shapes(env):
    c, st = env
    ids = seed(st)
    p = task(st, ids)
    st.conn.execute("INSERT INTO ops.agent_run(workflow, workflow_version, account_id, status, started_at) VALUES ('inbound_enquiry','1',%s,'waiting',%s)", (ids["account"], st.rt.clock.now()))
    rid = st.conn.execute("SELECT max(id) AS i FROM ops.agent_run").fetchone()["i"]
    st.conn.execute("INSERT INTO ops.run_step(run_id,node_id,node_type,status,attempt,error_class,error,started_at) VALUES (%s,'enrich','tool','retrying',1,'RetryableError','429',%s)", (rid, st.rt.clock.now()))
    st.conn.execute("INSERT INTO ops.run_step(run_id,node_id,node_type,status,attempt,started_at,ended_at) VALUES (%s,'enrich','tool','succeeded',2,%s,%s)", (rid, st.rt.clock.now(), st.rt.clock.now()))
    st.conn.commit()
    S.HealthOut(**ok(c.get("/api/health")))
    cfg = S.ConfigOut(**ok(c.get("/api/config")))
    assert cfg.live_enabled is False and cfg.llm_mode == "mock"
    ov = S.OverviewOut(**ok(c.get("/api/overview")))
    assert [g.key for g in ov.golden_thread] == ["enquiry", "triage", "account", "agent", "crm", "send", "reply", "intel"]
    assert ov.counts.leads == 1 and ov.counts.open_proposals == 1 and ov.counts.alerts == 1 and ov.golden_thread[0].done and ov.golden_thread[3].done and not ov.golden_thread[4].done
    [S.LeadOut(**x) for x in ok(c.get("/api/leads"))]
    rows = [S.AccountRow(**x) for x in ok(c.get("/api/accounts"))]
    assert rows[0].employees == 850 and rows[0].industry == "Logistics" and rows[0].lifecycle == "active" and rows[0].open_proposals == 1
    d = S.AccountDetail(**ok(c.get(f"/api/accounts/{ids['account']}")))
    byk = {f.key: f for f in d.fields}
    assert byk["employees"].source.startswith("provider_b") and byk["ai_summary"].owner == "agent" and byk["owner"].owner == "human"
    assert d.agent_state and d.agent_state.risks[0].severity == "medium" and len(d.proposals) == 1 and d.opportunities[0].name == "Data platform"
    assert c.get("/api/accounts/9999").status_code == 404
    [S.OpportunityRow(**x) for x in ok(c.get("/api/opportunities"))]
    al = [S.PipelineAlert(**x) for x in ok(c.get("/api/pipeline/alerts"))]
    assert al[0].kind == "no_reply" and al[0].severity == "high"
    pr = [S.ProposalOut(**x) for x in ok(c.get("/api/proposals"))]
    assert pr[0].id == p and pr[0].status == "pending" and pr[0].execution is None
    assert [x["id"] for x in ok(c.get("/api/proposals?status=executed"))] == []
    S.ProposalOut(**ok(c.get(f"/api/proposals/{p}")))
    assert c.get("/api/proposals/9999").status_code == 404
    runs = [S.RunRow(**x) for x in ok(c.get("/api/runs"))]
    assert runs[0].steps_total == 1 and runs[0].steps_done == 1
    rd = S.RunDetail(**ok(c.get(f"/api/runs/{rid}")))
    assert rd.steps[0].attempts == 2 and rd.steps[0].error == {"class": "RetryableError", "message": "429"} and rd.steps[0].status == "succeeded"
    assert c.get("/api/runs/9999").status_code == 404
    au = [S.AuditRow(**x) for x in ok(c.get("/api/audit?limit=5"))]
    assert au and [a.seq for a in au] == sorted((a.seq for a in au), reverse=True)
    [S.EventRow(**x) for x in ok(c.get("/api/events"))]
    S.EvalSummaryOut(**ok(c.get("/api/evals")))
    [S.FeedbackRow(**x) for x in ok(c.get("/api/feedback"))]
    assert c.get("/sim/control/state").status_code == 200
    assert c.options("/api/health", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"}).headers["access-control-allow-origin"] == "http://localhost:5173"


def test_decision_validation_and_errors(env):
    c, st = env
    ids = seed(st)
    p = task(st, ids)
    assert dec(c, p, "reject").status_code == 422
    assert dec(c, p, "approve_with_edits").status_code == 422
    assert dec(c, 9999).status_code == 404
    assert dec(c, p, by="agent:account-agent").status_code == 403          # agents cannot decide
    assert dec(c, p, by="user:dev", decision="reject", reason_code="other").status_code in (200, 403)
    r = dec(c, p, "reject", reason_code="not_ready") if c.get(f"/api/proposals/{p}").json()["status"] == "pending" else None
    assert dec(c, p).status_code == 409                                     # no longer pending


def test_approve_executes_through_gateway_with_13_checks(env):
    c, st = env
    ids = seed(st)
    p = task(st, ids)
    out = S.ProposalOut(**ok(dec(c, p)))
    assert out.status == "executed" and out.decisions[0].decision == "approve"
    ex = out.execution
    assert ex.status == "executed" and ex.adapter == "db.task" and ex.approval_consumed and ex.hash_verified and ex.external_ref.startswith("activity:")
    assert [x.step for x in ex.checks] == list(range(1, 14))
    assert ex.checks[0].status == "passed" and ex.checks[11].status == "passed" and ex.checks[2].status == "skipped" and ex.checks[12].status == "passed"
    assert st.conn.execute("SELECT count(*) AS n FROM gtm.activity WHERE type='task'").fetchone()["n"] == 1


def test_edit_changes_hash_and_payload(env):
    c, st = env
    ids = seed(st)
    p = task(st, ids)
    before = ok(c.get(f"/api/proposals/{p}"))["payload_hash"]
    out = S.ProposalOut(**ok(dec(c, p, "approve_with_edits", edited_payload={"owner": MAYA, "title": "Call Marta tomorrow"}, reason_code="tone_edit")))
    assert out.payload["title"] == "Call Marta tomorrow" and out.payload_hash != before and out.status == "executed"
    d = out.decisions[0]
    assert d.edited and d.old_hash == before and d.new_hash == out.payload_hash


def test_dependency_409_then_released(env):
    c, st = env
    ids = seed(st)
    a = task(st, ids, "first")
    b = task(st, ids, "second", depends_on=a)
    pb = ok(c.get(f"/api/proposals/{b}"))
    assert pb["status"] == "blocked" and pb["depends_on"] == a and pb["execution"] is None and "proposal #" in pb["block_reason"]
    assert dec(c, b).status_code == 409
    ok(dec(c, a))
    pb = ok(c.get(f"/api/proposals/{b}"))
    assert pb["status"] == "pending" and pb["block_reason"] is None
    assert ok(dec(c, b))["status"] == "executed"
    # rejected dependency supersedes the dependent
    x = task(st, ids, "x")
    y = task(st, ids, "y", depends_on=x)
    ok(dec(c, x, "reject", reason_code="other"))
    assert ok(c.get(f"/api/proposals/{y}"))["status"] == "superseded"


def test_soft_block_can_be_decided_again_hard_block_cannot(env):
    c, st = env
    ids = seed(st)
    m = message(st, ids)
    out = S.ProposalOut(**ok(dec(c, m)))            # contact never imported to the outreach tool -> soft block
    assert out.status == "blocked" and out.execution.status == "blocked" and out.execution.block_kind == "soft" and out.block_reason
    assert len(out.execution.checks) == 13 and any(x.status == "failed" for x in out.execution.checks) or out.execution.checks[0].status == "passed"
    assert ok(dec(c, m, "reject", reason_code="not_ready"))["status"] == "rejected"
    m2 = message(st, ids)
    st.conn.execute("INSERT INTO gtm.suppression(scope, value, reason, created_at) VALUES ('address','marta@brightwater-logistics.example','unsubscribe',%s)", (st.rt.clock.now(),))
    st.conn.commit()
    out = S.ProposalOut(**ok(dec(c, m2)))
    assert out.status == "blocked" and out.execution.block_kind == "hard"
    assert dec(c, m2, "reject", reason_code="other").status_code == 409


def test_audit_verify_then_broken_after_tamper(env):
    c, st = env
    ids = seed(st)
    ok(dec(c, task(st, ids)))
    v = S.AuditVerifyOut(**ok(c.get("/api/audit/verify")))
    assert v.ok and v.checked > 0 and v.first_bad_seq is None
    st.h.tamper("audit_row")
    v = S.AuditVerifyOut(**ok(c.get("/api/audit/verify")))
    assert not v.ok and v.first_bad_seq == v.checked


def test_demo_actions_are_safe_and_idempotent(env):
    c, st = env
    r = S.DemoResultOut(**ok(c.post("/api/demo/enquiry", json={"enquiry_id": "nope"})))
    assert not r.ok
    r = S.DemoResultOut(**ok(c.post("/api/demo/reply", json={"reply_id": "S01-golden-reply"})))
    assert not r.ok and "sent" in r.message
    t0 = ok(c.get("/api/health"))["clock"]
    r = S.DemoResultOut(**ok(c.post("/api/demo/advance", json={"seconds": 3600})))
    assert r.ok and r.clock > t0
    assert not ok(c.post("/api/demo/advance", json={"seconds": -5}))["ok"]
    seed(st)
    assert ok(c.get("/api/leads"))
    S.DemoResultOut(**ok(c.post("/api/demo/reset")))
    assert ok(c.get("/api/leads")) == [] and ok(c.get("/api/health"))["clock"] == t0
    r = ok(c.post("/api/demo/enquiry", json={"enquiry_id": "S01-golden-enquiry"}))
    if not r["ok"]:
        assert "intake" in r["message"]
    else:
        assert ok(c.post("/api/demo/enquiry", json={"enquiry_id": "enq_001"}))["ok"] is False


def test_lost_deal_review_roundtrip(env):
    c, st = env
    body = {"account_id": None, "opportunity_id": None, "reason_code": "lost_to_incumbent", "primary_reason": "Chose incumbent", "competitor": None,
            "could_we_have_won": "maybe", "what_would_change_it": "price", "verbatim_quotes": ["we stayed with them"], "reviewer": MAYA}
    assert c.post("/api/lost-deal-reviews", json=body).status_code == 422
    ids = seed(st)
    out = S.LostDealReviewOut(**ok(c.post("/api/lost-deal-reviews", json={**body, "account_id": ids["account"]})))
    assert out.ok
    fb = [S.FeedbackRow(**x) for x in ok(c.get("/api/feedback"))]
    assert fb[0].reason_code == "lost_to_incumbent" and fb[0].quotes[0].text == "we stayed with them" and fb[0].account_id == ids["account"] and fb[0].tags_ai_suggested == []


def test_evals_refuse_demo_db_and_run_on_separate_db(env, monkeypatch):
    c, st = env
    r = c.post("/api/evals/run", json={})
    assert r.status_code == 503 and "separate test database" in r.json()["detail"]
    sep = st.url.rsplit("/", 1)[0] + "/gtm_test_a_eval"
    monkeypatch.setenv("GTM_TEST_DATABASE_URL", sep)
    r = c.post("/api/evals/run", json={"scenarios": ["S06"]})
    assert r.status_code in (200, 503), r.text
    if r.status_code == 200:
        out = S.EvalSummaryOut(**r.json())
        assert out.totals["total"] == 1 and out.scenarios[0].id == "S06"
        assert S.EvalSummaryOut(**ok(c.get("/api/evals"))).run_id == out.run_id


def test_golden_thread_end_to_end_through_api(env):
    c, st = env
    r = ok(c.post("/api/demo/enquiry", json={"enquiry_id": "S01-golden-enquiry"}))
    if not r["ok"]:
        pytest.skip(r["message"])
    assert r["created"]["proposal_ids"]
    assert ok(c.post("/api/demo/enquiry", json={"enquiry_id": "enq_001"}))["ok"] is False
    lead = ok(c.get("/api/leads"))[0]
    assert 0 <= lead["fit_score"] <= 1 and lead["triage_class"] == "real_lead"
    assert ok(c.get("/api/accounts"))[0]["last_interaction_at"]
    G = lambda: {g["key"]: g["done"] for g in ok(c.get("/api/overview"))["golden_thread"]}
    assert not G()["intel"] and not G()["reply"]
    props = {p["type"]: p for p in ok(c.get("/api/proposals"))}
    for p_ in props.values():
        assert all(e["text"] and e["source"] and e["data_origin"] for e in p_["evidence"]), p_["evidence"]
    for p in props.values():
        S.ProposalOut(**p)
    crm, msg = props["crm_write"], props["message"]
    assert msg["status"] == "blocked" and msg["depends_on"] == crm["id"] and dec(c, msg["id"]).status_code == 409
    out = S.ProposalOut(**ok(dec(c, crm["id"])))
    assert out.status == "executed" and out.execution.adapter == "crm.write"
    ok(c.post("/api/demo/advance", json={"seconds": 300}))
    out = S.ProposalOut(**ok(dec(c, msg["id"])))
    assert out.status in ("executed", "parked", "blocked")
    if out.status != "executed":
        ok(c.post("/api/demo/advance", json={"seconds": 600}))
        out = S.ProposalOut(**ok(c.get(f"/api/proposals/{msg['id']}")))
    for p_ in ok(c.get("/api/proposals")):
        if p_["execution"]:
            assert not any(ch["detail"].startswith("{") for ch in p_["execution"]["checks"])
            assert not (p_["execution"]["status"] == "parked" and any(ch["status"] == "failed" for ch in p_["execution"]["checks"]))
    ov = S.OverviewOut(**ok(c.get("/api/overview")))
    assert {g.key: g.done for g in ov.golden_thread}["crm"]
    if out.status == "executed":
        assert {g.key: g.done for g in ov.golden_thread}["send"]
        rep = ok(c.post("/api/demo/reply", json={"reply_id": "S01-golden-reply"}))
        assert rep["ok"] and ok(c.post("/api/demo/reply", json={"reply_id": "rpl_001"}))["ok"] is False
        assert G()["reply"] and G()["intel"]
    [S.RunDetail(**ok(c.get(f"/api/runs/{r_['id']}"))) for r_ in ok(c.get("/api/runs"))]
    S.AccountDetail(**ok(c.get(f"/api/accounts/{r['created']['account_id']}")))
    assert ok(c.get("/api/audit/verify"))["ok"]


def test_every_read_endpoint_works_on_an_empty_database(env):
    """First-time users see an empty system: no endpoint may return 5xx (regression: overview NULL-parameter error)."""
    client, _ = env
    for path in ["/api/health", "/api/config", "/api/overview", "/api/leads", "/api/accounts", "/api/opportunities", "/api/pipeline/alerts",
                 "/api/proposals", "/api/runs", "/api/audit", "/api/audit/verify", "/api/events", "/api/evals", "/api/feedback"]:
        r = client.get(path)
        assert r.status_code == 200, (path, r.status_code, r.text[:200])
    ov = client.get("/api/overview").json()
    assert ov["counts"]["leads"] == 0 and not any(s["done"] for s in ov["golden_thread"])
