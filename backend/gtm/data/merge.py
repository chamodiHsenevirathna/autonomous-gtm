"""Soft merge, undo and the two Gateway executors (adapters 'db.merge' and 'db.match_confirmation').

Executors follow the gtm.gateway executor protocol: `.adapter`, `preflight`, `final_checks`, `run(gw, p, payload, appr) -> dict`.
Register with `gateway.register_executor("merge", MergeExecutor())` and `("match_confirmation", MatchConfirmationExecutor())`.
Approval of a match_confirmation proposal means 'same'; a rejection means 'distinct' (call `record_match_rejection`).
"""
from __future__ import annotations
from psycopg import Connection
from gtm import audit
from gtm.clock import Clock
from gtm.contracts.gateway import GatewayStatus
from .entity_resolution import record_match
from .survivorship import resolve_fields

TABLE = {"account": "gtm.account", "contact": "gtm.contact"}
# (table, fk column) re-pointed from loser to survivor; ids are logged so undo restores exactly these rows
REPOINT = {"account": [("gtm.contact", "account_id"), ("gtm.lead", "account_id"), ("gtm.opportunity", "account_id"),
                       ("gtm.interaction", "account_id"), ("gtm.activity", "account_id"), ("gtm.buying_signal", "account_id")],
           "contact": [("gtm.lead", "contact_id"), ("gtm.interaction", "contact_id")]}


class MergeError(Exception):
    pass


def _check(conn: Connection, etype: str, loser: int, survivor: int) -> None:
    if etype not in TABLE:
        raise MergeError(f"unknown entity type {etype}")
    if loser == survivor:
        raise MergeError("loser and survivor are the same record")
    rows = {r["id"]: r for r in conn.execute(f"SELECT id, merged_into_id FROM {TABLE[etype]} WHERE id IN (%s,%s)", (loser, survivor))}
    if len(rows) != 2:
        raise MergeError("loser or survivor not found")
    if rows[loser]["merged_into_id"] is not None or rows[survivor]["merged_into_id"] is not None:
        raise MergeError("record already merged")


def soft_merge(conn: Connection, clock: Clock, etype: str, loser_id: int, survivor_id: int, *, approval_id: int | None = None,
               proposal_id: int | None = None, actor: str = "system:gateway") -> int:
    """Non-destructive: loser.merged_into_id is set, observations and children are re-pointed, a merge_log row enables undo."""
    _check(conn, etype, loser_id, survivor_id)
    now = clock.now()
    moved: dict[str, list[int]] = {}
    obs = [r["id"] for r in conn.execute("SELECT id FROM gtm.observation WHERE entity_type=%s AND entity_id=%s ORDER BY id", (etype, loser_id))]
    conn.execute("UPDATE gtm.observation SET entity_id=%s WHERE id = ANY(%s)", (survivor_id, obs))
    moved["observation"] = obs
    for table, col in REPOINT[etype]:
        ids = [r["id"] for r in conn.execute(f"SELECT id FROM {table} WHERE {col}=%s ORDER BY id", (loser_id,))]
        if ids:
            conn.execute(f"UPDATE {table} SET {col}=%s WHERE id = ANY(%s)", (survivor_id, ids))
            moved[f"{table}.{col}"] = ids
    if etype == "account":
        doms = [r["domain"] for r in conn.execute("SELECT domain FROM gtm.account_domain WHERE account_id=%s", (loser_id,))]
        added = []
        for d in doms:
            if conn.execute("INSERT INTO gtm.account_domain(account_id, domain, is_primary) VALUES (%s,%s,false) ON CONFLICT DO NOTHING RETURNING domain", (survivor_id, d)).fetchone():
                added.append(d)
        moved["account_domain_added"] = added
    conn.execute(f"UPDATE {TABLE[etype]} SET merged_into_id=%s, updated_at=%s WHERE id=%s", (survivor_id, now, loser_id))
    conn.execute("DELETE FROM gtm.resolved_field WHERE entity_type=%s AND entity_id=%s", (etype, loser_id))
    log_id = conn.execute("INSERT INTO gtm.merge_log(entity_type, loser_id, survivor_id, moved_observation_count, approval_id, merged_at) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                          (etype, loser_id, survivor_id, len(obs), approval_id, now)).fetchone()["id"]
    audit.append(conn, clock, actor_type="system", actor_id=actor, event_type="merge.executed", entity_ref=f"merge_log:{log_id}", proposal_id=proposal_id,
                 data={"entity_type": etype, "loser_id": loser_id, "survivor_id": survivor_id, "moved": moved})
    resolve_fields(conn, clock, etype, survivor_id)
    return log_id


def undo_merge(conn: Connection, clock: Clock, merge_log_id: int, *, undone_by: str = "system:rules") -> None:
    log = conn.execute("SELECT * FROM gtm.merge_log WHERE id=%s FOR UPDATE", (merge_log_id,)).fetchone()
    if not log:
        raise MergeError("merge_log not found")
    if log["undone_at"] is not None:
        raise MergeError("merge already undone")
    ev = conn.execute("SELECT data FROM ops.audit_event WHERE event_type='merge.executed' AND entity_ref=%s ORDER BY seq LIMIT 1", (f"merge_log:{merge_log_id}",)).fetchone()
    moved = ev["data"]["moved"]
    etype, loser, surv = log["entity_type"], log["loser_id"], log["survivor_id"]
    if moved.get("observation"):
        conn.execute("UPDATE gtm.observation SET entity_id=%s WHERE id = ANY(%s)", (loser, moved["observation"]))
    for key, ids in moved.items():
        if "." in key:
            table, col = key.rsplit(".", 1)
            conn.execute(f"UPDATE {table} SET {col}=%s WHERE id = ANY(%s)", (loser, ids))
    for d in moved.get("account_domain_added", []):
        conn.execute("DELETE FROM gtm.account_domain WHERE account_id=%s AND domain=%s", (surv, d))
    conn.execute(f"UPDATE {TABLE[etype]} SET merged_into_id=NULL, updated_at=%s WHERE id=%s", (clock.now(), loser))
    conn.execute("UPDATE gtm.merge_log SET undone_at=%s WHERE id=%s", (clock.now(), merge_log_id))
    audit.append(conn, clock, actor_type="system", actor_id=undone_by, event_type="merge.undone", entity_ref=f"merge_log:{merge_log_id}",
                 data={"entity_type": etype, "loser_id": loser, "survivor_id": surv})
    resolve_fields(conn, clock, etype, surv)
    resolve_fields(conn, clock, etype, loser)


class _Executor:
    adapter = "none"

    def preflight(self, gw, p, payload, appr, rec): ...
    def final_checks(self, gw, p, payload, appr, rec): ...


class MergeExecutor(_Executor):
    """Payload: {"entity_type": "account"|"contact", "loser_id": int, "survivor_id": int}."""
    adapter = "db.merge"

    def preflight(self, gw, p, payload, appr, rec):
        try:
            _check(gw.conn, payload["entity_type"], int(payload["loser_id"]), int(payload["survivor_id"]))
        except (MergeError, KeyError) as e:
            rec("merge_valid", False, str(e))
            raise gw._stop(p, [], GatewayStatus.BLOCKED, f"merge_invalid: {e}", block_class="hard")
        rec("merge_valid", True)

    def run(self, gw, p, payload, appr):
        log_id = soft_merge(gw.conn, gw.clock, payload["entity_type"], int(payload["loser_id"]), int(payload["survivor_id"]),
                            approval_id=appr["id"], proposal_id=p["id"])
        return {"external_ref": f"merge_log:{log_id}", "merge_log_id": log_id, "summary": "soft merge"}


class MatchConfirmationExecutor(_Executor):
    """Payload (MatchPayload): {"entity_type", "left_id", "right_id", "score"}. Approval records decision='same' (no merge by itself)."""
    adapter = "db.match_confirmation"

    def run(self, gw, p, payload, appr):
        etype, a, b = payload["entity_type"], int(payload["left_id"]), int(payload["right_id"])
        row = gw.conn.execute("SELECT id FROM gtm.entity_match WHERE entity_type=%s AND ((left_id=%s AND right_id=%s) OR (left_id=%s AND right_id=%s))", (etype, a, b, b, a)).fetchone()
        if row:
            gw.conn.execute("UPDATE gtm.entity_match SET decision='same', decided_by=%s, is_negative=false WHERE id=%s", (appr["decided_by"], row["id"]))
            mid = row["id"]
        else:
            mid = record_match(gw.conn, gw.clock, etype, a, b, float(payload.get("score", 0)), {"source": "proposal"}, "possible", "same", appr["decided_by"])
        return {"external_ref": f"entity_match:{mid}", "summary": "match confirmed same"}


def record_match_rejection(conn: Connection, clock: Clock, proposal_id: int) -> int:
    """A rejected match_confirmation proposal means a human said 'distinct': store a negative match so it is never re-asked."""
    p = conn.execute("SELECT * FROM ops.proposal WHERE id=%s AND type='match_confirmation' AND status='rejected'", (proposal_id,)).fetchone()
    if not p:
        raise MergeError("not a rejected match_confirmation proposal")
    d = conn.execute("SELECT decided_by FROM ops.approval_decision WHERE proposal_id=%s AND decision='reject' ORDER BY id DESC LIMIT 1", (proposal_id,)).fetchone()
    pl = p["payload"]
    a, b = int(pl["left_id"]), int(pl["right_id"])
    row = conn.execute("SELECT id FROM gtm.entity_match WHERE entity_type=%s AND ((left_id=%s AND right_id=%s) OR (left_id=%s AND right_id=%s))", (pl["entity_type"], a, b, b, a)).fetchone()
    if row:
        conn.execute("UPDATE gtm.entity_match SET decision='distinct', decided_by=%s, is_negative=true WHERE id=%s", (d["decided_by"], row["id"]))
        return row["id"]
    return record_match(conn, clock, pl["entity_type"], a, b, float(pl.get("score", 0)), {"source": "proposal"}, "possible", "distinct", d["decided_by"], True)


def propose_merge(conn: Connection, clock: Clock, etype: str, loser_id: int, survivor_id: int, *, proposed_by: str = "system:rules",
                  account_id: int | None = None, rationale: str | None = None, emit=None) -> int:
    from gtm.approvals import create_proposal
    return create_proposal(conn, clock, type="merge", proposed_by=proposed_by, account_id=account_id,
                           payload={"entity_type": etype, "loser_id": loser_id, "survivor_id": survivor_id},
                           rationale=rationale or "confirmed duplicate", idempotency_key=f"merge:{etype}:{loser_id}:{survivor_id}", emit=emit)
