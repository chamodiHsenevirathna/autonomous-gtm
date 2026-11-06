"""Outbox: write a domain event and its dispatch rows in the caller's transaction."""
from __future__ import annotations
import json
from psycopg import Connection
from psycopg.types.json import Jsonb
from ..clock import Clock
from ..contracts.events import EventEnvelope


def subscribe(conn: Connection, event_type: str, workflow: str, filter: dict | None = None) -> int:
    return conn.execute(
        "INSERT INTO ops.subscription(event_type, workflow, filter) VALUES (%s,%s,%s) "
        "ON CONFLICT (event_type, workflow) DO UPDATE SET filter=EXCLUDED.filter, enabled=true RETURNING id",
        (event_type, workflow, Jsonb(filter) if filter else None)).fetchone()["id"]


def _subset(want, have) -> bool:
    if isinstance(want, dict):
        return isinstance(have, dict) and all(k in have and _subset(v, have[k]) for k, v in want.items())
    return want == have


def matches(flt: dict | None, env: EventEnvelope) -> bool:
    """Filter keys: any EventEnvelope field; 'payload' is matched as a recursive subset."""
    return not flt or _subset(flt, env.model_dump(mode="json"))


def row_to_env(r: dict) -> EventEnvelope:
    return EventEnvelope(type=r["type"], account_id=r["account_id"], entity_ref=r["entity_ref"], payload=r["payload"],
                         occurred_at=r["occurred_at"], source=r["source"], source_version=r["source_version"],
                         schema_version=r["schema_version"], dedupe_key=r["dedupe_key"], ordering_key=r["ordering_key"])


def emit(conn: Connection, clock: Clock, env: EventEnvelope) -> int | None:
    """Insert the event (None if dedupe_key exists), create dispatch rows for matching subscriptions and nudge runs
    that are waiting on this event type. All in the caller's transaction (caller commits)."""
    now = clock.now()
    row = conn.execute(
        "INSERT INTO ops.domain_event(type, account_id, entity_ref, payload, occurred_at, recorded_at, source, source_version, "
        "schema_version, dedupe_key, ordering_key) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT (dedupe_key) DO NOTHING RETURNING id",
        (env.type, env.account_id, env.entity_ref, Jsonb(env.payload), env.occurred_at, now, env.source, env.source_version,
         env.schema_version, env.dedupe_key, env.ordering_key or env.entity_ref)).fetchone()
    if row is None:
        return None
    eid = row["id"]
    for s in conn.execute("SELECT id, filter FROM ops.subscription WHERE event_type=%s AND enabled ORDER BY id", (env.type,)).fetchall():
        if matches(s["filter"], env):
            conn.execute("INSERT INTO ops.dispatch(event_id, subscription_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (eid, s["id"]))
    conn.execute(
        "UPDATE ops.job j SET available_at = LEAST(j.available_at, %s) FROM ops.agent_run r "
        "WHERE j.run_id=r.id AND j.status='queued' AND r.status='waiting' AND r.state->'_event_waits' @> %s::jsonb",
        (now, json.dumps([env.type])))
    return eid


def load_event(conn: Connection, event_id: int) -> EventEnvelope:
    return row_to_env(conn.execute("SELECT * FROM ops.domain_event WHERE id=%s", (event_id,)).fetchone())
