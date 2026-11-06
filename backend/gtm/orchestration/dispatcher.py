"""Gap-safe dispatcher: claims pending dispatch rows with SKIP LOCKED (never a cursor over seq)."""
from __future__ import annotations
from datetime import timedelta
from typing import Callable
from psycopg import Connection
from psycopg.types.json import Jsonb
from ..clock import Clock
from ..contracts.events import EventEnvelope, EventType
from .events import emit, row_to_env

STALE_SQL = """SELECT 1 FROM ops.dispatch d2 JOIN ops.domain_event e2 ON e2.id=d2.event_id
 WHERE d2.subscription_id=%(sub)s AND d2.status IN ('enqueued','done') AND e2.entity_ref=%(ref)s AND e2.type=%(type)s AND e2.id<>%(eid)s
   AND (CASE WHEN %(ver)s::bigint IS NOT NULL AND e2.source_version IS NOT NULL THEN e2.source_version > %(ver)s
             ELSE e2.occurred_at > %(at)s END) LIMIT 1"""


class Dispatcher:
    """lifecycle(conn, env, workflow) -> bool is the lifecycle filter hook (False: consume without waking, status 'done').
    Coalescing comes from the target Graph (coalesce_seconds, coalesce_key(env)). `graphs` maps workflow name -> Graph."""

    def __init__(self, conn: Connection, clock: Clock, graphs: dict | None = None, *,
                 lifecycle: Callable[[Connection, EventEnvelope, str], bool] | None = None, max_attempts: int = 3):
        self.conn, self.clock, self.graphs, self.lifecycle, self.max_attempts = conn, clock, graphs if graphs is not None else {}, lifecycle, max_attempts

    def claim(self, limit: int = 100) -> list[dict]:
        """Lock up to `limit` pending rows (kept locked until commit/rollback)."""
        return self.conn.execute(
            "SELECT d.id AS did, d.attempts, d.subscription_id AS sub, e.id AS eid, e.*, s.workflow FROM ops.dispatch d "
            "JOIN ops.domain_event e ON e.id=d.event_id JOIN ops.subscription s ON s.id=d.subscription_id "
            "WHERE d.status='pending' ORDER BY d.id LIMIT %s FOR UPDATE OF d SKIP LOCKED", (limit,)).fetchall()

    def process(self, limit: int = 100, rows: list[dict] | None = None) -> int:
        rows = self.claim(limit) if rows is None else rows
        for r in rows:
            try:
                with self.conn.transaction():
                    status = self._one(r)
                    self.conn.execute("UPDATE ops.dispatch SET status=%s WHERE id=%s", (status, r["did"]))
            except Exception as e:
                n = r["attempts"] + 1
                dead = n >= self.max_attempts
                self.conn.execute("UPDATE ops.dispatch SET attempts=%s, status=%s WHERE id=%s", (n, "dead" if dead else "pending", r["did"]))
                if dead:
                    emit(self.conn, self.clock, EventEnvelope(
                        type=EventType.JOB_DEAD, account_id=r["account_id"], entity_ref=f"dispatch:{r['did']}", occurred_at=self.clock.now(),
                        source="dispatcher", dedupe_key=f"job.dead:dispatch:{r['did']}", payload={"kind": "dispatch", "error": repr(e)}))
        self.conn.commit()
        return len(rows)

    def _one(self, r: dict) -> str:
        env = row_to_env(r)
        if self.lifecycle and not self.lifecycle(self.conn, env, r["workflow"]):
            return "done"
        if r["entity_ref"] and self.conn.execute(STALE_SQL, {"sub": r["sub"], "ref": r["entity_ref"], "type": r["type"], "eid": r["eid"],
                                                              "ver": r["source_version"], "at": r["occurred_at"]}).fetchone():
            return "ignored_stale"
        g = self.graphs.get(r["workflow"])
        ckey = g.coalesce_key(env) if g and g.coalesce_seconds and g.coalesce_key else None
        if ckey:
            j = self.conn.execute("SELECT id FROM ops.job WHERE workflow=%s AND status='queued' AND run_id IS NULL "
                                  "AND payload->>'coalesce_key'=%s ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED", (r["workflow"], ckey)).fetchone()
            if j:
                self.conn.execute("UPDATE ops.job SET payload=jsonb_set(payload,'{event_ids}',payload->'event_ids' || to_jsonb(%s::bigint)) WHERE id=%s",
                                  (r["eid"], j["id"]))
                return "enqueued"
        at = self.clock.now() + (timedelta(seconds=g.coalesce_seconds) if ckey and g.coalesce_delay else timedelta())
        self.conn.execute(
            "INSERT INTO ops.job(workflow, target, available_at, idempotency_key, payload) VALUES (%s,'start',%s,%s,%s) ON CONFLICT (idempotency_key) DO NOTHING",
            (r["workflow"], at, f"dispatch:{r['sub']}:{r['eid']}", Jsonb({"event_ids": [r["eid"]], "coalesce_key": ckey})))
        return "enqueued"
