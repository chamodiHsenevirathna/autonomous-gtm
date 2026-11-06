"""Stall detection and hygiene checks. Pure SQL/rules; no model calls.

Stall flags (is_stalled, stall_reason, days_in_stage) are system-owned and written directly, but only through
`set_opportunity_system_fields`, which checks ops.field_policy for the acting principal. Hygiene findings and the
re-engagement recommendation are PROPOSALS (task); human-owned fields are never written here.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import timedelta
from psycopg import Connection
from .. import audit
from ..approvals import create_proposal
from ..clock import Clock
from ..contracts.events import EventEnvelope, EventType
from ..mcp.field_policy import check_direct_write
from ..mcp.registry import CLOSED_STAGES

MONITOR_PRINCIPAL = "agent:pipeline-monitor"
SYSTEM_FIELDS = ("is_stalled", "stall_reason", "days_in_stage")


@dataclass
class ScanParams:
    inactivity_days: int = 14                       # N
    stage_dwell_days: dict = field(default_factory=lambda: {"default": 30})
    primary_reasons: tuple = ("no_activity", "stage_dwell", "close_date_passed")   # these make a deal stalled
    # no_next_step and single_threaded are risk amplifiers: recorded in stall_reason when the deal is stalled, and reported as hygiene.


def set_opportunity_system_fields(conn: Connection, clock: Clock, *, principal: str, opportunity_id: int, fields: dict) -> bool:
    """Field-policy-checked direct write. Raises PolicyDenied for any field the principal may not write directly. Returns True if changed."""
    for f in fields:
        check_direct_write(conn, "opportunity", f, principal)
    cur = conn.execute("SELECT is_stalled, stall_reason, days_in_stage FROM gtm.opportunity WHERE id=%s", (opportunity_id,)).fetchone()
    if all(cur[k] == v for k, v in fields.items()):
        return False
    conn.execute("UPDATE gtm.opportunity SET " + ", ".join(f"{f}=%s" for f in fields) + ", updated_at=%s WHERE id=%s",
                 [*fields.values(), clock.now(), opportunity_id])
    return True


_OPEN = list(CLOSED_STAGES)
_Q = """
SELECT o.*, 
  GREATEST(o.last_activity_at, o.created_at,
           (SELECT max(created_at) FROM gtm.activity a WHERE a.opportunity_id=o.id),
           (SELECT max(occurred_at) FROM gtm.interaction i WHERE i.account_id=o.account_id)) AS last_act,
  COALESCE((SELECT max(at) FROM gtm.stage_history h WHERE h.opportunity_id=o.id AND h.to_stage=o.stage), o.created_at) AS stage_since,
  (SELECT count(*) FROM gtm.opportunity_contact oc WHERE oc.opportunity_id=o.id) AS n_contacts
FROM gtm.opportunity o WHERE lower(o.stage) <> ALL(%s) ORDER BY o.id
"""


def evaluate(row: dict, now, p: ScanParams) -> dict:
    inactive = (now - row["last_act"]).days
    in_stage = (now - row["stage_since"]).days
    reasons: list[str] = []
    if inactive >= p.inactivity_days:
        reasons.append(f"no_activity:{inactive}d")
    if in_stage > p.stage_dwell_days.get(row["stage"], p.stage_dwell_days["default"]):
        reasons.append(f"stage_dwell:{in_stage}d")
    if row["close_date"] is not None and row["close_date"] < now.date():
        reasons.append("close_date_passed")
    stalled = bool(reasons)
    if stalled and not (row["next_step"] or "").strip():
        reasons.append("no_next_step")
    if stalled and row["n_contacts"] == 1:
        reasons.append("single_threaded")
    return {"stalled": stalled, "reason": ",".join(reasons) if stalled else None, "days_in_stage": in_stage, "inactive_days": inactive}


def _actor(principal: str) -> str:
    return "agent" if principal.startswith("agent:") else "system"


def _hygiene(conn, clock, rows, principal, out: dict) -> None:
    week = clock.now().isocalendar()
    wk = f"{week[0]}w{week[1]}"
    def propose(opp, issue: str, title: str, detail: str, key_extra: str = ""):
        base = f"hygiene:{opp['id']}:{issue}{key_extra}"
        if conn.execute("SELECT 1 FROM ops.proposal WHERE idempotency_key LIKE %s AND status IN ('pending','approved','approved_edited','executing','parked')", (base + ":%",)).fetchone():
            return
        pid = create_proposal(conn, clock, type="task", proposed_by=principal, account_id=opp["account_id"], idempotency_key=f"{base}:{wk}",
                              payload={"owner": opp["owner_principal"] or "unassigned", "title": title, "detail": detail},
                              evidence=[{"type": "sql_rule", "rule": f"hygiene:{issue}", "opportunity_id": opp["id"]}],
                              rationale=detail, confidence=1.0, target_entity={"type": "opportunity", "id": opp["id"]})
        out["proposals"].append(pid)
    for o in rows:
        if o["close_date"] is None:
            propose(o, "missing_close_date", f"Add a close date to '{o['name']}'", "Open opportunity has no close date.")
        if o["amount"] is None:
            propose(o, "missing_amount", f"Add an amount to '{o['name']}'", "Open opportunity has no amount.")
        if not (o["next_step"] or "").strip():
            propose(o, "missing_next_step", f"Record a next step for '{o['name']}'", "Open opportunity has no next step.")
        out["hygiene_issues"] += (o["close_date"] is None) + (o["amount"] is None) + (not (o["next_step"] or "").strip())
    seen: dict = {}
    for o in rows:
        key = (o["account_id"], (o["service_line"] or o["name"]).strip().lower())
        seen.setdefault(key, []).append(o)
    for grp in seen.values():
        if len(grp) > 1:
            keep, dup = grp[0], grp[-1]
            propose(dup, "duplicate_open", f"Review possible duplicate opportunities '{keep['name']}' (#{keep['id']}) and '{dup['name']}' (#{dup['id']})",
                    f"{len(grp)} open opportunities on the same account share a service line or name.", key_extra=f":{keep['id']}")
            out["duplicates"] += 1


def scan_pipeline(conn: Connection, clock: Clock, *, principal: str = MONITOR_PRINCIPAL, params: ScanParams | None = None) -> dict:
    """One scan. Idempotent: re-running with no change writes nothing, emits nothing, proposes nothing new. Caller commits."""
    from ..orchestration.events import emit
    p, now = params or ScanParams(), clock.now()
    rows = conn.execute(_Q, (_OPEN,)).fetchall()
    out = {"scanned": len(rows), "flagged": 0, "cleared": 0, "stalled_total": 0, "proposals": [], "hygiene_issues": 0, "duplicates": 0}
    for o in rows:
        ev = evaluate(o, now, p)
        out["stalled_total"] += ev["stalled"]
        set_opportunity_system_fields(conn, clock, principal=principal, opportunity_id=o["id"],
                                      fields={"is_stalled": ev["stalled"], "stall_reason": ev["reason"], "days_in_stage": ev["days_in_stage"]})
        if ev["stalled"] and not o["is_stalled"]:
            out["flagged"] += 1
            stamp = o["last_act"].isoformat()
            audit.append(conn, clock, actor_type=_actor(principal), actor_id=principal, event_type="deal.stall_flagged", entity_ref=f"opportunity:{o['id']}",
                         data={"reason": ev["reason"], "days_in_stage": ev["days_in_stage"], "inactive_days": ev["inactive_days"]})
            emit(conn, clock, EventEnvelope(type=EventType.DEAL_FLAGGED, account_id=o["account_id"], entity_ref=f"opportunity:{o['id']}",
                                            payload={"opportunity_id": o["id"], "reason": ev["reason"], "inactive_days": ev["inactive_days"]},
                                            occurred_at=now, source=f"pipeline:{principal}", dedupe_key=f"deal.flagged:{o['id']}:{stamp}"))
            pid = create_proposal(conn, clock, type="task", proposed_by=principal, account_id=o["account_id"], idempotency_key=f"stall:{o['id']}:{stamp}",
                                  payload={"owner": o["owner_principal"] or "unassigned", "title": f"Re-engage stalled deal '{o['name']}'",
                                           "detail": f"Flagged stalled: {ev['reason']}."},
                                  evidence=[{"type": "sql_rule", "rule": "stall", "opportunity_id": o["id"], "reason": ev["reason"]}],
                                  rationale=f"No activity for {ev['inactive_days']} days or other stall rule hit: {ev['reason']}", confidence=0.9,
                                  target_entity={"type": "opportunity", "id": o["id"]})
            out["proposals"].append(pid)
        elif not ev["stalled"] and o["is_stalled"]:
            out["cleared"] += 1
            audit.append(conn, clock, actor_type=_actor(principal), actor_id=principal, event_type="deal.stall_cleared", entity_ref=f"opportunity:{o['id']}",
                         data={"inactive_days": ev["inactive_days"]})
    _hygiene(conn, clock, rows, principal, out)
    return out


def build_graphs():
    from ..orchestration import Graph
    g = Graph("pipeline_scan", version="1")
    g.trigger("on_daily_scan", "pipeline.scan")
    g.code("scan_pipeline_rules", lambda ctx: scan_pipeline(ctx.conn, ctx.clock))
    return [g]
