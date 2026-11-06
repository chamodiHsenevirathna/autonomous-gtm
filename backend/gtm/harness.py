"""SystemHarness implementation (contract gtm.contracts.harness). Drives the REAL system for evaluation scenarios."""
from __future__ import annotations
import importlib
from datetime import timedelta
from typing import Any
from psycopg.types.json import Jsonb
from . import audit
from .approvals import ApprovalError, decide as _decide
from .config import get_settings
from .contracts.errors import GTMError, PolicyDenied
from .contracts.gateway import GatewayResult, GatewayStatus, mint_token
from .contracts.sims import FaultSpec
from .gateway import gateway_for
from .runtime import Runtime


class Harness:
    def __init__(self, database_url: str | None = None, **_):
        self.rt = Runtime(database_url or get_settings().test_database_url)

    # ---- protocol attributes ----
    @property
    def conn(self): return self.rt.conn
    @property
    def clock(self): return self.rt.clock
    @property
    def world(self): return self.rt.world

    def reset(self, seed: int | None = None, llm_mode: str = "mock", world_overrides: dict | None = None) -> None:
        self.rt.build(seed or 42, llm_mode, world_overrides, reset=True)

    # ---- driving the system ----
    def deliver_enquiry(self, enquiry_id: str) -> int:
        enq = next(e for e in self.world.enquiries if e.id == enquiry_id)
        intake = importlib.import_module("gtm.agents.intake")
        lead_id = intake.submit_enquiry(self.conn, self.clock, enq)
        self.conn.commit()
        return int(lead_id or 0)

    def run_until_idle(self, *, max_steps: int = 1000, advance_clock: bool = True) -> dict:
        out: dict[str, Any] = {"rounds": 0}
        try:
            ingest = importlib.import_module("gtm.agents.ingest")
        except ModuleNotFoundError:
            ingest = None
        for _ in range(20):
            out["rounds"] += 1
            res = self.rt.runner.run_until_idle(max_steps=max_steps, advance_clock=advance_clock)
            self.conn.commit()
            n = 0
            if ingest is not None:
                n = (ingest.pull_and_route(self.conn, self.clock, self.rt.services) or {}).get("routed", 0)
                self.conn.commit()
            out.update(res)
            if not n:
                break
        return out

    def pending_proposals(self) -> list[dict]:
        return list(self.conn.execute("SELECT * FROM ops.proposal WHERE status='pending' ORDER BY id"))

    def decide(self, proposal_id: int, decision: str, *, by: str, edited_payload: dict | None = None, reason_code: str | None = None) -> dict:
        try:
            appr = _decide(self.conn, self.clock, proposal_id=proposal_id, decided_by=by, decision=decision, edited_payload=edited_payload, reason_code=reason_code)
            self.conn.commit()
            return {"ok": True, "approval_id": appr["id"], "hash": appr["approved_payload_hash"]}
        except ApprovalError as e:
            self.conn.rollback()
            return {"ok": False, "error": e.code, "message": str(e)}

    def deliver_reply(self, reply_id: str) -> None:
        rep = next(r for r in self.world.replies if r.id == reply_id)
        enq = next(e for e in self.world.enquiries if e.id == rep.to_enquiry_id)
        self.rt.sims.script_reply(reply_id, to_email=enq.email)

    def advance(self, seconds: float) -> None:
        self.clock.advance(seconds)

    def inject_fault(self, spec: FaultSpec) -> None:
        self.rt.sims.control.inject(spec)

    def clear_faults(self) -> None:
        self.rt.sims.control.clear()

    # ---- red-team: every bypass attempt must be denied ----
    def attempt_gateway(self, proposal_id: int, *, bypass: str | None = None) -> GatewayResult:
        gw = gateway_for(self.conn, self.clock, self.rt.services)
        if bypass is None:
            return gw.attempt(proposal_id)
        if bypass == "replay":
            gw.attempt(proposal_id)
            return gw.attempt(proposal_id)
        svc = self.rt.services
        p = self.conn.execute("SELECT * FROM ops.proposal WHERE id=%s", (proposal_id,)).fetchone()
        exp = self.clock.now() + timedelta(minutes=15)
        token = None
        if bypass == "forged_token":
            token = mint_token(b"not-the-gateway-secret", proposal_id=proposal_id, payload_hash=p["payload_hash"], adapter="crm.write", expires_at=exp)
        elif bypass == "wrong_hash":
            token = mint_token(svc.token_secret, proposal_id=proposal_id, payload_hash="0" * 64, adapter="crm.write", expires_at=exp)
        elif bypass not in ("no_token", "direct_adapter"):
            raise ValueError(f"unknown bypass {bypass}")
        try:
            svc.crm.create("contacts", {"email": "bypass@attempt.example"}, token=token, idempotency_key=f"bypass:{bypass}:{proposal_id}",
                           payload_hash=p["payload_hash"])
        except (PolicyDenied, GTMError) as e:
            audit.append(self.conn, self.clock, actor_type="system", actor_id="system:gateway", event_type="gateway.bypass_denied",
                         entity_ref=f"proposal:{proposal_id}", proposal_id=proposal_id, data={"bypass": bypass, "error": str(e)})
            self.conn.commit()
            return GatewayResult(status=GatewayStatus.BLOCKED, reason=f"adapter_denied:{bypass}", block_class="hard")
        audit.append(self.conn, self.clock, actor_type="system", actor_id="system:gateway", event_type="gateway.bypass_SUCCEEDED",
                     entity_ref=f"proposal:{proposal_id}", proposal_id=proposal_id, data={"bypass": bypass})
        self.conn.commit()
        return GatewayResult(status=GatewayStatus.EXECUTED, reason=f"BYPASS_SUCCEEDED:{bypass}")

    def tamper(self, what: str) -> None:
        c = self.conn
        if what == "audit_row":
            c.execute("ALTER TABLE ops.audit_event DISABLE TRIGGER USER")
            c.execute("UPDATE ops.audit_event SET data = data || '{\"tampered\": true}'::jsonb WHERE seq=(SELECT max(seq) FROM ops.audit_event)")
            c.execute("ALTER TABLE ops.audit_event ENABLE TRIGGER USER")
        elif what == "proposal_payload":
            c.execute("UPDATE ops.approval_decision SET approved_payload = jsonb_set(approved_payload, '{subject}', '\"tampered\"') "
                      "WHERE id=(SELECT max(id) FROM ops.approval_decision WHERE approved_payload IS NOT NULL AND approved_payload ? 'subject')")
        elif what == "recipient":
            c.execute("UPDATE gtm.contact SET email = 'changed.' || email WHERE id=(SELECT max(id) FROM gtm.contact)")
        else:
            raise ValueError(what)
        c.commit()

    def snapshot(self) -> dict[str, Any]:
        q = lambda s: self.conn.execute(s).fetchone()["n"]
        sent = len(getattr(self.rt.sims, "outreach_state", None).messages) if getattr(getattr(self.rt.sims, "outreach_state", None), "messages", None) is not None else None
        return {
            "leads": q("SELECT count(*) AS n FROM gtm.lead"), "accounts": q("SELECT count(*) AS n FROM gtm.account"),
            "contacts": q("SELECT count(*) AS n FROM gtm.contact"), "opportunities": q("SELECT count(*) AS n FROM gtm.opportunity"),
            "proposals": {r["status"]: r["n"] for r in self.conn.execute("SELECT status, count(*) AS n FROM ops.proposal GROUP BY status")},
            "executions": q("SELECT count(*) AS n FROM ops.execution WHERE status='succeeded'"),
            "audit_rows": q("SELECT count(*) AS n FROM ops.audit_event"), "suppressions": q("SELECT count(*) AS n FROM gtm.suppression"),
            "held_leads": q("SELECT count(*) AS n FROM gtm.lead WHERE status='held'"), "messages_sent_to_sim": sent,
            "clock": self.clock.now().isoformat(),
        }
