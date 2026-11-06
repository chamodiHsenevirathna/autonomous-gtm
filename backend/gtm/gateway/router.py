"""Reply router and suppression helpers. Hard signals are evaluated FIRST on the raw sender address (docs/execution-architecture 13.4).
Suppression and sequence stops are the only unattended actions (autonomy A2: they only reduce outreach)."""
from __future__ import annotations
import re
from datetime import timedelta
from typing import Any
from psycopg import Connection
from psycopg.types.json import Jsonb
from .. import audit
from ..clock import Clock
from ..contracts.events import EventEnvelope, EventType
from ..contracts.llm import LLMRequest, Task

_UNSUB = re.compile(r"\b(unsubscribe|remove me|stop (?:emailing|contacting|sending)|do not contact|take me off)\b", re.I)
_OOO = re.compile(r"\b(out of (?:the )?office|automatic reply|auto-?reply|on (?:annual )?leave until)\b", re.I)


def domain_of(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower() if "@" in email else ""


def active_suppression(conn: Connection, now, *, email: str | None, contact_id: int | None, account_id: int | None, lock: bool = False) -> dict | None:
    """Return the first active suppression covering this recipient (address, domain, contact, account)."""
    clauses, params = [], []
    if email:
        clauses.append("(scope='address' AND lower(value)=lower(%s))"); params.append(email)
        clauses.append("(scope='domain' AND lower(value)=lower(%s))"); params.append(domain_of(email))
    if contact_id is not None:
        clauses.append("(scope='contact' AND value=%s)"); params.append(str(contact_id))
    if account_id is not None:
        clauses.append("(scope='account' AND value=%s)"); params.append(str(account_id))
    if not clauses:
        return None
    sql = ("SELECT * FROM gtm.suppression WHERE lifted_at IS NULL AND (expires_at IS NULL OR expires_at > %s) AND (" + " OR ".join(clauses) + ") ORDER BY id LIMIT 1")
    if lock:
        sql += " FOR SHARE"
    return conn.execute(sql, [now] + params).fetchone()


def add_suppression(conn: Connection, clock: Clock, *, scope: str, value: str, reason: str, actor: str = "system:rules", source_event_id: int | None = None) -> int:
    ex = conn.execute("SELECT id FROM gtm.suppression WHERE scope=%s AND lower(value)=lower(%s) AND reason=%s AND lifted_at IS NULL", (scope, value, reason)).fetchone()
    if ex:
        return ex["id"]
    sid = conn.execute("INSERT INTO gtm.suppression(scope, value, reason, source_event_id, created_at) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                       (scope, value, reason, source_event_id, clock.now())).fetchone()["id"]
    audit.append(conn, clock, actor_type="system", actor_id=actor, event_type="suppression.added", entity_ref=f"suppression:{sid}",
                 data={"scope": scope, "value": value, "reason": reason})
    return sid


def lift_suppression(conn: Connection, clock: Clock, *, suppression_id: int, lifted_by: str, evidence: str) -> None:
    """Human-only and evidence-bound (docs/human-oversight 9.2). Raises PermissionError otherwise."""
    pr = conn.execute("SELECT p.type, array_agg(r.role) AS roles FROM ops.principal p LEFT JOIN ops.role_assignment r ON r.principal_id=p.id WHERE p.id=%s GROUP BY p.type", (lifted_by,)).fetchone()
    if not pr or pr["type"] != "human" or not (set(pr["roles"] or []) & {"revops", "director"}) or not (evidence or "").strip():
        raise PermissionError("suppression can be lifted only by RevOps/Director with contact-initiated opt-in evidence")
    conn.execute("UPDATE gtm.suppression SET lifted_at=%s, lifted_by=%s, lifted_evidence=%s WHERE id=%s", (clock.now(), lifted_by, evidence, suppression_id))
    audit.append(conn, clock, actor_type="human", actor_id=lifted_by, event_type="suppression.lifted", entity_ref=f"suppression:{suppression_id}", data={"evidence": evidence})


def _emit(emit, conn, clock, etype, *, account_id, ref, payload, dedupe):
    if emit is None:
        try:
            from ..orchestration.events import emit as emit  # type: ignore
        except Exception:
            return None
    return emit(conn, clock, EventEnvelope(type=etype, account_id=account_id, entity_ref=ref, payload=payload, occurred_at=clock.now(), source="router", dedupe_key=dedupe))


def route_sim_event(conn: Connection, clock: Clock, ev: dict, *, llm=None, emit=None) -> dict:
    """Process one event pulled from the outreach/mail simulator. ev = {seq, type, ts, payload}. Idempotent on (type, seq)."""
    seq, etype, p = ev["seq"], ev["type"], ev.get("payload", {})
    key = f"sim:{etype}:{seq}"
    if conn.execute("SELECT 1 FROM ops.idempotency_record WHERE key=%s", (key,)).fetchone():
        return {"duplicate": True}
    sender = (p.get("from") or p.get("email") or "").lower()
    contact = conn.execute("SELECT id, account_id FROM gtm.contact WHERE lower(email)=%s AND merged_into_id IS NULL", (sender,)).fetchone() if sender else None
    cid, aid = (contact["id"], contact["account_id"]) if contact else (None, None)
    out: dict[str, Any] = {"type": etype, "contact_id": cid, "account_id": aid}

    if etype == "contact_visible":
        ref = str(p.get("external_key") or "")
        conn.execute("UPDATE gtm.sync_state SET state='visible', last_checked_at=%s WHERE system='outreach' AND external_ref=%s AND state IN ('unknown','pending')", (clock.now(), ref))
        _emit(emit, conn, clock, EventType.SYNC_CONTACT_VISIBLE, account_id=aid, ref=f"sync:{ref}", payload=p, dedupe=key)
        out["intent"] = "contact_visible"
    else:
        body, subject = p.get("body", ""), p.get("subject", "")
        intent = None
        if etype == "unsubscribe" or (etype == "reply" and _UNSUB.search(f"{subject}\n{body}")):
            intent = "unsubscribe"; add_suppression(conn, clock, scope="address", value=sender, reason="unsubscribe")
        elif etype == "bounce":
            intent = "bounce"; add_suppression(conn, clock, scope="address", value=sender or p.get("to", ""), reason="bounce")
            conn.execute("UPDATE gtm.sending_domain_stats SET bounces=bounces+1 WHERE domain=%s", (domain_of(p.get("from_domain") or p.get("sender_domain") or "corvane.example"),))
            if cid:
                conn.execute("UPDATE gtm.contact SET email_status='bounced' WHERE id=%s", (cid,))
        elif etype == "reply" and _OOO.search(f"{subject}\n{body}"):
            intent = "ooo"
        elif etype == "meeting_booked":
            intent = "meeting_booked"
        else:
            if llm is not None:
                r = llm.complete(LLMRequest(task=Task.REPLY_INTENT, input={"untrusted": {"subject": subject, "body": body}}))
                intent = r.output.get("intent", "unclear")
            else:
                intent = "unclear"
        if intent in ("unsubscribe", "bounce") and cid:
            conn.execute("UPDATE gtm.outreach_claim SET released_at=%s WHERE entity_type='contact' AND entity_id=%s AND released_at IS NULL", (clock.now(), cid))
            _emit(emit, conn, clock, EventType.SEQUENCE_STOPPED, account_id=aid, ref=f"contact:{cid}", payload={"reason": intent}, dedupe=f"{key}:stop")
            _emit(emit, conn, clock, EventType.SUPPRESSION_ADDED, account_id=aid, ref=f"contact:{cid}", payload={"reason": intent}, dedupe=f"{key}:supp")
        iid = conn.execute("INSERT INTO gtm.interaction(account_id, contact_id, channel, direction, occurred_at, subject, body, thread_id, classification, external_ref, data_origin) "
                           "VALUES (%s,%s,'email','inbound',%s,%s,%s,%s,%s,%s,'SCR') RETURNING id",
                           (aid, cid, ev.get("ts") or clock.now(), subject, body, p.get("thread_id"), intent, f"sim:{seq}")).fetchone()["id"]
        out.update(intent=intent, interaction_id=iid)
        evt = EventType.MEETING_BOOKED if intent == "meeting_booked" else EventType.REPLY_RECEIVED
        _emit(emit, conn, clock, evt, account_id=aid, ref=f"interaction:{iid}", payload={"intent": intent, "contact_id": cid, "interaction_id": iid}, dedupe=f"{key}:evt")
        audit.append(conn, clock, actor_type="system", actor_id="system:rules", event_type="reply.routed", entity_ref=f"interaction:{iid}",
                     data={"intent": intent, "sim_event": seq, "suppressed": intent in ("unsubscribe", "bounce")})
    conn.execute("INSERT INTO ops.idempotency_record(key, result, created_at) VALUES (%s,%s,%s)", (key, Jsonb(out), clock.now()))
    return out
