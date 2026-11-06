"""Append-only audit log with a lightweight SHA-256 hash chain (NFR-AUD-03).
All streams write audit via append(); nobody updates or deletes rows (a DB trigger forbids it)."""
from __future__ import annotations
import hashlib, json
from typing import Any
from psycopg import Connection
from psycopg.types.json import Jsonb


def _dumps(o):
    return json.dumps(o, default=str)
from .clock import Clock, UTC

GENESIS = "0" * 64
_LOCK_KEY = 7_340_001  # advisory lock id serialising appends so the chain has no forks


def _digest(prev: str, at_iso: str, actor_type: str, actor_id: str, event_type: str, entity_ref: str | None,
            run_id: int | None, proposal_id: int | None, data: dict) -> str:
    doc = [prev, at_iso, actor_type, actor_id, event_type, entity_ref, run_id, proposal_id, data]
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False).encode()).hexdigest()


def append(conn: Connection, clock: Clock, *, actor_type: str, actor_id: str, event_type: str, entity_ref: str | None = None,
           run_id: int | None = None, proposal_id: int | None = None, data: dict[str, Any] | None = None) -> int:
    """Insert one audit row inside the caller's transaction. Returns seq."""
    data = data or {}
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_KEY,))
    row = conn.execute("SELECT hash FROM ops.audit_event ORDER BY seq DESC LIMIT 1").fetchone()
    prev = row["hash"] if row else GENESIS
    at = clock.now()
    h = _digest(prev, at.astimezone(UTC).isoformat(), actor_type, actor_id, event_type, entity_ref, run_id, proposal_id, data)
    r = conn.execute(
        "INSERT INTO ops.audit_event(at, actor_type, actor_id, event_type, entity_ref, run_id, proposal_id, data, prev_hash, hash) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING seq",
        (at, actor_type, actor_id, event_type, entity_ref, run_id, proposal_id, Jsonb(data, dumps=_dumps), prev, h)).fetchone()
    return r["seq"]


def verify_chain(conn: Connection) -> tuple[bool, int, int | None]:
    """Returns (ok, rows_checked, first_bad_seq). Detects edits to any field and removed/reordered rows."""
    prev = GENESIS
    n = 0
    for r in conn.execute("SELECT * FROM ops.audit_event ORDER BY seq"):
        n += 1
        expect = _digest(prev, r["at"].astimezone(UTC).isoformat(), r["actor_type"], r["actor_id"], r["event_type"], r["entity_ref"],
                         r["run_id"], r["proposal_id"], r["data"])
        if r["prev_hash"] != prev or r["hash"] != expect:
            return False, n, r["seq"]
        prev = r["hash"]
    return True, n, None
