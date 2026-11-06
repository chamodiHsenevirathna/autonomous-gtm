"""A fake SystemHarness for testing the runner end to end. It writes the same rows the real system will write.
Switches inject defects so that the runner/invariants can be shown to catch them."""
from __future__ import annotations
from datetime import timedelta
from psycopg.types.json import Jsonb
from gtm import audit, db, seed
from gtm.clock import SimClock
from gtm.contracts.errors import PolicyDenied
from gtm.contracts.gateway import GatewayResult, GatewayStatus
from gtm.contracts.proposals import payload_hash
from eval_helpers import small_world


class FakeHarness:
    def __init__(self, conn, *, wrong_band: bool = False, send_without_approval: bool = False, ignore_suppression: bool = False):
        self.conn, self.clock, self.world = conn, SimClock(), small_world()
        self.wrong_band, self.send_without_approval, self.ignore_suppression = wrong_band, send_without_approval, ignore_suppression
        self.faults, self.sent, self.resets = [], 0, 0

    # ---- protocol
    def reset(self, seed_: int | None = None, llm_mode: str = "mock") -> None:
        db.truncate_all(self.conn); seed.seed_reference(self.conn)
        self.clock, self.faults, self.sent = SimClock(), [], 0
        self.resets += 1

    def deliver_enquiry(self, enquiry_id: str) -> int:
        e = next(x for x in self.world.enquiries if x.id == enquiry_id)
        now = self.clock.now()
        band = "none" if self.wrong_band and e.expected_band == "high" else e.expected_band
        lead = self.conn.execute(
            "INSERT INTO gtm.lead(channel, raw_payload, idempotency_key, triage_class, fit_band, status, created_at, updated_at) "
            "VALUES ('form',%s,%s,%s,%s,'proposed',%s,%s) RETURNING id",
            (Jsonb({"enquiry_id": e.id, "email": e.email}), f"enq:{e.id}", e.kind, band, now, now)).fetchone()["id"]
        if e.kind == "genuine":
            payload = {"channel": "email", "contact_id": lead, "resolved_recipient": e.email, "sender_identity": "maya@corvane.example",
                       "subject": "Hello", "body": "Thanks for your enquiry", "links": [], "attachments": [], "claims": []}
            pid = self.conn.execute(
                "INSERT INTO ops.proposal(type, gate_id, payload, payload_hash, proposed_by, created_at, expires_at) "
                "VALUES ('message','G5',%s,'x','agent:account-agent',%s,%s) RETURNING id", (Jsonb(payload), now, now + timedelta(hours=72))).fetchone()["id"]
            self.conn.execute("UPDATE ops.proposal SET payload_hash=%s WHERE id=%s", (payload_hash(pid, "message", payload), pid))
            audit.append(self.conn, self.clock, actor_type="agent", actor_id="agent:account-agent", event_type="proposal.created", proposal_id=pid)
            self.conn.execute("INSERT INTO ops.domain_event(type, payload, occurred_at, recorded_at, source, dedupe_key) VALUES ('lead.received',%s,%s,%s,'fake',%s)",
                              (Jsonb({"enquiry_id": e.id}), now, now, f"lead:{e.id}"))
        self.conn.commit()
        return lead

    def run_until_idle(self, *, max_steps: int = 1000, advance_clock: bool = True) -> dict:
        for p in self.conn.execute("SELECT id FROM ops.proposal WHERE status IN ('approved','approved_edited') ORDER BY id").fetchall():
            self._execute(p["id"])
        self.conn.commit()
        return {"steps": 0}

    def pending_proposals(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM ops.proposal WHERE status='pending'").fetchall()]

    def decide(self, proposal_id: int, decision: str, *, by: str, edited_payload: dict | None = None, reason_code: str | None = None) -> dict:
        p = self.conn.execute("SELECT * FROM ops.proposal WHERE id=%s", (proposal_id,)).fetchone()
        if by.startswith("agent:"):
            raise PolicyDenied("agents cannot approve")
        payload = edited_payload or p["payload"]
        status = {"approve": "approved", "approve_with_edits": "approved_edited", "reject": "rejected"}[decision]
        now = self.clock.now()
        aid = self.conn.execute(
            "INSERT INTO ops.approval_decision(proposal_id, decided_by, decision, approved_payload, approved_payload_hash, reason_code, decided_at, expires_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (proposal_id, by, decision, Jsonb(payload), payload_hash(proposal_id, p["type"], payload), reason_code, now, now + timedelta(hours=72))).fetchone()["id"]
        self.conn.execute("UPDATE ops.proposal SET status=%s WHERE id=%s", (status, proposal_id))
        audit.append(self.conn, self.clock, actor_type="human", actor_id=by, event_type=f"proposal.{status}", proposal_id=proposal_id)
        self.conn.commit()
        return {"approval_id": aid, "status": status}

    def deliver_reply(self, reply_id: str) -> None:
        rep = next(r for r in self.world.replies if r.id == reply_id)
        e = next(x for x in self.world.enquiries if x.id == rep.to_enquiry_id)
        if rep.kind == "unsubscribe":
            self.conn.execute("INSERT INTO gtm.suppression(scope, value, reason, created_at) VALUES ('address',%s,'unsubscribe',%s)", (e.email, self.clock.now()))
            self.conn.commit()

    def advance(self, seconds: float) -> None:
        self.clock.advance(seconds)

    def inject_fault(self, spec) -> None:
        self.faults.append(spec)

    def clear_faults(self) -> None:
        self.faults = []

    def attempt_gateway(self, proposal_id: int, *, bypass: str | None = None) -> GatewayResult:
        if bypass:
            return GatewayResult(status=GatewayStatus.BLOCKED, reason=f"bypass:{bypass}", block_class="soft")
        return self._execute(proposal_id)

    def tamper(self, what: str) -> None:
        if what == "audit_row":
            self.conn.execute("ALTER TABLE ops.audit_event DISABLE TRIGGER USER")
            self.conn.execute("UPDATE ops.audit_event SET data='{\"x\":1}'::jsonb WHERE seq=(SELECT min(seq) FROM ops.audit_event)")
            self.conn.execute("ALTER TABLE ops.audit_event ENABLE TRIGGER USER")
            self.conn.commit()
        else:
            raise ValueError(what)

    def snapshot(self) -> dict:
        return {"sent": self.sent, "faults": len(self.faults)}

    # ---- internals
    def _execute(self, pid: int) -> GatewayResult:
        p = self.conn.execute("SELECT * FROM ops.proposal WHERE id=%s", (pid,)).fetchone()
        a = self.conn.execute("SELECT * FROM ops.approval_decision WHERE proposal_id=%s AND decision<>'reject' ORDER BY id DESC LIMIT 1", (pid,)).fetchone()
        if a is None and not self.send_without_approval:
            return GatewayResult(status=GatewayStatus.BLOCKED, reason="no_approval", block_class="soft")
        payload = (a["approved_payload"] if a else p["payload"])
        to = payload["resolved_recipient"]
        if not self.ignore_suppression and self.conn.execute(
                "SELECT 1 FROM gtm.suppression WHERE scope='address' AND lower(value)=lower(%s) AND lifted_at IS NULL", (to,)).fetchone():
            self.conn.execute("UPDATE ops.proposal SET status='blocked', block_class='hard', block_reason='suppressed' WHERE id=%s", (pid,))
            audit.append(self.conn, self.clock, actor_type="system", actor_id="system:gateway", event_type="proposal.blocked", proposal_id=pid,
                         data={"block_class": "hard"})
            return GatewayResult(status=GatewayStatus.BLOCKED, reason="suppressed", block_class="hard")
        now = self.clock.now()
        xid = self.conn.execute(
            "INSERT INTO ops.execution(proposal_id, approval_id, idempotency_key, adapter, status, result, executed_at) VALUES (%s,%s,%s,'outreach.send','succeeded',%s,%s) "
            "ON CONFLICT (idempotency_key) DO UPDATE SET attempts = ops.execution.attempts RETURNING id, (xmax = 0) AS fresh",
            (pid, a["id"] if a else None, f"send:{pid}", Jsonb({"to_address": to}), now)).fetchone()
        if xid["fresh"]:
            self.sent += 1
            if a:
                self.conn.execute("UPDATE ops.approval_decision SET consumed_at=%s WHERE id=%s", (now, a["id"]))
            self.conn.execute("UPDATE ops.proposal SET status='executed' WHERE id=%s", (pid,))
            audit.append(self.conn, self.clock, actor_type="system", actor_id="system:gateway", event_type="proposal.executed", proposal_id=pid)
        self.conn.commit()
        return GatewayResult(status=GatewayStatus.EXECUTED, execution_id=xid["id"])


def make(database_url: str | None = None) -> FakeHarness:
    return FakeHarness(db.connect(database_url))
