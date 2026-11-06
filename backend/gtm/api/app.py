"""Dashboard API (frontend/API_SPEC.md). One Runtime on the demo DB guarded by a lock; state-changing calls run the system to quiet."""
from __future__ import annotations
import importlib, threading
from datetime import timedelta
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from psycopg.types.json import Jsonb
from gtm import audit, db
from gtm.approvals import ApprovalError, decide
from gtm.config import get_settings
from gtm.contracts.api import DecisionIn
from gtm.gateway import gateway_for
from gtm.harness import Harness
from gtm.runtime import Runtime
from . import views
from .schemas import LostDealReviewIn

GOLDEN = {"S01-golden-enquiry": "enq_001", "S01-golden-reply": "rpl_001"}
DATA_NOTICE = "All data is synthetic. Model outputs are produced by a deterministic mock unless live mode is enabled."
VITE_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
ERR_STATUS = {"not_found": 404, "not_pending": 409, "expired": 409, "role": 403, "distinct_approver": 403, "not_human": 403,
              "invalid_edit": 422, "commercial_block": 422}


class ApiState:
    def __init__(self, url: str, reset: bool = True):
        self.url, self.lock = url, threading.RLock()
        db.ensure_database(url)
        db.migrate(url)
        self.rt = Runtime(url, reset=reset)
        self.h = Harness.__new__(Harness)
        self.h.rt = self.rt
        self.demo_enquiries: set[str] = set()
        self.demo_replies: set[str] = set()

    @property
    def conn(self):
        return self.rt.conn

    def quiet(self, advance_clock: bool = False) -> None:
        self.h.run_until_idle(advance_clock=advance_clock)
        self.conn.commit()

    def rebuild(self) -> None:
        self.rt.build(42, "mock", None, reset=True)
        self.demo_enquiries.clear()
        self.demo_replies.clear()


class _SimProxy:
    """ASGI proxy so a rebuilt Runtime's simulators stay mounted. The root sims app already uses /sim/... paths."""
    def __init__(self, st: ApiState):
        self.st = st

    async def __call__(self, scope, receive, send):
        scope = dict(scope, path="/sim" + scope["path"][len(scope.get("root_path", "")):] if scope.get("root_path") else scope["path"])
        scope["root_path"] = ""
        await self.st.rt.sims.app(scope, receive, send)


def _mod(name: str):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        return None


def create_app(database_url: str | None = None, *, reset: bool = True) -> FastAPI:
    st = ApiState(database_url or get_settings().database_url, reset)
    app = FastAPI(title="Autonomous GTM dashboard API")
    app.state.api = st
    app.add_middleware(CORSMiddleware, allow_origins=VITE_ORIGINS, allow_methods=["*"], allow_headers=["*"])
    app.mount("/sim", _SimProxy(st))

    def read(fn):
        with st.lock:
            try:
                return fn(st.conn)
            finally:
                st.conn.rollback()

    @app.get("/api/health")
    def health():
        def f(c):
            c.execute("SELECT 1")
            return {"ok": True, "db": True, "clock": views.iso(st.rt.clock.now())}
        return read(f)

    @app.get("/api/config")
    def config():
        return {"llm_mode": st.rt.settings.llm_mode, "live_enabled": bool(st.rt.settings.live_enabled()), "data_notice": DATA_NOTICE}

    @app.get("/api/overview")
    def overview():
        return read(lambda c: views.overview(c, st.rt.clock.now()))

    @app.get("/api/leads")
    def leads():
        return read(views.leads)

    @app.get("/api/accounts")
    def accounts():
        return read(views.accounts)

    @app.get("/api/accounts/{account_id}")
    def account(account_id: int):
        def f(c):
            a = c.execute("SELECT * FROM gtm.account WHERE id=%s", (account_id,)).fetchone()
            if not a:
                raise HTTPException(404, f"account {account_id} not found")
            return {**views.account_row(c, a), "fields": views.account_fields(c, a, st.rt.clock.now()),
                    "agent_state": views.agent_state(c, account_id, st.rt.settings.llm_mode), "interactions": views.interactions(c, account_id),
                    "proposals": views.list_proposals(c, account_id=account_id), "opportunities": views.opportunities(c, account_id)}
        return read(f)

    @app.get("/api/opportunities")
    def opportunities():
        return read(views.opportunities)

    @app.get("/api/pipeline/alerts")
    def alerts():
        return read(views.alerts)

    @app.get("/api/proposals")
    def proposals(status: str | None = None):
        return read(lambda c: views.list_proposals(c, status))

    def one_proposal(c, pid: int) -> dict:
        p = c.execute("SELECT * FROM ops.proposal WHERE id=%s", (pid,)).fetchone()
        if not p:
            raise HTTPException(404, f"proposal {pid} not found")
        return views.proposal_out(c, p)

    @app.get("/api/proposals/{pid}")
    def proposal(pid: int):
        return read(lambda c: one_proposal(c, pid))

    @app.post("/api/proposals/{pid}/decision")
    def decision(pid: int, body: DecisionIn):
        with st.lock:
            c = st.conn
            try:
                p = c.execute("SELECT * FROM ops.proposal WHERE id=%s", (pid,)).fetchone()
                if not p:
                    raise HTTPException(404, f"proposal {pid} not found")
                if body.decision == "reject" and not body.reason_code:
                    raise HTTPException(422, "reason_code is required to reject")
                if body.decision == "approve_with_edits" and not body.edited_payload:
                    raise HTTPException(422, "edited_payload (the complete replacement payload) is required for approve_with_edits")
                if p["depends_on_proposal_id"]:
                    d = c.execute("SELECT status FROM ops.proposal WHERE id=%s", (p["depends_on_proposal_id"],)).fetchone()
                    if d and d["status"] != "executed":
                        raise HTTPException(409, f"Blocked: proposal #{p['depends_on_proposal_id']} must be executed first (it is {d['status']})")
                try:
                    decide(c, st.rt.clock, proposal_id=pid, decided_by=body.decided_by, decision=body.decision, edited_payload=body.edited_payload,
                           reason_code=body.reason_code, comment=body.comment)
                except ApprovalError as e:
                    c.rollback()
                    raise HTTPException(ERR_STATUS.get(e.code, 422), str(e))
                c.commit()
                st.quiet()
                cur = c.execute("SELECT status FROM ops.proposal WHERE id=%s", (pid,)).fetchone()["status"]
                if cur in ("approved", "approved_edited") and body.decision != "reject":
                    gateway_for(c, st.rt.clock, st.rt.services).attempt(pid)   # no execute_proposal workflow registered: run the gateway directly
                    c.commit()
                    st.quiet()
                return one_proposal(c, pid)
            except HTTPException:
                c.rollback()
                raise
            except Exception:
                c.rollback()
                raise
            finally:
                c.rollback()

    @app.get("/api/runs")
    def runs():
        return read(lambda c: [views.run_row(c, r) for r in c.execute("SELECT * FROM ops.agent_run ORDER BY id DESC").fetchall()])

    @app.get("/api/runs/{rid}")
    def run(rid: int):
        def f(c):
            r = c.execute("SELECT * FROM ops.agent_run WHERE id=%s", (rid,)).fetchone()
            if not r:
                raise HTTPException(404, f"run {rid} not found")
            return views.run_row(c, r, views._steps(c, r, st.rt.settings.llm_mode))
        return read(f)

    @app.get("/api/audit")
    def audit_list(limit: int = 100):
        return read(lambda c: views.audit_rows(c, max(1, min(limit, 1000))))

    @app.get("/api/audit/verify")
    def audit_verify():
        ok, n, bad = read(audit.verify_chain)
        return {"ok": ok, "checked": n, "first_bad_seq": bad}

    @app.get("/api/events")
    def events(limit: int = 100):
        return read(lambda c: views.events(c, max(1, min(limit, 1000))))

    @app.get("/api/evals")
    def evals():
        from .evals import latest_summary
        return read(latest_summary)

    @app.post("/api/evals/run")
    def evals_run(body: dict | None = None):
        from .evals import run_eval
        return run_eval(st, (body or {}).get("scenarios"))

    @app.get("/api/feedback")
    def feedback():
        return read(views.feedback)

    @app.post("/api/lost-deal-reviews")
    def lost_deal_review(body: LostDealReviewIn):
        with st.lock:
            c = st.conn
            try:
                opp = body.opportunity_id
                if opp is None and body.account_id is not None:
                    r = c.execute("SELECT id FROM gtm.opportunity WHERE account_id=%s ORDER BY id DESC LIMIT 1", (body.account_id,)).fetchone()
                    opp = r["id"] if r else None
                if opp is None or not c.execute("SELECT 1 FROM gtm.opportunity WHERE id=%s", (opp,)).fetchone():
                    raise HTTPException(422, "A lost-deal review needs an existing opportunity (opportunity_id, or an account that has one)")
                fb = _mod("gtm.feedback")
                if fb is not None and hasattr(fb, "save_lost_deal_review"):
                    try:
                        res = fb.save_lost_deal_review(c, st.rt.clock, opportunity_id=opp, reason_code=body.reason_code, primary_reason=body.primary_reason,
                                                       competitor=body.competitor, could_we_have_won=body.could_we_have_won,
                                                       what_would_change_it=body.what_would_change_it, verbatim_quotes=body.verbatim_quotes, reviewer=body.reviewer)
                        rid = res["id"] if isinstance(res, dict) else int(res)
                        c.commit()
                        st.quiet()
                        return {"id": rid, "feedback_id": rid, "created_at": views.iso(st.rt.clock.now()), "ok": True}
                    except TypeError:
                        c.rollback()
                now = st.rt.clock.now()
                notes = f"could_we_have_won={body.could_we_have_won}; what_would_change_it={body.what_would_change_it}"
                rid = c.execute("INSERT INTO gtm.lost_deal_review(opportunity_id, primary_reason, secondary_reasons, competitor, notes, captured_by, ai_suggested_tags, created_at) "
                                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id", (opp, body.primary_reason, [f"reason:{body.reason_code}"], body.competitor, notes,
                                                                                   body.reviewer, Jsonb([]), now)).fetchone()["id"]
                acct = c.execute("SELECT account_id FROM gtm.opportunity WHERE id=%s", (opp,)).fetchone()["account_id"]
                for q in body.verbatim_quotes:
                    c.execute("INSERT INTO gtm.feedback_item(lost_deal_review_id, account_id, source_type, kind, label, quote, speaker_role, review_status, created_at) "
                              "VALUES (%s,%s,'lost_deal_review','lost_reason',%s,%s,'prospect','confirmed',%s)", (rid, acct, body.reason_code, q, now))
                audit.append(c, st.rt.clock, actor_type="human", actor_id=body.reviewer, event_type="lost_deal_review.saved", entity_ref=f"lost_deal_review:{rid}",
                             data={"opportunity_id": opp, "reason_code": body.reason_code})
                c.commit()
                return {"id": rid, "feedback_id": rid, "created_at": views.iso(now), "ok": True}
            except HTTPException:
                c.rollback()
                raise
            finally:
                c.rollback()

    # ------------------------------------------------------------------ demo
    def result(ok: bool, message: str, created: dict | None = None) -> dict:
        return {"ok": ok, "message": message, "clock": views.iso(st.rt.clock.now()), "created": created or {}}

    @app.post("/api/demo/enquiry")
    def demo_enquiry(body: dict):
        eid = GOLDEN.get(str(body.get("enquiry_id")), str(body.get("enquiry_id")))
        with st.lock:
            if not any(e.id == eid for e in st.rt.world.enquiries):
                return result(False, f"Unknown enquiry id {body.get('enquiry_id')!r}.")
            if eid in st.demo_enquiries:
                return result(False, f"Enquiry {eid} was already submitted; reset the demo to replay it.")
            if _mod("gtm.agents.intake") is None:
                return result(False, "The intake workflow (gtm.agents.intake) is not available yet, so enquiries cannot be submitted.")
            try:
                lead_id = st.h.deliver_enquiry(eid)
                st.demo_enquiries.add(eid)
                st.quiet()
                c = st.conn
                lead = c.execute("SELECT account_id FROM gtm.lead WHERE id=%s", (lead_id,)).fetchone()
                pids = [r["id"] for r in c.execute("SELECT id FROM ops.proposal WHERE account_id=%s ORDER BY id", (lead["account_id"] if lead else None,))]
                return result(True, f"Enquiry {eid} submitted and processed; proposals wait for your decision.",
                              {"lead_id": lead_id, "account_id": lead["account_id"] if lead else None, "proposal_ids": pids})
            except Exception as e:
                st.conn.rollback()
                return result(False, f"Could not submit the enquiry: {type(e).__name__}: {e}")
            finally:
                st.conn.rollback()

    @app.post("/api/demo/reply")
    def demo_reply(body: dict):
        rid = GOLDEN.get(str(body.get("reply_id")), str(body.get("reply_id")))
        with st.lock:
            rep = next((r for r in st.rt.world.replies if r.id == rid), None)
            if rep is None:
                return result(False, f"Unknown reply id {body.get('reply_id')!r}.")
            if rid in st.demo_replies:
                return result(False, f"Reply {rid} was already delivered.")
            enq = next(e for e in st.rt.world.enquiries if e.id == rep.to_enquiry_id)
            msgs = st.rt.sims.outreach_state.messages.values()
            if not any(m["to"] == enq.email.lower() for m in msgs):
                return result(False, "No message has been sent to this prospect yet. Approve and execute the intro reply first.")
            try:
                st.rt.sims.script_reply(rid, to_email=enq.email, at=st.rt.clock.now() + timedelta(seconds=30))
                st.demo_replies.add(rid)
                st.rt.clock.advance(31)
                st.quiet()
                return result(True, f"Scripted reply {rid} ({rep.kind}) arrived and was processed.", {"reply_id": rid, "kind": rep.kind})
            except Exception as e:
                st.conn.rollback()
                return result(False, f"Could not deliver the reply: {type(e).__name__}: {e}")
            finally:
                st.conn.rollback()

    @app.post("/api/demo/advance")
    def demo_advance(body: dict):
        try:
            secs = float(body.get("seconds", 0))
        except (TypeError, ValueError):
            return result(False, "seconds must be a number")
        if secs <= 0 or secs > 30 * 86400:
            return result(False, "seconds must be between 1 and 2592000 (30 days)")
        with st.lock:
            try:
                n = max(1, min(24, int(secs // 60)))
                for _ in range(n):
                    st.rt.clock.advance(secs / n)
                    st.quiet()
                return result(True, f"Advanced the simulated clock by {int(secs)} seconds.")
            finally:
                st.conn.rollback()

    @app.post("/api/demo/reset")
    def demo_reset(body: dict | None = None):
        with st.lock:
            st.rebuild()
            return result(True, "Demo reset: database and simulated world rebuilt.")

    return app
