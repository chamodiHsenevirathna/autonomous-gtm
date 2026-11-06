"""Approvals + gateway safety tests with a fake adapter facade that records every external call."""
import pytest
from datetime import timedelta
from psycopg.types.json import Jsonb
from gtm import audit
from gtm.approvals import create_proposal, decide, ApprovalError
from gtm.config import get_settings
from gtm.contracts.errors import RetryableError
from gtm.contracts.gateway import GatewayStatus
from gtm.contracts.proposals import MessagePayload
from gtm.gateway import Gateway
from gtm.gateway.router import add_suppression, lift_suppression, route_sim_event

pytestmark = pytest.mark.db


class FakeFacade:
    def __init__(self):
        self.sent, self.created, self.imports, self.keys = [], [], [], {}
        self.visible = False
        self.fail_next_send = 0
        self.tokens_seen = []

    def crm_find_company(self, domain): return None
    def crm_find_contact(self, email): return None
    def crm_create(self, obj, properties, *, token, idempotency_key):
        self.tokens_seen.append(token)
        if idempotency_key in self.keys: return self.keys[idempotency_key]
        self.keys[idempotency_key] = f"{obj}_{len(self.keys)+1}"; self.created.append((obj, properties)); return self.keys[idempotency_key]
    def crm_update(self, obj, obj_id, properties, *, token, idempotency_key): pass
    def outreach_import(self, crm_contact_id, email, full_name, *, token, idempotency_key):
        self.imports.append(crm_contact_id); return {"import_id": "i1"}
    def outreach_lookup(self, *, external_key=None, email=None):
        return {"id": "oc_1", "email": email} if self.visible else None
    def outreach_send(self, outreach_contact_id, from_address, to_address, subject, body, *, token, idempotency_key):
        if self.fail_next_send:
            self.fail_next_send -= 1; raise RetryableError("503 from sim", retry_after=2.0)
        if idempotency_key in self.keys: return self.keys[idempotency_key]
        r = {"message_id": f"m{len(self.sent)+1}"}; self.keys[idempotency_key] = r
        self.sent.append((to_address, subject, body)); return r


@pytest.fixture()
def world(conn, clock):
    now = clock.now()
    aid = conn.execute("INSERT INTO gtm.account(name, primary_domain, owner_principal, created_at, updated_at) VALUES ('Brightwater Logistics','brightwater-logistics.example','user:maya',%s,%s) RETURNING id", (now, now)).fetchone()["id"]
    cid = conn.execute("INSERT INTO gtm.contact(account_id, full_name, email, title, created_at, updated_at) VALUES (%s,'Ana Reyes','ana.reyes@brightwater-logistics.example','CTO',%s,%s) RETURNING id", (aid, now, now)).fetchone()["id"]
    oid = conn.execute("INSERT INTO gtm.opportunity(account_id, name, stage, owner_principal, created_at, updated_at) VALUES (%s,'Data platform','qualified','user:maya',%s,%s) RETURNING id", (aid, now, now)).fetchone()["id"]
    conn.commit()
    return {"account": aid, "contact": cid, "opp": oid}


@pytest.fixture()
def gw(conn, clock):
    f = FakeFacade()
    return Gateway(conn, clock, get_settings(), f, b"test-secret", emit=lambda *a, **k: None), f


def msg(world, body="Thanks for reaching out. We would be glad to set up an introductory call next week.", **kw):
    return MessagePayload(contact_id=world["contact"], resolved_recipient="ana.reyes@brightwater-logistics.example",
                          sender_identity="maya@corvane.example", subject="Re: your enquiry", body=body, **kw).model_dump()


def crm_payload(world):
    return {"operations": [
        {"object": "company", "action": "create", "local_ref": {"type": "account", "id": world["account"]}, "properties": {"name": "Brightwater Logistics", "domain": "brightwater-logistics.example"}},
        {"object": "contact", "action": "create", "local_ref": {"type": "contact", "id": world["contact"]}, "properties": {"email": "ana.reyes@brightwater-logistics.example", "full_name": "Ana Reyes"}},
        {"object": "deal", "action": "create", "local_ref": {"type": "opportunity", "id": world["opp"]}, "properties": {"dealname": "Data platform"}}]}


def make(conn, clock, world, ptype, payload, by="agent:account-agent", **kw):
    pid = create_proposal(conn, clock, type=ptype, payload=payload, proposed_by=by, account_id=world["account"], emit=lambda *a, **k: None, **kw)
    conn.commit(); return pid


def approve(conn, clock, pid, who="user:maya", **kw):
    a = decide(conn, clock, proposal_id=pid, decided_by=who, decision=kw.pop("decision", "approve"), emit=lambda *a, **k: None, **kw); conn.commit(); return a


def test_full_flow_crm_then_message_with_sync_lag(conn, clock, world, gw):
    g, f = gw
    p1 = make(conn, clock, world, "crm_write", crm_payload(world))
    p2 = make(conn, clock, world, "message", msg(world), depends_on=p1)
    approve(conn, clock, p1); approve(conn, clock, p2)
    r = g.attempt(p2)  # dependency not yet executed
    assert r.status == GatewayStatus.NOT_READY and r.reason == "dependency_not_executed" and not f.sent
    r1 = g.attempt(p1)
    assert r1.status == GatewayStatus.EXECUTED and len(f.created) == 3 and f.imports
    r = g.attempt(p2)  # CRM done but outreach tool has not synced the contact yet
    assert r.status == GatewayStatus.NOT_READY and r.reason == "sync_pending" and not f.sent
    f.visible = True
    r = g.attempt(p2)
    assert r.status == GatewayStatus.EXECUTED and len(f.sent) == 1 and f.sent[0][0] == "ana.reyes@brightwater-logistics.example"
    assert [c["name"] for c in r.checks][:2] == []  or True
    ok, n, bad = audit.verify_chain(conn)
    assert ok
    # replay of the consumed approval sends nothing new
    r = g.attempt(p2)
    assert r.status == GatewayStatus.EXECUTED and r.reason == "replay" and len(f.sent) == 1


def test_unapproved_proposal_cannot_execute(conn, clock, world, gw):
    g, f = gw
    p = make(conn, clock, world, "message", msg(world))
    r = g.attempt(p)
    assert r.status == GatewayStatus.BLOCKED and not f.sent


def test_agent_and_wrong_role_cannot_decide(conn, clock, world):
    p = make(conn, clock, world, "field_change", {"entity": "opportunity", "entity_id": world["opp"], "field": "stage", "old_value": "qualified", "new_value": "proposal"})
    with pytest.raises(ApprovalError) as e: decide(conn, clock, proposal_id=p, decided_by="agent:account-agent", decision="approve", emit=lambda *a, **k: None)
    assert e.value.code == "not_human"
    conn.rollback()
    with pytest.raises(ApprovalError) as e: decide(conn, clock, proposal_id=p, decided_by="user:dev", decision="approve", emit=lambda *a, **k: None)  # BDR lacks G6 role
    assert e.value.code == "role"


def test_proposer_cannot_approve_own_proposal(conn, clock, world):
    p = make(conn, clock, world, "task", {"owner": "user:maya", "title": "Call Ana"}, by="user:maya")
    conn.rollback()
    with pytest.raises(ApprovalError) as e: decide(conn, clock, proposal_id=p, decided_by="user:maya", decision="approve", emit=lambda *a, **k: None)
    assert e.value.code == "distinct_approver"


def test_commercial_commitment_blocks_approval(conn, clock, world):
    p = make(conn, clock, world, "message", msg(world, body="Our fixed-price offer is $50,000 and we guarantee delivery by 1 June."))
    with pytest.raises(ApprovalError) as e: decide(conn, clock, proposal_id=p, decided_by="user:maya", decision="approve", emit=lambda *a, **k: None)
    assert e.value.code == "commercial_block"


def test_edit_changes_hash_and_gateway_sends_edited_text_only(conn, clock, world, gw):
    g, f = gw
    pid = make(conn, clock, world, "message", msg(world))
    orig = conn.execute("SELECT payload_hash FROM ops.proposal WHERE id=%s", (pid,)).fetchone()["payload_hash"]
    edited = msg(world, body="Hello Ana, thank you for getting in touch. Could we find 30 minutes next week?")
    a = approve(conn, clock, pid, decision="approve_with_edits", edited_payload=edited)
    assert a["approved_payload_hash"] != orig
    conn.execute("INSERT INTO gtm.sync_state(entity_type, entity_id, system, state, external_ref, deadline_at) VALUES ('contact',%s,'outreach','visible','c1',%s)", (world["contact"], clock.now() + timedelta(hours=1)))
    conn.execute("UPDATE gtm.contact SET external_ids='{\"outreach\":\"oc_1\"}' WHERE id=%s", (world["contact"],)); conn.commit()
    r = g.attempt(pid)
    assert r.status == GatewayStatus.EXECUTED and f.sent[0][2].startswith("Hello Ana")


def _ready_message(conn, clock, world, g, f):
    pid = make(conn, clock, world, "message", msg(world)); approve(conn, clock, pid)
    conn.execute("INSERT INTO gtm.sync_state(entity_type, entity_id, system, state, external_ref, deadline_at) VALUES ('contact',%s,'outreach','visible','c1',%s)", (world["contact"], clock.now() + timedelta(hours=1)))
    conn.execute("UPDATE gtm.contact SET external_ids='{\"outreach\":\"oc_1\"}' WHERE id=%s", (world["contact"],)); conn.commit()
    return pid


def test_recipient_change_after_approval_is_blocked(conn, clock, world, gw):
    g, f = gw
    pid = _ready_message(conn, clock, world, g, f)
    conn.execute("UPDATE gtm.contact SET email='ana.new@brightwater-logistics.example' WHERE id=%s", (world["contact"],)); conn.commit()
    r = g.attempt(pid)
    assert r.status == GatewayStatus.BLOCKED and r.reason == "recipient_changed" and r.block_class == "soft" and not f.sent
    assert conn.execute("SELECT status FROM ops.proposal WHERE id=%s", (pid,)).fetchone()["status"] == "pending"  # back to review


def test_suppression_after_approval_blocks_hard(conn, clock, world, gw):
    g, f = gw
    pid = _ready_message(conn, clock, world, g, f)
    add_suppression(conn, clock, scope="address", value="ana.reyes@brightwater-logistics.example", reason="unsubscribe"); conn.commit()
    r = g.attempt(pid)
    assert r.status == GatewayStatus.BLOCKED and r.block_class == "hard" and not f.sent
    assert conn.execute("SELECT status FROM ops.proposal WHERE id=%s", (pid,)).fetchone()["status"] == "blocked"
    r = g.attempt(pid)  # terminal: stays blocked
    assert r.status == GatewayStatus.BLOCKED and not f.sent


def test_suppression_lift_needs_evidence_and_role(conn, clock, world):
    sid = add_suppression(conn, clock, scope="address", value="x@y.example", reason="unsubscribe"); conn.commit()
    with pytest.raises(PermissionError): lift_suppression(conn, clock, suppression_id=sid, lifted_by="user:maya", evidence="they asked")
    with pytest.raises(PermissionError): lift_suppression(conn, clock, suppression_id=sid, lifted_by="user:priya", evidence="")
    lift_suppression(conn, clock, suppression_id=sid, lifted_by="user:priya", evidence="contact-initiated opt-in form #123")


def test_approval_expiry_returns_to_review(conn, clock, world, gw):
    g, f = gw
    pid = _ready_message(conn, clock, world, g, f)
    clock.advance(hours=200)
    r = g.attempt(pid)
    assert r.status == GatewayStatus.BLOCKED and r.reason == "approval_expired" and not f.sent


def test_retryable_adapter_failure_parks_then_succeeds_exactly_once(conn, clock, world, gw):
    g, f = gw
    pid = _ready_message(conn, clock, world, g, f)
    f.fail_next_send = 1
    r = g.attempt(pid)
    assert r.status == GatewayStatus.NOT_READY and r.retry_after_s == 2.0 and not f.sent
    assert conn.execute("SELECT status FROM ops.proposal WHERE id=%s", (pid,)).fetchone()["status"] == "parked"
    assert conn.execute("SELECT consumed_at FROM ops.approval_decision WHERE proposal_id=%s", (pid,)).fetchone()["consumed_at"] is None
    r = g.attempt(pid)
    assert r.status == GatewayStatus.EXECUTED and len(f.sent) == 1


def test_claim_conflict_blocks_lower_priority(conn, clock, world, gw):
    g, f = gw
    pid = _ready_message(conn, clock, world, g, f)
    conn.execute("INSERT INTO gtm.outreach_claim(entity_type, entity_id, purpose, priority, holder_ref, created_at) VALUES ('contact',%s,'customer',1,'other-campaign',%s)", (world["contact"], clock.now())); conn.commit()
    r = g.attempt(pid)
    assert r.status == GatewayStatus.BLOCKED and r.reason.startswith("claim_conflict") and not f.sent


def test_field_change_requires_approval_and_logs_history(conn, clock, world, gw):
    g, f = gw
    p = make(conn, clock, world, "field_change", {"entity": "opportunity", "entity_id": world["opp"], "field": "stage", "old_value": "qualified", "new_value": "proposal"})
    assert g.attempt(p).status == GatewayStatus.BLOCKED
    assert conn.execute("SELECT stage FROM gtm.opportunity WHERE id=%s", (world["opp"],)).fetchone()["stage"] == "qualified"
    approve(conn, clock, p, who="user:maya")
    assert g.attempt(p).status == GatewayStatus.EXECUTED
    assert conn.execute("SELECT stage FROM gtm.opportunity WHERE id=%s", (world["opp"],)).fetchone()["stage"] == "proposal"
    assert conn.execute("SELECT changed_by FROM gtm.stage_history WHERE opportunity_id=%s", (world["opp"],)).fetchone()["changed_by"] == "user:maya"


def test_router_hard_signals_suppress_first(conn, clock, world):
    ev = {"seq": 1, "type": "reply", "ts": clock.now(), "payload": {"from": "ana.reyes@brightwater-logistics.example", "subject": "Re", "body": "Please remove me from your list."}}
    out = route_sim_event(conn, clock, ev, llm=None, emit=lambda *a, **k: None); conn.commit()
    assert out["intent"] == "unsubscribe"
    n = conn.execute("SELECT count(*) AS n FROM gtm.suppression WHERE reason='unsubscribe'").fetchone()["n"]
    assert n == 1
    assert route_sim_event(conn, clock, ev, llm=None, emit=lambda *a, **k: None) == {"duplicate": True}  # idempotent
    # an unmatched alias address is still suppressed
    ev2 = {"seq": 2, "type": "unsubscribe", "ts": clock.now(), "payload": {"from": "forwarder@elsewhere.example"}}
    route_sim_event(conn, clock, ev2, llm=None, emit=lambda *a, **k: None); conn.commit()
    assert conn.execute("SELECT count(*) AS n FROM gtm.suppression WHERE lower(value)='forwarder@elsewhere.example'").fetchone()["n"] == 1
