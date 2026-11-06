"""match_resume: continue leads held as 'match_pending' once the human decided the G1 match proposal(s).
approved (executed by the gateway) = same entity -> link to the existing record; rejected = distinct -> keep the new records.
Nothing is merged here; the lead is re-submitted to inbound_intake with a `resume` payload (idempotent per lead and proposal)."""
from __future__ import annotations
from gtm.data import record_match_rejection
from gtm.data.merge import MergeError
from gtm.orchestration import Graph


def _decision(status: str) -> str | None:
    return "same" if status == "executed" else "distinct" if status == "rejected" else None


def _scan(ctx):
    ref = ctx.trigger.entity_ref or ""
    if not ref.startswith("proposal:"):
        return {"resumed": []}
    pid, c = int(ref.split(":", 1)[1]), ctx.conn
    p = c.execute("SELECT * FROM ops.proposal WHERE id=%s", (pid,)).fetchone()
    if not p or p["type"] != "match_confirmation" or _decision(p["status"]) is None:
        return {"resumed": []}
    if p["status"] == "rejected":
        try:
            record_match_rejection(c, ctx.clock, pid)
        except MergeError:
            pass
    et, left = p["payload"]["entity_type"], int(p["payload"]["left_id"])
    col = "account_id" if et == "account" else "contact_id"
    resumed = []
    for lead in c.execute(f"SELECT * FROM gtm.lead WHERE status='held' AND held_reason='match_pending' AND {col}=%s ORDER BY id", (left,)).fetchall():
        acct, cont, is_open, has_acct_q = lead["account_id"], lead["contact_id"], False, False
        for mp in c.execute("SELECT * FROM ops.proposal WHERE type='match_confirmation' ORDER BY id").fetchall():
            pl = mp["payload"]
            mine = (pl["entity_type"] == "account" and int(pl["left_id"]) == lead["account_id"]) or (pl["entity_type"] == "contact" and int(pl["left_id"]) == lead["contact_id"])
            if not mine:
                continue
            d = _decision(mp["status"])
            has_acct_q |= pl["entity_type"] == "account"
            if d is None:
                is_open = True                  # another match question for this lead is still open
            elif d == "same":
                if pl["entity_type"] == "account":
                    acct = int(pl["right_id"])
                else:
                    cont = int(pl["right_id"])
        if is_open:
            continue
        # invariant: a lead's contact belongs to the lead's account
        if cont != lead["contact_id"]:                  # linked to an existing contact: the account follows that contact
            rc = c.execute("SELECT account_id FROM gtm.contact WHERE id=%s", (cont,)).fetchone()
            acct = (rc and rc["account_id"]) or acct
        elif acct != lead["account_id"]:                # linked to an existing account: move this lead's own new contact under it
            c.execute("UPDATE gtm.contact SET account_id=%s, updated_at=%s WHERE id=%s", (acct, ctx.clock.now(), cont))
            ctx.audit("lead.contact_moved", {"contact_id": cont, "to_account": acct}, entity_ref=f"lead:{lead['id']}")
        raw = lead["raw_payload"]
        ctx.emit("lead.received", {"lead_id": lead["id"], "enquiry_id": raw.get("enquiry_id"), "resume": {"proposal_id": pid, "account_id": acct, "contact_id": cont}},
                 entity_ref=f"lead:{lead['id']}", account_id=None, dedupe_key=f"lead.received:{raw.get('enquiry_id')}:resume:{acct}:{cont}", source="match_resume")
        resumed.append(lead["id"])
    return {"resumed": []}
    pid, c = int(ref.split(":", 1)[1]), ctx.conn
    p = c.execute("SELECT * FROM ops.proposal WHERE id=%s", (pid,)).fetchone()
    if not p or p["type"] != "match_confirmation" or _decision(p["status"]) is None:
        return {"resumed": []}
    if p["status"] == "rejected":
        try:
            record_match_rejection(c, ctx.clock, pid)
        except MergeError:
            pass
    et, left = p["payload"]["entity_type"], int(p["payload"]["left_id"])
    col = "account_id" if et == "account" else "contact_id"
    resumed = []
    for lead in c.execute(f"SELECT * FROM gtm.lead WHERE status='held' AND held_reason='match_pending' AND {col}=%s ORDER BY id", (left,)).fetchall():
        acct, cont = lead["account_id"], lead["contact_id"]
        for mp in c.execute("SELECT * FROM ops.proposal WHERE type='match_confirmation' AND (payload->>'left_id')::bigint = ANY(%s) ORDER BY id", ([a for a in (acct, cont) if a],)).fetchall():
            d = _decision(mp["status"])
            if mp["payload"]["entity_type"] == "account" and int(mp["payload"]["left_id"]) == acct or mp["payload"]["entity_type"] == "contact" and int(mp["payload"]["left_id"]) == cont:
                if d is None:
                    break                       # another match question for this lead is still open
                right = int(mp["payload"]["right_id"])
                if d == "same":
                    if mp["payload"]["entity_type"] == "account":
                        acct = right
                    else:
                        cont = right
                        rc = c.execute("SELECT account_id FROM gtm.contact WHERE id=%s", (right,)).fetchone()
                        if rc and rc["account_id"] and not any(x["payload"]["entity_type"] == "account" and _decision(x["status"]) == "same" for x in [mp]):
                            acct = acct if lead["account_id"] != acct else rc["account_id"]
        else:
            raw = lead["raw_payload"]
            ctx.emit("lead.received", {"lead_id": lead["id"], "enquiry_id": raw.get("enquiry_id"), "resume": {"proposal_id": pid, "account_id": acct, "contact_id": cont}},
                     entity_ref=f"lead:{lead['id']}", account_id=None, dedupe_key=f"lead.received:{raw.get('enquiry_id')}:resume:{acct}:{cont}", source="match_resume")
            resumed.append(lead["id"])
    return {"resumed": resumed, "proposal_id": pid, "decision": _decision(p["status"])}


def build_graph() -> Graph:
    g = Graph("match_resume", "1")
    g.trigger("on_match_decided", ["execution.completed", "proposal.rejected"])
    g.code("find_resumable_leads", _scan)
    return g
