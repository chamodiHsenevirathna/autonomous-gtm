"""Outreach tool simulator: eventually consistent contact import, idempotent sends, pull-style event feed, scripted replies."""
from __future__ import annotations
from datetime import datetime, timedelta
from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import JSONResponse
from gtm.clock import Clock
from gtm.contracts.sims import OutreachImport, OutreachSend, SimEvent
from gtm.contracts.world import ScriptedReply, World
from gtm.world.degrade import unit
from .faults import FaultStore, gate

REPLY_TYPE = {"bounce": "bounce", "unsubscribe": "unsubscribe", "meeting_booked": "meeting_booked"}  # others -> "reply"
ORDER = {"contact_visible": 0, "reply": 1, "bounce": 1, "unsubscribe": 1, "meeting_booked": 2}


class OutreachState:
    def __init__(self, world: World, clock: Clock, faults: FaultStore, auto_replies: bool = False):
        self.world, self.clock, self.faults, self.auto_replies = world, clock, faults, auto_replies
        self.contacts: dict[str, dict] = {}          # outreach contact id -> record
        self.import_keys: dict[str, str] = {}        # idempotency key -> contact id
        self.messages: dict[str, dict] = {}
        self.msg_keys: dict[str, str] = {}
        self.events: list[SimEvent] = []
        self.scheduled: list[dict] = []
        self.suppressed: set[str] = set()
        self._replies = {r.id: r for r in world.replies}
        self._enq_by_email: dict[str, str] = {}
        for e in world.enquiries:
            self._enq_by_email.setdefault(e.email.lower(), e.id)  # duplicates share the original's replies

    # ---- scripting ----
    def schedule_reply(self, reply_id: str, at: datetime, to_email: str | None = None, to_message_id: str | None = None) -> dict:
        rep: ScriptedReply | None = self._replies.get(reply_id)
        if rep is None:
            raise KeyError(reply_id)
        if to_message_id:
            msg = self.messages.get(to_message_id)
            if msg is None:
                raise LookupError(to_message_id)
            to_email = msg["to"]
        if not to_email:
            to_email = next((e.email for e in self.world.enquiries if e.id == rep.to_enquiry_id), None)
        item = {"reply_id": reply_id, "email": to_email.lower(), "at": at, "message_id": to_message_id, "delivered": False}
        self.scheduled.append(item)
        return {"reply_id": reply_id, "email": item["email"], "at": at.isoformat()}

    # ---- time-driven materialisation ----
    def delay_for(self, email: str) -> int:
        return 5 + int(unit(self.world.seed, "outreach_delay", email.lower()) * 116)

    def _find_contact(self, email: str) -> dict | None:
        return next((c for c in self.contacts.values() if c["email"] == email), None)

    def _emit(self, typ: str, ts: datetime, payload: dict) -> None:
        self.events.append(SimEvent(seq=len(self.events) + 1, type=typ, ts=ts, payload=payload))

    def tick(self) -> None:
        now = self.clock.now()
        due = []
        for c in self.contacts.values():
            if not c["dropped"] and not c["announced"] and c["visible_at"] <= now:
                due.append((c["visible_at"], 0, c["id"], "visible", c))
        for i, s in enumerate(self.scheduled):
            if not s["delivered"] and s["at"] <= now:
                due.append((s["at"], 1, f"{i:06d}", "reply", s))
        for ts, _, _, kind, item in sorted(due, key=lambda x: x[:3]):
            if kind == "visible":
                item["announced"] = True
                self._emit("contact_visible", ts, {"contact_id": item["id"], "email": item["email"], "external_key": item["external_key"]})
                continue
            item["delivered"] = True
            rep = self._replies[item["reply_id"]]
            c = self._find_contact(item["email"])
            msg_id = item["message_id"] or next((m["id"] for m in reversed(list(self.messages.values())) if m["to"] == item["email"]), None)
            payload = {"reply_id": rep.id, "email": item["email"], "contact_id": c["id"] if c else None, "message_id": msg_id,
                       "subject": rep.subject, "body": rep.body}
            self._emit(REPLY_TYPE.get(rep.kind, "reply"), ts, payload)
            if rep.kind in ("unsubscribe", "bounce"):
                self.suppressed.add(item["email"])

    def summary(self) -> dict:
        return {"contacts": len(self.contacts), "visible": sum(1 for c in self.contacts.values() if self.is_visible(c)),
                "messages": len(self.messages), "events": len(self.events),
                "scheduled_pending": sum(1 for s in self.scheduled if not s["delivered"]), "suppressed": sorted(self.suppressed)}

    def is_visible(self, c: dict) -> bool:
        return not c["dropped"] and c["visible_at"] <= self.clock.now()


def make_outreach_app(world: World, clock: Clock, faults: FaultStore, state: OutreachState | None = None) -> FastAPI:
    st = state or OutreachState(world, clock, faults)
    app = FastAPI(title="sim outreach")
    app.state.outreach = st

    @app.post("/contacts/import", status_code=202)
    def import_contact(body: OutreachImport, response: Response, idempotency_key: str | None = Header(default=None)):
        o = gate(faults, "outreach", response, ["/contacts/import", body.email, body.crm_contact_id],
                 relevant=("eventual_consistency", "drop_sync"))
        st.tick()
        email = body.email.lower()
        cid = f"oc_{body.crm_contact_id}"
        if idempotency_key and idempotency_key in st.import_keys:
            cid = st.import_keys[idempotency_key]
        existing = st.contacts.get(cid)
        if existing is None:
            now = clock.now()
            delay = o.delay_s if o.delay_s is not None else st.delay_for(email)
            existing = {"id": cid, "import_id": f"imp_{body.crm_contact_id}", "email": email, "external_key": body.crm_contact_id,
                        "full_name": body.full_name, "imported_at": now, "visible_at": now + timedelta(seconds=delay),
                        "dropped": o.drop_sync, "announced": False}
            st.contacts[cid] = existing
        if idempotency_key:
            st.import_keys[idempotency_key] = cid
        return {"import_id": existing["import_id"], "visible_at": existing["visible_at"].isoformat()}

    @app.get("/contacts")
    def lookup(response: Response, external_key: str | None = None, email: str | None = None):
        o = gate(faults, "outreach", response, ["/contacts", external_key or "", email or ""])
        st.tick()
        hits = [c for c in st.contacts.values() if st.is_visible(c)
                and ((external_key is not None and c["external_key"] == external_key) or (email is not None and c["email"] == email.lower()))]
        out = [{"id": c["id"], "email": c["email"], "external_key": c["external_key"], "visible_at": c["visible_at"].isoformat()} for c in hits]
        if o.partial:
            out = [{k: v for k, v in c.items() if k != "email"} for c in out]
        return {"contacts": out}

    @app.post("/messages")
    def send(body: OutreachSend, response: Response, idempotency_key: str | None = Header(default=None)):
        gate(faults, "outreach", response, ["/messages", body.to_address, body.contact_id])
        st.tick()
        if not idempotency_key:
            raise HTTPException(400, {"message": "Idempotency-Key header required"})
        if idempotency_key in st.msg_keys:
            m = st.messages[st.msg_keys[idempotency_key]]
            response.status_code = 200
            return {"message_id": m["id"], "status": "sent"}
        c = st.contacts.get(body.contact_id)
        if c is None:
            raise HTTPException(404, {"message": "unknown contact"})
        if not st.is_visible(c):
            raise HTTPException(422, {"message": "contact not yet visible"})
        if c["email"] in st.suppressed or body.to_address.lower() in st.suppressed:
            return JSONResponse({"message": "suppressed"}, status_code=403)
        mid = f"msg_{len(st.messages) + 1:05d}"
        now = clock.now()
        st.messages[mid] = {"id": mid, "contact_id": c["id"], "to": body.to_address.lower(), "from": body.from_address,
                            "subject": body.subject, "body": body.body, "sent_at": now}
        st.msg_keys[idempotency_key] = mid
        if st.auto_replies:
            enq = st._enq_by_email.get(body.to_address.lower())
            for r in world.replies:
                if r.to_enquiry_id == enq:
                    st.schedule_reply(r.id, now + timedelta(seconds=r.at_offset_s), to_message_id=mid)
        response.status_code = 201
        return {"message_id": mid, "status": "sent"}

    @app.get("/events")
    def events(response: Response, since: int = 0):
        o = gate(faults, "outreach", response, ["/events"], relevant=("duplicate_events", "out_of_order_events"))
        st.tick()
        evs = [e for e in st.events if e.seq > since]
        if o.duplicate_events:
            evs = [e for e in evs for _ in (0, 1)]
        if o.out_of_order_events:
            evs = list(reversed(evs))
        return {"events": [e.model_dump(mode="json") for e in evs]}

    return app
