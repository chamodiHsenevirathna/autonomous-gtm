"""Pull events from the outreach/mail simulator and route them (idempotent; durable cursor in ops.idempotency_record)."""
from __future__ import annotations
from psycopg.types.json import Jsonb
from gtm.gateway import route_sim_event
from gtm.orchestration import Graph

CURSOR_KEY = "sim_ingest:cursor"


def _cursor(conn) -> int:
    r = conn.execute("SELECT result FROM ops.idempotency_record WHERE key=%s", (CURSOR_KEY,)).fetchone()
    return int(r["result"]["seq"]) if r else 0


def pull_and_route(conn, clock, services) -> dict:
    """Returns {"routed": newly routed events, "duplicates": already-seen events, "cursor": last seq}."""
    cur = _cursor(conn)
    outreach = services.outreach or services.extras["adapters"].outreach
    routed = dups = 0
    top = cur
    for e in sorted(outreach.events(cur), key=lambda e: e.seq):
        out = route_sim_event(conn, clock, e.model_dump(), llm=services.llm)
        if out.get("duplicate"):
            dups += 1
        else:
            routed += 1
        top = max(top, e.seq)
    conn.execute("INSERT INTO ops.idempotency_record(key,result,created_at) VALUES (%s,%s,%s) "
                 "ON CONFLICT (key) DO UPDATE SET result=EXCLUDED.result", (CURSOR_KEY, Jsonb({"seq": top}), clock.now()))
    conn.commit()
    return {"routed": routed, "duplicates": dups, "cursor": top}


def build_graph() -> Graph:
    g = Graph("sim_ingest", "1")
    g.trigger("on_sim_poll", "sim.poll")
    g.code("pull", lambda ctx: pull_and_route(ctx.conn, ctx.clock, ctx.services))
    return g
