"""Context pack (docs/account-agents.md section 6) and the deterministic change detector. No model calls."""
from __future__ import annotations
import hashlib, json
from datetime import timedelta
from psycopg import Connection
from gtm.clock import Clock
from gtm.data import get_resolved

TOKEN_BUDGET = 6000
MATERIAL_EVENTS = {"lead.qualified", "reply.received", "meeting.booked", "deal.flagged", "feedback.captured", "signal.detected",
                   "opportunity.stage_changed", "opportunity.closed_lost", "execution.completed", "execution.failed"}
STALE_WAKE_DAYS = 30        # time threshold: review at least this often when an opportunity is open
STALL_RECHECK_DAYS = 7


def _tok(o) -> int:
    return max(1, len(json.dumps(o, default=str)) // 4)


def _plain(rows):
    return [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()} for r in rows]


def get_state(conn: Connection, account_id: int) -> dict | None:
    return conn.execute("SELECT * FROM gtm.account_agent_state WHERE account_id=%s", (account_id,)).fetchone()


def build_context_pack(conn: Connection, clock: Clock, account_id: int, *, budget: int = TOKEN_BUDGET) -> dict:
    now = clock.now()
    acct = conn.execute("SELECT * FROM gtm.account WHERE id=%s", (account_id,)).fetchone()
    st = get_state(conn, account_id)
    since = st["last_woken_at"] if st and st["last_woken_at"] else None
    resolved = {f: {"value": r.get("value"), "confidence": r.get("confidence"), "freshness": r.get("freshness_state"),
                    "conflict": r.get("conflict_flag"), "sources": [s if isinstance(s, str) else s.get("source") for s in r.get("sources", [])]}
                for f, r in get_resolved(conn, "account", account_id).items()}
    parent = conn.execute("SELECT id, name FROM gtm.account WHERE id=%s", (acct["parent_account_id"],)).fetchone() if acct["parent_account_id"] else None
    children = conn.execute("SELECT id, name FROM gtm.account WHERE parent_account_id=%s ORDER BY id", (account_id,)).fetchall()
    opps = conn.execute("SELECT id, name, stage, amount, owner_principal, is_stalled, stall_reason, days_in_stage, last_activity_at, external_ids FROM gtm.opportunity WHERE account_id=%s ORDER BY id", (account_id,)).fetchall()
    hist = conn.execute("SELECT opportunity_id, from_stage, to_stage, changed_by, at FROM gtm.stage_history WHERE opportunity_id = ANY(%s) ORDER BY at", ([o["id"] for o in opps],)).fetchall()
    contacts = conn.execute("SELECT id, full_name, email, title, seniority, email_status, external_ids FROM gtm.contact WHERE account_id=%s AND merged_into_id IS NULL ORDER BY id", (account_id,)).fetchall()
    inter = conn.execute("SELECT id, contact_id, channel, direction, occurred_at, subject, body, classification FROM gtm.interaction WHERE account_id=%s ORDER BY occurred_at, id", (account_id,)).fetchall()
    new = [i for i in inter if since is None or i["occurred_at"] > since]
    old = [i for i in inter if i not in new][-5:]
    signals = conn.execute("SELECT id, type, description, strength, observed_at, expires_at FROM gtm.buying_signal WHERE account_id=%s AND (expires_at IS NULL OR expires_at > %s) ORDER BY observed_at", (account_id, now)).fetchall()
    fb = conn.execute("SELECT p.id, p.type, d.decision, d.reason_code, d.comment, d.decided_at FROM ops.approval_decision d JOIN ops.proposal p ON p.id=d.proposal_id WHERE p.account_id=%s ORDER BY d.decided_at DESC LIMIT 10", (account_id,)).fetchall()
    cids = [c["id"] for c in contacts]
    sup = conn.execute("SELECT scope, value, reason FROM gtm.suppression WHERE lifted_at IS NULL AND ((scope='account' AND value=%s) OR (scope='contact' AND value = ANY(%s)) "
                       "OR (scope='address' AND lower(value) = ANY(%s)))", (str(account_id), [str(c) for c in cids], [(c["email"] or "").lower() for c in contacts])).fetchall()
    claims = conn.execute("SELECT purpose, holder_ref FROM gtm.outreach_claim WHERE entity_type='contact' AND entity_id = ANY(%s) AND released_at IS NULL", (cids,)).fetchall()
    pending = conn.execute("SELECT id, type, status FROM ops.proposal WHERE account_id=%s AND status IN ('pending','approved','approved_edited','parked') ORDER BY id", (account_id,)).fetchall()
    sections = [  # priority order; later sections are trimmed first when over budget
        ("account", {"id": account_id, "name": acct["name"], "domain": acct["primary_domain"], "status": acct["status"], "owner": acct["owner_principal"],
                     "external_ids": acct["external_ids"], "ai": {k: acct[k] for k in ("ai_summary", "ai_risk_level", "ai_next_action")},
                     "resolved_fields": resolved, "hierarchy": {"parent": dict(parent) if parent else None, "children": _plain(children)}}),
        ("opportunities", {"items": _plain(opps), "stage_history": _plain(hist)}),
        ("agent_state", {k: (st[k] if not hasattr(st[k], "isoformat") else st[k].isoformat()) for k in ("version", "lifecycle", "summary", "stakeholder_map", "commitments", "risks", "open_questions", "next_actions", "last_woken_at")} if st else None),
        ("interactions_since_review", {"items": _plain(new), "untrusted_text": True}),
        ("older_interactions", {"items": [dict(x, body=(x["body"] or "")[:200]) for x in _plain(old)], "untrusted_text": True}),
        ("signals", {"items": _plain(signals)}),
        ("feedback_digest", {"items": _plain(fb)}),
        ("constraints", {"suppressions": _plain(sup), "outreach_claims": _plain(claims), "owner": acct["owner_principal"], "pending_proposals": _plain(pending)}),
        ("contacts", {"items": _plain(contacts)}),
    ]
    pack, used, trimmed = {}, 0, []
    for name, body in sections:
        t = _tok(body)
        if used + t > budget and name in ("older_interactions", "signals", "feedback_digest", "contacts"):
            trimmed.append(name); continue
        pack[name] = body; used += t
    pack["meta"] = {"account_id": account_id, "tokens_est": used, "budget": budget, "trimmed": trimmed}
    pack["content_hash"] = hashlib.sha256(json.dumps({k: v for k, v in pack.items() if k != "meta"}, sort_keys=True, default=str).encode()).hexdigest()
    return pack


def change_detector(conn: Connection, clock: Clock, account_id: int, event_type: str | None = None) -> dict:
    """Deterministic: is there anything material since the last review? If not, the caller makes no model call."""
    now = clock.now()
    st = get_state(conn, account_id)
    since = st["last_woken_at"] if st else None
    reasons: list[str] = []
    if event_type in MATERIAL_EVENTS:
        reasons.append(f"event:{event_type}")
    if since is None:
        reasons.append("never_reviewed")
    else:
        n = conn.execute("SELECT count(*) n FROM gtm.interaction WHERE account_id=%s AND direction='inbound' AND occurred_at > %s", (account_id, since)).fetchone()["n"]
        if n:
            reasons.append(f"new_interactions:{n}")
        n = conn.execute("SELECT count(*) n FROM gtm.stage_history h JOIN gtm.opportunity o ON o.id=h.opportunity_id WHERE o.account_id=%s AND h.at > %s", (account_id, since)).fetchone()["n"]
        if n:
            reasons.append(f"stage_changes:{n}")
        n = conn.execute("SELECT count(*) n FROM ops.approval_decision d JOIN ops.proposal p ON p.id=d.proposal_id WHERE p.account_id=%s AND d.decided_at > %s", (account_id, since)).fetchone()["n"]
        if n:
            reasons.append(f"approvals_decided:{n}")
        n = conn.execute("SELECT count(*) n FROM gtm.buying_signal WHERE account_id=%s AND observed_at > %s", (account_id, since)).fetchone()["n"]
        if n:
            reasons.append(f"new_signals:{n}")
        open_opp = conn.execute("SELECT count(*) n FROM gtm.opportunity WHERE account_id=%s AND stage NOT IN ('closed_won','closed_lost')", (account_id,)).fetchone()["n"]
        if open_opp and now - since >= timedelta(days=STALE_WAKE_DAYS):
            reasons.append("time_threshold")
        stalled = conn.execute("SELECT count(*) n FROM gtm.opportunity WHERE account_id=%s AND is_stalled", (account_id,)).fetchone()["n"]
        if stalled and now - since >= timedelta(days=STALL_RECHECK_DAYS):
            reasons.append("stall_flag")
    return {"material": bool(reasons), "reasons": reasons, "since": since.isoformat() if since else None}
