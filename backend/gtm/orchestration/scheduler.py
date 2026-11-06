"""Single scheduling source: due rows in ops.schedule become domain events (e.g. heartbeat.due)."""
from __future__ import annotations
from datetime import datetime, timedelta
from psycopg import Connection
from ..clock import Clock
from ..contracts.events import EventEnvelope
from .events import emit


def add_schedule(conn: Connection, clock: Clock, kind: str, target: str, cadence_seconds: int | None,
                 first_at: datetime | None = None) -> int:
    return conn.execute(
        "INSERT INTO ops.schedule(kind, target, cadence_seconds, next_run_at) VALUES (%s,%s,%s,%s) "
        "ON CONFLICT (kind, target) DO UPDATE SET cadence_seconds=EXCLUDED.cadence_seconds, enabled=true RETURNING id",
        (kind, target, cadence_seconds, first_at or clock.now())).fetchone()["id"]


def tick(conn: Connection, clock: Clock) -> int:
    """Emit one event per due schedule and move next_run_at forward (missed beats are skipped, not replayed)."""
    now, n = clock.now(), 0
    for s in conn.execute("SELECT * FROM ops.schedule WHERE enabled AND next_run_at<=%s ORDER BY next_run_at, id "
                          "FOR UPDATE SKIP LOCKED", (now,)).fetchall():
        etype = s["kind"] if "." in s["kind"] else f"{s['kind']}.due"
        acct = int(s["target"].split(":", 1)[1]) if s["target"].startswith("account:") else None
        emit(conn, clock, EventEnvelope(type=etype, account_id=acct, entity_ref=s["target"], occurred_at=s["next_run_at"],
                                        source="scheduler", dedupe_key=f"sched:{s['kind']}:{s['target']}:{s['next_run_at'].isoformat()}",
                                        payload={"schedule_id": s["id"], "kind": s["kind"]}))
        if s["cadence_seconds"]:
            nxt, step = s["next_run_at"], timedelta(seconds=s["cadence_seconds"])
            while nxt <= now:
                nxt += step
            conn.execute("UPDATE ops.schedule SET next_run_at=%s WHERE id=%s", (nxt, s["id"]))
        else:
            conn.execute("UPDATE ops.schedule SET enabled=false WHERE id=%s", (s["id"],))
        n += 1
    conn.commit()
    return n
