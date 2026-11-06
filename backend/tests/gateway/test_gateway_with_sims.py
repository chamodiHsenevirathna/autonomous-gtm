"""Gateway wired to the REAL simulated CRM/outreach adapters on a shared SimClock (CRM-to-outreach sync lag, scripted reply)."""
import pytest
from gtm import audit
from gtm.approvals import create_proposal, decide
from gtm.config import get_settings
from gtm.contracts.errors import PolicyDenied
from gtm.contracts.gateway import GatewayStatus
from gtm.contracts.proposals import MessagePayload
from gtm.gateway import Gateway, SimFacade
from gtm.gateway.router import route_sim_event
from gtm.sims import build_sims
from gtm.world import generate_world

pytestmark = pytest.mark.db
SECRET = b"integration-secret"
NOEMIT = lambda *a, **k: None


def test_golden_execution_with_sync_lag_and_reply(conn, clock):
    world = generate_world(42)
    sims = build_sims(world, clock)
    ad = sims.clients(token_secret=SECRET)
    gw = Gateway(conn, clock, get_settings(), SimFacade(ad), SECRET, emit=NOEMIT)
    enq = next(e for e in world.enquiries if e.id == "enq_001")
    now = clock.now()
    aid = conn.execute("INSERT INTO gtm.account(name, primary_domain, owner_principal, created_at, updated_at) VALUES (%s,%s,'user:maya',%s,%s) RETURNING id", ("Brightwater Logistics", "brightwater-logistics.example", now, now)).fetchone()["id"]
    cid = conn.execute("INSERT INTO gtm.contact(account_id, full_name, email, title, created_at, updated_at) VALUES (%s,%s,%s,'VP Data and Analytics',%s,%s) RETURNING id", (aid, enq.full_name, enq.email, now, now)).fetchone()["id"]
    oid = conn.execute("INSERT INTO gtm.opportunity(account_id, name, stage, owner_principal, created_at, updated_at) VALUES (%s,'Data platform','qualified','user:maya',%s,%s) RETURNING id", (aid, now, now)).fetchone()["id"]
    conn.commit()
    crm = {"operations": [
        {"object": "company", "action": "create", "local_ref": {"type": "account", "id": aid}, "properties": {"name": "Brightwater Logistics", "domain": "brightwater-logistics.example"}},
        {"object": "contact", "action": "create", "local_ref": {"type": "contact", "id": cid}, "properties": {"email": enq.email, "full_name": enq.full_name}},
        {"object": "deal", "action": "create", "local_ref": {"type": "opportunity", "id": oid}, "properties": {"dealname": "Data platform"}}]}
    p1 = create_proposal(conn, clock, type="crm_write", payload=crm, proposed_by="agent:account-agent", account_id=aid, emit=NOEMIT)
    body = "Hello Marta, thank you for getting in touch about your telematics data. Could we find 30 minutes next week to talk it through?"
    p2 = create_proposal(conn, clock, type="message", depends_on=p1, account_id=aid, proposed_by="agent:account-agent", emit=NOEMIT,
                         payload=MessagePayload(contact_id=cid, resolved_recipient=enq.email, sender_identity="maya@corvane.example", subject="Re: your enquiry", body=body).model_dump())
    conn.commit()
    for p in (p1, p2):
        decide(conn, clock, proposal_id=p, decided_by="user:maya", decision="approve", emit=NOEMIT)
    conn.commit()
    assert gw.attempt(p1).status == GatewayStatus.EXECUTED
    r = gw.attempt(p2)
    assert r.status == GatewayStatus.NOT_READY and r.reason == "sync_pending"   # CRM contact exists, outreach tool has not synced it yet
    clock.advance(300)                                                           # simulated time passes; sync completes
    r = gw.attempt(p2)
    assert r.status == GatewayStatus.EXECUTED, (r.status, r.reason, r.checks)
    # scripted customer reply arrives
    sims.script_reply("rpl_001", to_email=enq.email)
    clock.advance(6000)
    evs = ad.outreach.events(0)
    kinds = [e.type for e in evs]
    assert "reply" in kinds, kinds
    for e in evs:
        route_sim_event(conn, clock, e.model_dump(), llm=None, emit=NOEMIT)
    conn.commit()
    assert conn.execute("SELECT count(*) AS n FROM gtm.interaction WHERE direction='inbound'").fetchone()["n"] >= 1
    assert audit.verify_chain(conn)[0]


def test_adapter_refuses_call_without_gateway_token(conn, clock):
    world = generate_world(42)
    ad = build_sims(world, clock).clients(token_secret=SECRET)
    with pytest.raises(PolicyDenied):
        ad.outreach.send("oc_x", "a@corvane.example", "b@x.example", "s", "b", token=None, idempotency_key="k")
    with pytest.raises(PolicyDenied):
        ad.crm.create("contacts", {"email": "x@y.example"}, token=None, idempotency_key="k")
