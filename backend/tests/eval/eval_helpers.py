"""Row builders for evaluation tests (hand-inserted rows; no system under test needed)."""
from __future__ import annotations
from datetime import timedelta
from psycopg.types.json import Jsonb
from gtm import audit
from gtm.contracts.proposals import payload_hash

MSG = {"channel": "email", "contact_id": 1, "resolved_recipient": "a@x.example", "sender_identity": "maya@corvane.example",
       "subject": "Hi", "body": "Hello", "links": [], "attachments": [], "claims": []}


def mk_proposal(conn, clock, *, ptype="message", gate="G5", payload=None, status="executed", by="agent:account-agent",
                account_id=None, block_class=None) -> int:
    payload = payload if payload is not None else dict(MSG)
    pid = conn.execute(
        "INSERT INTO ops.proposal(type, gate_id, account_id, payload, payload_hash, proposed_by, status, block_class, created_at) "
        "VALUES (%s,%s,%s,%s,'x',%s,%s,%s,%s) RETURNING id",
        (ptype, gate, account_id, Jsonb(payload), by, status, block_class, clock.now())).fetchone()["id"]
    conn.execute("UPDATE ops.proposal SET payload_hash=%s WHERE id=%s", (payload_hash(pid, ptype, payload), pid))
    return pid


def mk_approval(conn, clock, pid, *, decision="approve", by="user:maya", consumed=True, expires_in=3600, payload=None, hash_=None) -> int:
    row = conn.execute("SELECT type, payload, payload_hash FROM ops.proposal WHERE id=%s", (pid,)).fetchone()
    payload = payload if payload is not None else row["payload"]
    h = hash_ or (row["payload_hash"] if payload == row["payload"] else payload_hash(pid, row["type"], payload))
    now = clock.now()
    return conn.execute(
        "INSERT INTO ops.approval_decision(proposal_id, decided_by, decision, approved_payload, approved_payload_hash, decided_at, expires_at, consumed_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (pid, by, decision, Jsonb(payload), h, now, now + timedelta(seconds=expires_in), now if consumed else None)).fetchone()["id"]


def mk_execution(conn, clock, pid, aid, *, key=None, adapter="outreach.send", status="succeeded", result=None, after_s=10) -> int:
    result = {"to_address": "a@x.example"} if result is None else result
    return conn.execute(
        "INSERT INTO ops.execution(proposal_id, approval_id, idempotency_key, adapter, status, result, executed_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (pid, aid, key or f"idem-{pid}-{adapter}-{status}-{after_s}", adapter, status, Jsonb(result),
         clock.now() + timedelta(seconds=after_s))).fetchone()["id"]


def mk_audit(conn, clock, event_type, *, pid=None, actor_type="system", actor_id="system:gateway", entity_ref=None, data=None):
    return audit.append(conn, clock, actor_type=actor_type, actor_id=actor_id, event_type=event_type, proposal_id=pid,
                        entity_ref=entity_ref, data=data or {})


def golden(conn, clock) -> dict:
    """A fully compliant history: message proposed, approved, executed, audited; one in-profile tool call."""
    pid = mk_proposal(conn, clock)
    mk_audit(conn, clock, "proposal.created", pid=pid)
    aid = mk_approval(conn, clock, pid)
    mk_audit(conn, clock, "proposal.approved", pid=pid, actor_type="human", actor_id="user:maya")
    xid = mk_execution(conn, clock, pid, aid)
    mk_audit(conn, clock, "proposal.executed", pid=pid)
    conn.execute("INSERT INTO ops.tool_call(principal, tool_name, permitted, at) VALUES ('agent:account-agent','get_account_context',true,%s)",
                 (clock.now(),))
    conn.commit()
    return {"pid": pid, "aid": aid, "xid": xid}


def mk_opportunity(conn, clock) -> int:
    aid = conn.execute("INSERT INTO gtm.account(name, primary_domain, created_at, updated_at) VALUES ('Acme','acme.example',%s,%s) RETURNING id",
                       (clock.now(), clock.now())).fetchone()["id"]
    return conn.execute("INSERT INTO gtm.opportunity(account_id, name, created_at, updated_at) VALUES (%s,'Opp',%s,%s) RETURNING id",
                        (aid, clock.now(), clock.now())).fetchone()["id"]


def small_world():
    from gtm.contracts.world import World, TrueCompany, Enquiry, ScriptedReply
    def co(i, dom):
        return TrueCompany(id=f"co_{i:03d}", name=f"Co {i}", domain=dom, industry="software", employee_count=100, revenue_band="10-50M",
                           region="EMEA", hq_country="GB", icp_fit=True)
    def enq(i, kind, band, email, **kw):
        return Enquiry(id=f"enq_{i:03d}", kind=kind, expected_band=band, full_name="N", email=email, company_name="C", message="m", **kw)
    return World(seed=42, companies=[co(1, "one.example"), co(2, "two.example")], contacts=[],
                 enquiries=[enq(1, "genuine", "high", "ann@one.example", truth_company_id="co_001"),
                            enq(2, "genuine", "high", "ann@one.example", duplicate_of="enq_001"),
                            enq(3, "vendor", "none", "sam@two.example"),
                            enq(4, "genuine", "low", "info@two.example", injection=True)],
                 replies=[ScriptedReply(id="rep_001", to_enquiry_id="enq_001", at_offset_s=60, kind="unsubscribe")])
