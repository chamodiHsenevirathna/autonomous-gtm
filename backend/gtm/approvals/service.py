"""Proposal and approval service (G1..G10). Humans decide; agents only create proposals.
Approvals bind to a payload hash, are single-use (consumed by the gateway), expire, and need an authorised role."""
from __future__ import annotations
from datetime import timedelta
from typing import Any, Callable
from psycopg import Connection
from psycopg.types.json import Jsonb
from .. import audit
from ..clock import Clock
from ..contracts.events import EventEnvelope, EventType
from ..contracts.proposals import (GATE_FOR_TYPE, MessagePayload, CrmWritePayload, FieldChangePayload, TaskPayload,
                                  LeadDispositionPayload, MatchPayload, ProposalType, payload_hash)
from .screens import screen_message

Emit = Callable[[Connection, Clock, EventEnvelope], Any]
_MODELS = {ProposalType.MESSAGE: MessagePayload, ProposalType.CRM_WRITE: CrmWritePayload, ProposalType.FIELD_CHANGE: FieldChangePayload,
           ProposalType.TASK: TaskPayload, ProposalType.LEAD_DISPOSITION: LeadDispositionPayload, ProposalType.MATCH_CONFIRMATION: MatchPayload}


class ApprovalError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _emit(emit: Emit | None, conn, clock, etype: str, proposal_id: int, account_id, payload: dict):
    if emit is None:
        try:
            from ..orchestration.events import emit as default_emit
        except Exception:  # orchestration may not be present in isolated tests
            return
        emit = default_emit
    emit(conn, clock, EventEnvelope(type=etype, account_id=account_id, entity_ref=f"proposal:{proposal_id}", payload=payload,
                                    occurred_at=clock.now(), source="approvals", dedupe_key=f"{etype}:{proposal_id}:{payload.get('n', 0)}"))


def _validate(ptype: str, payload: dict) -> dict:
    m = _MODELS.get(ProposalType(ptype))
    return m(**payload).model_dump(mode="json") if m else payload


def create_proposal(conn: Connection, clock: Clock, *, type: str, payload: dict, proposed_by: str, account_id: int | None = None,
                    evidence: list | None = None, rationale: str | None = None, confidence: float | None = None,
                    run_id: int | None = None, group_id: int | None = None, depends_on: int | None = None,
                    idempotency_key: str | None = None, target_entity: dict | None = None, emit: Emit | None = None) -> int:
    """Create a pending proposal. Idempotent on idempotency_key. Agents may call this; they cannot approve or execute."""
    ptype = ProposalType(type)
    if idempotency_key:
        r = conn.execute("SELECT id FROM ops.proposal WHERE idempotency_key=%s", (idempotency_key,)).fetchone()
        if r:
            return r["id"]
    gate = conn.execute("SELECT * FROM ops.gate_catalog WHERE gate_id=%s", (GATE_FOR_TYPE[ptype],)).fetchone()
    payload = _validate(ptype, payload)
    flags = []
    if ptype == ProposalType.MESSAGE:
        flags = screen_message(payload).flags
    now = clock.now()
    row = conn.execute(
        "INSERT INTO ops.proposal(group_id, depends_on_proposal_id, type, gate_id, account_id, target_entity, payload, payload_hash, evidence, "
        "rationale, confidence, proposed_by_run_id, proposed_by, required_role, idempotency_key, created_at, expires_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (group_id, depends_on, ptype.value, gate["gate_id"], account_id, Jsonb(target_entity) if target_entity else None, Jsonb(payload),
         Jsonb((evidence or []) + ([{"screen_flags": flags}] if flags else [])), rationale, confidence, run_id, proposed_by,
         ",".join(gate["approver_roles"]), idempotency_key, now, now + timedelta(hours=gate["expiry_hours"] or 72))).fetchone()
    pid = row["id"]
    conn.execute("UPDATE ops.proposal SET payload_hash=%s WHERE id=%s", (payload_hash(pid, ptype.value, payload), pid))
    audit.append(conn, clock, actor_type="agent" if proposed_by.startswith(("agent:", "system:")) else "human", actor_id=proposed_by,
                 event_type="proposal.created", entity_ref=f"proposal:{pid}", run_id=run_id, proposal_id=pid,
                 data={"type": ptype.value, "gate": gate["gate_id"], "account_id": account_id, "screen_flags": flags})
    _emit(emit, conn, clock, EventType.PROPOSAL_CREATED, pid, account_id, {"type": ptype.value})
    return pid


def _roles(conn, principal: str) -> set[str]:
    return {r["role"] for r in conn.execute("SELECT role FROM ops.role_assignment WHERE principal_id=%s", (principal,))}


def decide(conn: Connection, clock: Clock, *, proposal_id: int, decided_by: str, decision: str, edited_payload: dict | None = None,
           reason_code: str | None = None, comment: str | None = None, acknowledge_not_commitment: bool = False,
           emit: Emit | None = None) -> dict:
    """Record a human decision. Raises ApprovalError (code in: not_found, not_pending, expired, role, distinct_approver, invalid_edit,
    commercial_block, not_human). Returns the approval row."""
    p = conn.execute("SELECT * FROM ops.proposal WHERE id=%s FOR UPDATE", (proposal_id,)).fetchone()
    if not p:
        raise ApprovalError("not_found", f"proposal {proposal_id} not found")
    pr = conn.execute("SELECT type FROM ops.principal WHERE id=%s", (decided_by,)).fetchone()
    if not pr or pr["type"] != "human":
        raise ApprovalError("not_human", "only a human principal can decide a proposal")
    if p["status"] != "pending":
        raise ApprovalError("not_pending", f"proposal is {p['status']}")
    now = clock.now()
    if p["expires_at"] and p["expires_at"] <= now:
        conn.execute("UPDATE ops.proposal SET status='expired' WHERE id=%s", (proposal_id,))
        audit.append(conn, clock, actor_type="system", actor_id="system:rules", event_type="proposal.expired", entity_ref=f"proposal:{proposal_id}", proposal_id=proposal_id)
        raise ApprovalError("expired", "proposal expired before the decision")
    gate = conn.execute("SELECT * FROM ops.gate_catalog WHERE gate_id=%s", (p["gate_id"],)).fetchone()
    if not (_roles(conn, decided_by) & set(gate["approver_roles"])) and "director" not in _roles(conn, decided_by):
        raise ApprovalError("role", f"{decided_by} lacks a role allowed for {p['gate_id']} ({','.join(gate['approver_roles'])})")
    # separation of duties: a human may not approve their own proposal when the gate requires a distinct approver
    if (gate["requires_distinct_approver"] or p["proposed_by"] == decided_by) and p["proposed_by"] == decided_by:
        raise ApprovalError("distinct_approver", "approver must differ from the proposer")
    approved_payload, new_hash, status = None, None, None
    if decision == "reject":
        status = "rejected"
    else:
        approved_payload = p["payload"]
        status = "approved"
        if decision == "approve_with_edits":
            if not edited_payload:
                raise ApprovalError("invalid_edit", "edited_payload required")
            try:
                approved_payload = _validate(p["type"], edited_payload)
            except Exception as e:
                raise ApprovalError("invalid_edit", f"edited payload invalid: {e}")
            status = "approved_edited"
        if p["type"] == ProposalType.MESSAGE.value:
            ack = acknowledge_not_commitment and bool(_roles(conn, decided_by) & {"ae", "director"})
            sr = screen_message(approved_payload, acknowledged_not_commitment=ack)
            if sr.blocked:
                raise ApprovalError("commercial_block", "content screen blocks approval: " + "; ".join(f["detail"] for f in sr.flags if f["blocking"]))
        new_hash = payload_hash(proposal_id, p["type"], approved_payload)
        if acknowledge_not_commitment and p["type"] == ProposalType.MESSAGE.value:
            reason_code = "ack_not_commitment"   # the gateway re-screens and honours this acknowledgement
    appr = conn.execute(
        "INSERT INTO ops.approval_decision(proposal_id, decided_by, decision, approved_payload, approved_payload_hash, reason_code, comment, decided_at, expires_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
        (proposal_id, decided_by, decision, Jsonb(approved_payload) if approved_payload is not None else None, new_hash, reason_code, comment, now,
         now + timedelta(hours=gate["expiry_hours"] or 72) if decision != "reject" else None)).fetchone()
    conn.execute("UPDATE ops.proposal SET status=%s WHERE id=%s", (status, proposal_id))
    audit.append(conn, clock, actor_type="human", actor_id=decided_by, event_type=f"proposal.{'rejected' if decision=='reject' else 'approved'}",
                 entity_ref=f"proposal:{proposal_id}", proposal_id=proposal_id,
                 data={"decision": decision, "hash": new_hash, "edited": decision == "approve_with_edits", "reason_code": reason_code,
                       "acknowledged_not_commitment": acknowledge_not_commitment})
    _emit(emit, conn, clock, EventType.PROPOSAL_REJECTED if decision == "reject" else EventType.PROPOSAL_APPROVED, proposal_id, p["account_id"],
          {"decision": decision, "approval_id": appr["id"]})
    return appr


def expire_due(conn: Connection, clock: Clock, *, emit: Emit | None = None) -> list[int]:
    ids = [r["id"] for r in conn.execute("SELECT id, account_id FROM ops.proposal WHERE status='pending' AND expires_at <= %s", (clock.now(),))]
    for pid in ids:
        conn.execute("UPDATE ops.proposal SET status='expired' WHERE id=%s", (pid,))
        audit.append(conn, clock, actor_type="system", actor_id="system:rules", event_type="proposal.expired", entity_ref=f"proposal:{pid}", proposal_id=pid)
        _emit(emit, conn, clock, EventType.PROPOSAL_EXPIRED, pid, None, {})
    return ids


def supersede(conn: Connection, clock: Clock, proposal_id: int, reason: str, *, emit: Emit | None = None) -> None:
    p = conn.execute("SELECT status, account_id FROM ops.proposal WHERE id=%s FOR UPDATE", (proposal_id,)).fetchone()
    if p and p["status"] in ("pending", "approved", "approved_edited", "parked"):
        conn.execute("UPDATE ops.proposal SET status='superseded', block_reason=%s WHERE id=%s", (reason, proposal_id))
        audit.append(conn, clock, actor_type="system", actor_id="system:rules", event_type="proposal.superseded", entity_ref=f"proposal:{proposal_id}",
                     proposal_id=proposal_id, data={"reason": reason})
        _emit(emit, conn, clock, EventType.PROPOSAL_SUPERSEDED, proposal_id, p["account_id"], {"reason": reason})
