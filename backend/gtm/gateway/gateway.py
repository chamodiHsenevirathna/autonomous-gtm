"""Execution gateway: the ONLY route to side-effecting adapters. Deterministic code, no model calls.
Ordered checks (docs/execution-architecture.md 13.2); returns READY/NOT_READY/BLOCKED/EXECUTED (contract C11).
Approvals are single-use; adapters require a gateway-minted execution token."""
from __future__ import annotations
import hashlib
from datetime import timedelta
from typing import Any, Callable, Protocol
from psycopg import Connection
from psycopg.types.json import Jsonb
from .. import audit
from ..approvals.screens import screen_message
from ..clock import Clock
from ..config import Settings
from ..contracts.errors import NotReady, PermanentError, PolicyDenied, RetryableError
from ..contracts.events import EventEnvelope, EventType
from ..contracts.gateway import GatewayResult, GatewayStatus, mint_token
from ..contracts.proposals import ProposalType, payload_hash
from .router import active_suppression, domain_of

CLAIM_PRIORITY = {"customer": 1, "opportunity_followup": 2, "inbound_response": 3, "outbound": 4}


class ExecutionFacade(Protocol):
    """What the gateway needs from the (simulated) CRM and outreach tool. Implemented over the gtm.adapters clients."""
    def crm_find_company(self, domain: str) -> str | None: ...
    def crm_find_contact(self, email: str) -> str | None: ...
    def crm_create(self, obj: str, properties: dict, *, token, idempotency_key: str) -> str: ...
    def crm_update(self, obj: str, obj_id: str, properties: dict, *, token, idempotency_key: str) -> None: ...
    def outreach_import(self, crm_contact_id: str, email: str, full_name: str | None, *, token, idempotency_key: str) -> dict: ...
    def outreach_lookup(self, *, external_key: str | None = None, email: str | None = None) -> dict | None: ...
    def outreach_send(self, outreach_contact_id: str, from_address: str, to_address: str, subject: str, body: str, *, token, idempotency_key: str) -> dict: ...


class _Stop(Exception):
    def __init__(self, result: GatewayResult):
        self.result = result


class Gateway:
    def __init__(self, conn: Connection, clock: Clock, settings: Settings, facade: ExecutionFacade, token_secret: bytes, emit: Callable | None = None):
        self.conn, self.clock, self.settings, self.facade, self._secret, self._emit_fn = conn, clock, settings, facade, token_secret, emit
        self.executors: dict[str, Any] = {
            ProposalType.CRM_WRITE.value: _CrmWrite(), ProposalType.MESSAGE.value: _Message(), ProposalType.FIELD_CHANGE.value: _FieldChange(),
            ProposalType.TASK.value: _Task(), ProposalType.LEAD_DISPOSITION.value: _Disposition()}

    # ---- helpers ----
    def register_executor(self, proposal_type: str, executor) -> None:
        self.executors[proposal_type] = executor

    def token(self, p: dict, appr: dict, adapter: str):
        return mint_token(self._secret, proposal_id=p["id"], payload_hash=appr["approved_payload_hash"], adapter=adapter,
                          expires_at=self.clock.now() + timedelta(minutes=self.settings.execution_token_ttl_minutes))

    def emit(self, etype: str, account_id, ref: str, payload: dict, dedupe: str):
        fn = self._emit_fn
        if fn is None:
            try:
                from ..orchestration.events import emit as fn  # type: ignore
            except Exception:
                return
        fn(self.conn, self.clock, EventEnvelope(type=etype, account_id=account_id, entity_ref=ref, payload=payload, occurred_at=self.clock.now(), source="gateway", dedupe_key=dedupe))

    def _audit(self, p, event_type: str, data: dict):
        audit.append(self.conn, self.clock, actor_type="system", actor_id="system:gateway", event_type=event_type, entity_ref=f"proposal:{p['id']}", proposal_id=p["id"], data=data)

    # ---- main entry ----
    def attempt(self, proposal_id: int) -> GatewayResult:
        checks: list[dict] = []
        self._checks = checks
        try:
            res = self._attempt(proposal_id, checks)
        except _Stop as s:
            res = s.result
        res.checks = checks
        self.conn.commit()
        return res

    def _stop(self, p, checks, status: GatewayStatus, reason: str, *, block_class: str | None = None, retry: float | None = None) -> _Stop:
        pid = p["id"]
        checks = checks or self._checks
        if status == GatewayStatus.BLOCKED:
            if block_class == "hard":
                self.conn.execute("UPDATE ops.proposal SET status='blocked', block_class='hard', block_reason=%s WHERE id=%s", (reason, pid))
            else:  # soft: returned to review with the reason
                self.conn.execute("UPDATE ops.proposal SET status='pending', block_class='soft', block_reason=%s WHERE id=%s", (reason, pid))
        elif status == GatewayStatus.NOT_READY:
            self.conn.execute("UPDATE ops.proposal SET status='parked', block_reason=%s WHERE id=%s AND status NOT IN ('executed')", (reason, pid))
        etype = "proposal.blocked" if (status == GatewayStatus.BLOCKED and block_class == "hard") else f"gateway.{status.value.lower()}"
        self._audit(p, etype, {"reason": reason, "block_class": block_class, "checks": checks})
        return _Stop(GatewayResult(status=status, reason=reason, block_class=block_class, retry_after_s=retry))

    def _attempt(self, proposal_id: int, checks: list[dict]) -> GatewayResult:
        c = self.conn
        p = c.execute("SELECT * FROM ops.proposal WHERE id=%s FOR UPDATE", (proposal_id,)).fetchone()
        if not p:
            return GatewayResult(status=GatewayStatus.BLOCKED, reason="not_found", block_class="hard")
        now = self.clock.now()

        def rec(name: str, passed: bool, detail: Any = None):
            checks.append({"name": name, "passed": passed, "detail": detail})

        if p["status"] == "executed":  # replay of a consumed approval: no new effect
            ex = c.execute("SELECT * FROM ops.execution WHERE proposal_id=%s AND status='succeeded' ORDER BY id DESC LIMIT 1", (proposal_id,)).fetchone()
            rec("replay", True, "already executed; returning earlier result")
            return GatewayResult(status=GatewayStatus.EXECUTED, reason="replay", execution_id=ex["id"] if ex else None, external_ref=ex["external_ref"] if ex else None)
        if p["status"] == "blocked" and p["block_class"] == "hard":
            raise self._stop(p, checks, GatewayStatus.BLOCKED, p["block_reason"] or "hard_block", block_class="hard")
        if p["status"] not in ("approved", "approved_edited", "parked", "executing"):
            rec("proposal_status", False, p["status"])
            raise _Stop(GatewayResult(status=GatewayStatus.BLOCKED, reason=f"not_approved:{p['status']}", block_class="soft"))
        # 1. approval valid: exists, unconsumed, unexpired (G10 grace), authorised role, hash matches
        appr = c.execute("SELECT * FROM ops.approval_decision WHERE proposal_id=%s AND decision IN ('approve','approve_with_edits') ORDER BY id DESC LIMIT 1", (proposal_id,)).fetchone()
        if not appr or appr["consumed_at"] is not None:
            rec("approval_valid", False, "missing or consumed")
            raise self._stop(p, checks, GatewayStatus.BLOCKED, "no_valid_approval", block_class="soft")
        grace = timedelta(minutes=self.settings.sequence_step_grace_minutes) if p["gate_id"] == "G10" else timedelta(0)
        if appr["expires_at"] and appr["expires_at"] + grace <= now:
            rec("approval_valid", False, "expired")
            raise self._stop(p, checks, GatewayStatus.BLOCKED, "approval_expired", block_class="soft")
        gate = c.execute("SELECT approver_roles FROM ops.gate_catalog WHERE gate_id=%s", (p["gate_id"],)).fetchone()
        roles = {r["role"] for r in c.execute("SELECT role FROM ops.role_assignment WHERE principal_id=%s", (appr["decided_by"],))}
        if not (roles & set(gate["approver_roles"])) and "director" not in roles:
            rec("approval_valid", False, "approver role no longer valid")
            raise self._stop(p, checks, GatewayStatus.BLOCKED, "approver_role_invalid", block_class="hard")
        payload = appr["approved_payload"]
        if payload_hash(proposal_id, p["type"], payload) != appr["approved_payload_hash"]:
            rec("hash_matches", False, "approved payload does not match its recorded hash")
            raise self._stop(p, checks, GatewayStatus.BLOCKED, "payload_tampered", block_class="hard")
        live_payload = payload
        if p["type"] == ProposalType.MESSAGE.value:  # recompute against the CURRENTLY resolved recipient
            ct = c.execute("SELECT email, merged_into_id FROM gtm.contact WHERE id=%s", (payload["contact_id"],)).fetchone()
            live_payload = dict(payload, resolved_recipient=(ct["email"] if ct else None))
            if ct is None or ct["merged_into_id"] is not None or payload_hash(proposal_id, p["type"], live_payload) != appr["approved_payload_hash"]:
                rec("hash_matches", False, "recipient changed since approval")
                raise self._stop(p, checks, GatewayStatus.BLOCKED, "recipient_changed", block_class="soft")
        rec("approval_valid", True, {"approval_id": appr["id"], "decided_by": appr["decided_by"]})
        rec("hash_matches", True, appr["approved_payload_hash"][:12])
        if p["depends_on_proposal_id"]:
            dep = c.execute("SELECT status FROM ops.proposal WHERE id=%s", (p["depends_on_proposal_id"],)).fetchone()
            ok = dep and dep["status"] == "executed"
            rec("dependency_executed", bool(ok), dep["status"] if dep else None)
            if not ok:
                raise self._stop(p, checks, GatewayStatus.NOT_READY, "dependency_not_executed", retry=5.0)
        ex = self.executors.get(p["type"])
        if ex is None:
            raise self._stop(p, checks, GatewayStatus.BLOCKED, f"no_executor:{p['type']}", block_class="hard")
        # 2-10 type-specific preflight
        ex.preflight(self, p, live_payload, appr, rec)
        # 11. critical section: atomically claim execution, authoritative suppression re-read with lock (LAST), then adapter call
        claimed = c.execute("UPDATE ops.proposal SET status='executing' WHERE id=%s AND status IN ('approved','approved_edited','parked','executing') RETURNING id", (proposal_id,)).fetchone()
        if not claimed:
            raise self._stop(p, checks, GatewayStatus.BLOCKED, "claim_lost", block_class="soft")
        ex.final_checks(self, p, live_payload, appr, rec)
        try:
            out = ex.run(self, p, live_payload, appr)
        except RetryableError as e:
            c.rollback()
            p2 = c.execute("SELECT * FROM ops.proposal WHERE id=%s FOR UPDATE", (proposal_id,)).fetchone()
            rec("adapter", False, f"retryable: {e}")
            raise self._stop(p2, checks, GatewayStatus.NOT_READY, f"adapter_retryable: {e}", retry=e.retry_after or 5.0)
        except NotReady as e:
            c.rollback()
            p2 = c.execute("SELECT * FROM ops.proposal WHERE id=%s FOR UPDATE", (proposal_id,)).fetchone()
            raise self._stop(p2, checks, GatewayStatus.NOT_READY, str(e), retry=e.retry_after or 5.0)
        except PolicyDenied as e:
            c.rollback()
            p2 = c.execute("SELECT * FROM ops.proposal WHERE id=%s FOR UPDATE", (proposal_id,)).fetchone()
            rec("adapter", False, f"policy: {e}")
            raise self._stop(p2, checks, GatewayStatus.BLOCKED, f"adapter_denied: {e}", block_class="hard")
        except PermanentError as e:
            c.rollback()
            p2 = c.execute("SELECT * FROM ops.proposal WHERE id=%s FOR UPDATE", (proposal_id,)).fetchone()
            c.execute("INSERT INTO ops.execution(proposal_id, approval_id, idempotency_key, adapter, status, error, executed_at) VALUES (%s,%s,%s,%s,'failed',%s,%s) ON CONFLICT (idempotency_key) DO NOTHING",
                      (proposal_id, appr["id"], f"exec:{proposal_id}:{appr['id']}:{ex.adapter}:failed", ex.adapter, str(e), self.clock.now()))
            c.execute("UPDATE ops.proposal SET status='failed', block_reason=%s WHERE id=%s", (str(e), proposal_id))
            self.emit(EventType.EXECUTION_FAILED, p2["account_id"], f"proposal:{proposal_id}", {"error": str(e)}, f"exec-failed:{proposal_id}:{appr['id']}")
            raise self._stop(p2, checks, GatewayStatus.BLOCKED, f"adapter_permanent: {e}", block_class="hard")
        rec("adapter", True, out.get("summary"))
        exec_row = c.execute("INSERT INTO ops.execution(proposal_id, approval_id, idempotency_key, adapter, status, external_ref, result, executed_at) VALUES (%s,%s,%s,%s,'succeeded',%s,%s,%s) "
                             "ON CONFLICT (idempotency_key) DO UPDATE SET external_ref=EXCLUDED.external_ref RETURNING id",
                             (proposal_id, appr["id"], f"exec:{proposal_id}:{appr['id']}:{ex.adapter}", ex.adapter, out.get("external_ref"), Jsonb({**out, "payload_hash": appr["approved_payload_hash"]}), now)).fetchone()
        c.execute("UPDATE ops.approval_decision SET consumed_at=%s WHERE id=%s AND consumed_at IS NULL", (now, appr["id"]))
        c.execute("UPDATE ops.proposal SET status='executed', block_reason=NULL WHERE id=%s", (proposal_id,))
        self._audit(p, "execution.completed", {"adapter": ex.adapter, "external_ref": out.get("external_ref"), "approval_id": appr["id"], "checks": checks})
        self.emit(EventType.EXECUTION_COMPLETED, p["account_id"], f"proposal:{proposal_id}", {"type": p["type"], "external_ref": out.get("external_ref")}, f"exec-done:{proposal_id}:{appr['id']}")
        return GatewayResult(status=GatewayStatus.EXECUTED, execution_id=exec_row["id"], external_ref=out.get("external_ref"))


# ================= executors =================
class _Base:
    adapter = "none"

    def preflight(self, gw: Gateway, p, payload, appr, rec): ...
    def final_checks(self, gw: Gateway, p, payload, appr, rec): ...


class _Message(_Base):
    adapter = "outreach.send"

    def preflight(self, gw, p, payload, appr, rec):
        c, now = gw.conn, gw.clock.now()
        purpose = (p["target_entity"] or {}).get("purpose", "inbound_response")
        if payload.get("experiment_id") or payload.get("variant_id"):
            raise gw._stop(p, [], GatewayStatus.BLOCKED, "experiments_not_enabled", block_class="soft")
        sr = screen_message(payload, acknowledged_not_commitment=(appr["reason_code"] == "ack_not_commitment"))
        rec("content_screens", not sr.blocked, sr.flags)
        if sr.blocked:
            raise gw._stop(p, [], GatewayStatus.BLOCKED, "content_screen: " + "; ".join(f["detail"] for f in sr.flags if f["blocking"]), block_class="soft")
        ct = c.execute("SELECT * FROM gtm.contact WHERE id=%s", (payload["contact_id"],)).fetchone()
        ok = ct["email_status"] not in ("bounced", "stale")
        rec("recipient_quality", ok, ct["email_status"])
        if not ok:
            raise gw._stop(p, [], GatewayStatus.BLOCKED, f"recipient_email_{ct['email_status']}", block_class="soft")
        sup = active_suppression(c, now, email=payload["resolved_recipient"], contact_id=ct["id"], account_id=ct["account_id"])
        rec("suppression_precheck", sup is None, sup and {"id": sup["id"], "reason": sup["reason"]})
        if sup:
            raise gw._stop(p, [], GatewayStatus.BLOCKED, f"suppressed:{sup['reason']}", block_class="hard")
        mine = CLAIM_PRIORITY.get(purpose, 4)
        other = c.execute("SELECT * FROM gtm.outreach_claim WHERE entity_type='contact' AND entity_id=%s AND released_at IS NULL AND (expires_at IS NULL OR expires_at > %s) "
                          "AND holder_ref <> %s AND priority <= %s ORDER BY priority LIMIT 1", (ct["id"], now, f"proposal:{p['id']}", mine)).fetchone()
        rec("outreach_claims", other is None, other and other["holder_ref"])
        if other:
            raise gw._stop(p, [], GatewayStatus.BLOCKED, f"claim_conflict:{other['holder_ref']}", block_class="soft")
        fp = hashlib.sha256(f"{ct['id']}|{purpose}|{hashlib.sha256(payload['body'].encode()).hexdigest()}".encode()).hexdigest()
        dup = c.execute("SELECT 1 FROM ops.execution e WHERE e.adapter='outreach.send' AND e.status='succeeded' AND e.result->>'fingerprint'=%s AND e.executed_at > %s AND e.proposal_id<>%s", (fp, now - timedelta(days=14), p["id"])).fetchone()
        rec("duplicate_outreach", dup is None)
        if dup:
            raise gw._stop(p, [], GatewayStatus.BLOCKED, "duplicate_outreach", block_class="soft")
        if purpose == "outbound":
            last = c.execute("SELECT max(executed_at) AS t FROM ops.execution e JOIN ops.proposal pr ON pr.id=e.proposal_id WHERE e.adapter='outreach.send' AND e.status='succeeded' AND pr.payload->>'contact_id'=%s", (str(ct["id"]),)).fetchone()["t"]
            capped = bool(last and now - last < timedelta(days=3))
            rec("frequency_cap", not capped)
            if capped:
                raise gw._stop(p, [], GatewayStatus.BLOCKED, "frequency_cap", block_class="soft")
        lock = c.execute("SELECT 1 FROM gtm.interaction WHERE contact_id=%s AND direction='outbound' AND classification='human_touch' AND occurred_at > %s", (ct["id"], now - timedelta(hours=2))).fetchone()
        rec("human_touch_lock", lock is None)
        if lock:
            raise gw._stop(p, [], GatewayStatus.BLOCKED, "human_touch_lock", block_class="soft")
        dom = domain_of(payload["sender_identity"])
        st = c.execute("SELECT breaker_state FROM gtm.sending_domain_stats WHERE domain=%s", (dom,)).fetchone()
        rec("domain_breaker", not (st and st["breaker_state"] == "open"))
        if st and st["breaker_state"] == "open":
            raise gw._stop(p, [], GatewayStatus.BLOCKED, "breaker_open", block_class="soft")
        # sync precondition: the contact must be visible in the outreach tool
        ss = c.execute("SELECT * FROM gtm.sync_state WHERE entity_type='contact' AND entity_id=%s AND system='outreach'", (ct["id"],)).fetchone()
        if not ss:
            rec("sync_precondition", False, "contact never imported")
            raise gw._stop(p, [], GatewayStatus.BLOCKED, "contact_not_in_outreach", block_class="soft")
        if ss["state"] not in ("visible", "enrolled"):
            found = gw.facade.outreach_lookup(external_key=ss["external_ref"], email=ct["email"])
            if found:
                c.execute("UPDATE gtm.sync_state SET state='visible', last_checked_at=%s WHERE entity_type='contact' AND entity_id=%s AND system='outreach'", (now, ct["id"]))
                c.execute("UPDATE gtm.contact SET external_ids = external_ids || %s WHERE id=%s", (Jsonb({"outreach": str(found["id"])}), ct["id"]))
                rec("sync_precondition", True, "became visible")
            else:
                timed_out = ss["deadline_at"] is not None and now >= ss["deadline_at"]
                if timed_out:
                    c.execute("UPDATE gtm.sync_state SET state='timed_out', last_checked_at=%s WHERE entity_type='contact' AND entity_id=%s AND system='outreach'", (now, ct["id"]))
                rec("sync_precondition", False, "timed_out" if timed_out else "pending")
                raise gw._stop(p, [], GatewayStatus.NOT_READY, "sync_timeout" if timed_out else "sync_pending", retry=60.0 if timed_out else 5.0)
        else:
            rec("sync_precondition", True, ss["state"])

    def final_checks(self, gw, p, payload, appr, rec):
        ct = gw.conn.execute("SELECT id, account_id FROM gtm.contact WHERE id=%s", (payload["contact_id"],)).fetchone()
        sup = active_suppression(gw.conn, gw.clock.now(), email=payload["resolved_recipient"], contact_id=ct["id"], account_id=ct["account_id"], lock=True)
        rec("suppression_authoritative", sup is None, sup and sup["reason"])
        if sup:
            gw.conn.execute("UPDATE ops.proposal SET status='parked' WHERE id=%s", (p["id"],))  # then _stop sets blocked
            raise gw._stop(p, [], GatewayStatus.BLOCKED, f"suppressed:{sup['reason']}", block_class="hard")
        purpose = (p["target_entity"] or {}).get("purpose", "inbound_response")
        gw.conn.execute("INSERT INTO gtm.outreach_claim(entity_type, entity_id, purpose, priority, holder_ref, created_at, expires_at) VALUES ('contact',%s,%s,%s,%s,%s,%s)",
                        (ct["id"], purpose, CLAIM_PRIORITY.get(purpose, 4), f"proposal:{p['id']}", gw.clock.now(), gw.clock.now() + timedelta(days=3)))

    def run(self, gw, p, payload, appr):
        ct = gw.conn.execute("SELECT * FROM gtm.contact WHERE id=%s", (payload["contact_id"],)).fetchone()
        oid = (ct["external_ids"] or {}).get("outreach")
        if not oid:
            raise NotReady("outreach contact id unknown", retry_after=5.0)
        key = f"exec:{p['id']}:{appr['id']}:outreach.send"
        resp = gw.facade.outreach_send(oid, payload["sender_identity"], payload["resolved_recipient"], payload["subject"], payload["body"], token=gw.token(p, appr, "outreach.send"), idempotency_key=key)
        purpose = (p["target_entity"] or {}).get("purpose", "inbound_response")
        fp = hashlib.sha256(f"{ct['id']}|{purpose}|{hashlib.sha256(payload['body'].encode()).hexdigest()}".encode()).hexdigest()
        gw.conn.execute("INSERT INTO gtm.interaction(account_id, contact_id, channel, direction, occurred_at, subject, body, thread_id, classification, external_ref, data_origin) "
                        "VALUES (%s,%s,'email','outbound',%s,%s,%s,%s,'agent_drafted_human_approved',%s,'SCR')",
                        (ct["account_id"], ct["id"], gw.clock.now(), payload["subject"], payload["body"], payload.get("thread_id"), f"msg:{resp.get('message_id')}"))
        gw.conn.execute("INSERT INTO gtm.sending_domain_stats(domain, sends) VALUES (%s,1) ON CONFLICT (domain) DO UPDATE SET sends = gtm.sending_domain_stats.sends+1", (domain_of(payload["sender_identity"]),))
        gw.conn.execute("UPDATE gtm.sync_state SET state='enrolled' WHERE entity_type='contact' AND entity_id=%s AND system='outreach' AND state='visible'", (ct["id"],))
        return {"external_ref": str(resp.get("message_id")), "fingerprint": fp, "summary": f"sent to {payload['resolved_recipient']}", "recipient": payload["resolved_recipient"], "to_address": payload["resolved_recipient"]}


class _CrmWrite(_Base):
    adapter = "crm.write"

    def run(self, gw, p, payload, appr):
        c, tok = gw.conn, gw.token(p, appr, "crm.write")
        results, ids = [], {}
        for i, op in enumerate(payload["operations"]):
            obj, props, ref = op["object"], dict(op["properties"]), op["local_ref"]
            key = f"crm:{p['id']}:{appr['id']}:{i}"
            if op["action"] == "create":
                existing = None
                if obj == "company" and props.get("domain"):
                    existing = gw.facade.crm_find_company(props["domain"])
                if obj == "contact" and props.get("email"):
                    existing = gw.facade.crm_find_contact(props["email"])
                if obj == "company":
                    pass
                if obj == "deal" and ids.get("company"):
                    props["associated_company"] = ids["company"]
                if obj == "contact" and ids.get("company"):
                    props["associated_company"] = ids["company"]
                crm_id = existing or gw.facade.crm_create({"company": "companies", "contact": "contacts", "deal": "deals"}[obj], props, token=tok, idempotency_key=key)
                results.append({"object": obj, "crm_id": crm_id, "reused_existing": bool(existing)})
            else:
                crm_id = (ref.get("crm_id") or "")
                gw.facade.crm_update({"company": "companies", "contact": "contacts", "deal": "deals"}[obj], crm_id, props, token=tok, idempotency_key=key)
                results.append({"object": obj, "crm_id": crm_id, "updated": True})
            ids[obj] = crm_id
            table = {"account": "gtm.account", "contact": "gtm.contact", "opportunity": "gtm.opportunity"}[ref["type"]]
            c.execute(f"UPDATE {table} SET external_ids = external_ids || %s WHERE id=%s", (Jsonb({"crm": crm_id}), ref["id"]))
            if obj == "contact" and op["action"] == "create" and props.get("email"):
                imp_key = f"outreach-import:{p['id']}:{appr['id']}:{i}"
                gw.facade.outreach_import(crm_id, props["email"], props.get("full_name"), token=gw.token(p, appr, "outreach.import"), idempotency_key=imp_key)
                c.execute("INSERT INTO gtm.sync_state(entity_type, entity_id, system, state, external_ref, last_checked_at, deadline_at) VALUES ('contact',%s,'outreach','pending',%s,%s,%s) "
                          "ON CONFLICT (entity_type, entity_id, system) DO UPDATE SET state='pending', external_ref=EXCLUDED.external_ref, last_checked_at=EXCLUDED.last_checked_at, deadline_at=EXCLUDED.deadline_at",
                          (ref["id"], crm_id, gw.clock.now(), gw.clock.now() + timedelta(minutes=gw.settings.sync_wait_deadline_minutes)))
        return {"external_ref": ",".join(r["crm_id"] for r in results), "operations": results, "summary": f"{len(results)} CRM operation(s)"}


class _FieldChange(_Base):
    adapter = "db.field_change"

    def preflight(self, gw, p, payload, appr, rec):
        pol = gw.conn.execute("SELECT * FROM ops.field_policy WHERE entity=%s AND field=%s", (payload["entity"], payload["field"])).fetchone()
        ok = pol is not None and pol["write_mode"] in ("proposal", "direct")
        rec("field_policy", ok, pol and pol["owner_class"])
        if not ok:
            raise gw._stop(p, [], GatewayStatus.BLOCKED, "field_policy_forbids", block_class="hard")

    def run(self, gw, p, payload, appr):
        table = {"opportunity": "gtm.opportunity", "account": "gtm.account", "contact": "gtm.contact"}[payload["entity"]]
        field = payload["field"]
        if not field.replace("_", "").isalnum():
            raise PolicyDenied("bad field name")
        old = gw.conn.execute(f"SELECT {field} AS v FROM {table} WHERE id=%s", (payload["entity_id"],)).fetchone()["v"]
        gw.conn.execute(f"UPDATE {table} SET {field}=%s, updated_at=%s WHERE id=%s", (payload["new_value"], gw.clock.now(), payload["entity_id"]))
        if payload["entity"] == "opportunity" and field == "stage":
            gw.conn.execute("INSERT INTO gtm.stage_history(opportunity_id, from_stage, to_stage, changed_by, at) VALUES (%s,%s,%s,%s,%s)",
                            (payload["entity_id"], old, payload["new_value"], appr["decided_by"], gw.clock.now()))
            audit.append(gw.conn, gw.clock, actor_type="human", actor_id=appr["decided_by"], event_type="opportunity.stage_changed",
                         entity_ref=f"opportunity:{payload['entity_id']}", proposal_id=p["id"], data={"from_stage": old, "to_stage": payload["new_value"]})
        return {"external_ref": f"{payload['entity']}:{payload['entity_id']}:{field}", "old": old, "new": payload["new_value"], "summary": "field changed"}


class _Task(_Base):
    adapter = "db.task"

    def run(self, gw, p, payload, appr):
        r = gw.conn.execute("INSERT INTO gtm.activity(account_id, type, actor, due_at, status, detail, created_at) VALUES (%s,'task',%s,%s,'open',%s,%s) RETURNING id",
                            (p["account_id"], payload["owner"], payload.get("due_at"), Jsonb(payload), gw.clock.now())).fetchone()
        return {"external_ref": f"activity:{r['id']}", "summary": "task created"}


class _Disposition(_Base):
    adapter = "db.lead_disposition"

    def run(self, gw, p, payload, appr):
        status = {"qualified": "routed", "disqualified": "disqualified", "nurture": "archived"}[payload["disposition"]]
        gw.conn.execute("UPDATE gtm.lead SET status=%s, updated_at=%s WHERE id=%s", (status, gw.clock.now(), payload["lead_id"]))
        if payload.get("route_owner"):
            lead = gw.conn.execute("SELECT account_id FROM gtm.lead WHERE id=%s", (payload["lead_id"],)).fetchone()
            if lead and lead["account_id"]:
                gw.conn.execute("UPDATE gtm.account SET owner_principal=%s, updated_at=%s WHERE id=%s", (payload["route_owner"], gw.clock.now(), lead["account_id"]))
        return {"external_ref": f"lead:{payload['lead_id']}", "summary": f"lead {status}"}
