"""execute_proposal: runs after proposal.approved. Waiting is owned here (Wait node polling the gateway); every poll re-runs
the gateway's full ordered check chain. The gateway alone decides READY / NOT_READY / BLOCKED / EXECUTED."""
from __future__ import annotations
from gtm.config import get_settings
from gtm.contracts.gateway import GatewayStatus
from gtm.data import MatchConfirmationExecutor, MergeExecutor
from gtm.gateway import gateway_for
from gtm.orchestration import Graph


def proposal_id_of(ctx) -> int:
    ref = ctx.trigger.entity_ref or ""
    if not ref.startswith("proposal:"):
        raise ValueError(f"trigger has no proposal ref: {ref!r}")
    return int(ref.split(":", 1)[1])


def _attempt(ctx):
    pid = proposal_id_of(ctx)
    gw = gateway_for(ctx.conn, ctx.clock, ctx.services)
    gw.register_executor("match_confirmation", MatchConfirmationExecutor())
    gw.register_executor("merge", MergeExecutor())
    res = ctx.call("gateway.attempt", gw.attempt, pid)
    if res.status == GatewayStatus.NOT_READY:
        return None                       # keep waiting (polled with backoff, or woken by an event)
    return {"status": res.status.value, "reason": res.reason, "block_class": res.block_class, "external_ref": res.external_ref,
            "execution_id": res.execution_id, "proposal_id": pid}


def _record(ctx):
    r = dict(ctx.state["gateway"])
    ctx.audit("execute_proposal.finished", {k: r.get(k) for k in ("status", "reason", "block_class", "proposal_id")}, entity_ref=f"proposal:{r['proposal_id']}")
    if r["status"] == "BLOCKED":
        r["outcome"] = "returned_to_review" if r["block_class"] == "soft" else "terminal_hard_block"
    else:
        r["outcome"] = "executed"
    return {k: r.get(k) for k in ("status", "reason", "block_class", "proposal_id", "external_ref", "outcome")}


def build_graph() -> Graph:
    s = get_settings()
    g = Graph("execute_proposal", "1")
    g.trigger("on_proposal_approved", "proposal.approved")
    g.wait("gateway", _attempt, event=["sync.contact_visible", "execution.completed"], match=lambda ctx, env: False,
           poll=(5, 2, 60), deadline=s.sync_wait_deadline_minutes * 60 + 300)
    g.code("record", _record, after="gateway")
    return g
