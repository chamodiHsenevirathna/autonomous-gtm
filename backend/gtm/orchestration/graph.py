"""Workflow graph builder. Nodes are plain functions; edges are `after=`. See README.md for the exact API."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable

SIDE_EFFECTING = {"crm.write", "outreach.import", "outreach.send"}   # Tool nodes may not name these (execution boundary)
PROPOSAL_EVENTS = {"proposal.approved": "approved", "proposal.rejected": "rejected",
                   "proposal.expired": "expired", "proposal.superseded": "superseded"}
DECIDED = {"approved", "approved_edited", "rejected", "expired", "superseded"}


@dataclass(frozen=True)
class Retry:
    max_attempts: int = 1       # total attempts, including the first
    base: float = 2.0           # seconds; delay = min(cap, base * 2**(attempt-1)) with deterministic jitter
    cap: float = 60.0


DEFAULT_RETRY = {"tool": Retry(5, 2, 60), "map": Retry(5, 2, 60), "llm": Retry(2, 1, 4), "agent": Retry(2, 5, 60)}


@dataclass
class Node:
    name: str
    kind: str                   # trigger code tool llm agent conditional map reduce wait approval
    fn: Callable | None = None
    after: list[str] = field(default_factory=list)
    when: tuple[str, str] | None = None     # (conditional node, branch label)
    join: bool = False          # run if at least one dependency ran (skipped branches allowed)
    retry: Retry = Retry()
    timeout: float | None = None            # simulated seconds, measured on the injected clock
    on_error: str = "fail"      # 'fail' (run -> needs_attention) | 'continue' (output {"error": ...})
    opts: dict = field(default_factory=dict)


class Graph:
    def __init__(self, name: str, version: str = "1", *, cost_cap: float | None = None, lease: bool = False,
                 coalesce_seconds: float = 0, coalesce_key: Callable | None = None, coalesce_delay: bool = False, park_deadline: float | None = None):
        self.name, self.version, self.cost_cap, self.lease = name, version, cost_cap, lease
        self.coalesce_seconds, self.coalesce_key, self.coalesce_delay = coalesce_seconds, coalesce_key, coalesce_delay   # coalesce_key(env) -> str | None
        self.park_deadline = park_deadline       # seconds a node may stay NotReady (default settings.sync_wait_deadline_minutes)
        self.nodes: dict[str, Node] = {}
        self.triggers: list[tuple[list[str], dict | None]] = []

    # ---- internals
    def _add(self, name, kind, fn, after, **kw) -> "Graph":
        if name in self.nodes or name.startswith("_"):
            raise ValueError(f"bad or duplicate node name {name!r}")
        after = [after] if isinstance(after, str) else list(after if after is not None else self._roots())
        for a in after:
            if a not in self.nodes:
                raise ValueError(f"node {name!r}: unknown dependency {a!r} (declare dependencies first)")
        retry = kw.pop("retry", None) or DEFAULT_RETRY.get(kind, Retry())
        opts = kw.pop("opts", {})
        if kw.get("when") and kw["when"][0] not in after:
            after.append(kw["when"][0])
        self.nodes[name] = Node(name, kind, fn, after, retry=retry, opts=opts, **kw)
        return self

    def _roots(self) -> list[str]:
        return [n.name for n in self.nodes.values() if n.kind == "trigger"][:1]

    # ---- node kinds (all return self for chaining)
    def trigger(self, name: str, events: str | list[str], filter: dict | None = None) -> "Graph":
        if any(n.kind == "trigger" for n in self.nodes.values()):
            raise ValueError("one trigger node per graph")
        evs = [events] if isinstance(events, str) else list(events)
        self.triggers.append((evs, filter))
        return self._add(name, "trigger", None, [], opts={"events": evs})

    def code(self, name, fn, after=None, **kw):
        return self._add(name, "code", fn, after, **kw)

    def tool(self, name, fn, after=None, *, adapter: str | None = None, **kw):
        if adapter in SIDE_EFFECTING:
            raise ValueError(f"tool node {name!r} names side-effecting adapter {adapter!r}; use a proposal and the gateway")
        return self._add(name, "tool", fn, after, opts={"adapter": adapter}, **kw)

    def llm(self, name, task, input, after=None, *, prompt_version="v1", **kw):
        """task: str or fn(ctx)->str. input: fn(ctx)->dict (untrusted text under key 'untrusted'). Output = model output + '_llm'."""
        def fn(ctx):
            out = ctx.llm(task(ctx) if callable(task) else task, input(ctx), prompt_version=prompt_version)
            r = ctx.last_llm
            return {**out, "_llm": {"model_id": r.model_id, "mode": r.mode, "input_hash": r.input_hash}}
        return self._add(name, "llm", fn, after, **kw)

    def agent(self, name, fn, after=None, *, max_steps: int = 8, **kw):
        """fn(ctx) runs a bounded loop; call ctx.tick() each iteration (raises PermanentError past max_steps)."""
        return self._add(name, "agent", fn, after, opts={"max_steps": max_steps}, **kw)

    def conditional(self, name, fn, after=None, **kw):
        """fn(ctx) -> label (str). Downstream nodes declare when=(name, label). Output: {"branch": label}."""
        def run(ctx):
            return {"branch": str(fn(ctx))}
        return self._add(name, "conditional", run, after, **kw)

    def map(self, name, items, fn, after=None, *, key=None, concurrency: int = 3, **kw):
        """items(ctx)->list; fn(ctx, item)->dict per item (own run_step, retries and idempotency). Output:
        {"items": {key: {"ok": bool, "output"|"error"}}, "ok": n, "failed": m}. A failed item does not fail the node."""
        return self._add(name, "map", fn, after, opts={"items": items, "key": key, "concurrency": max(1, concurrency)}, **kw)

    def reduce(self, name, over, fn, after=None, **kw):
        """Deterministic fan-in: fn(ctx, results) where results = state[over]['items']."""
        after = [over] + [a for a in ([after] if isinstance(after, str) else (after or [])) if a != over]
        if self.nodes.get(over) is None or self.nodes[over].kind != "map":
            raise ValueError(f"reduce {name!r}: {over!r} is not a map node")
        return self._add(name, "reduce", lambda ctx: fn(ctx, ctx.state[over]["items"]), after, **kw)

    def wait(self, name, until=None, after=None, *, event: str | list[str] | None = None, match=None, result=None,
             poll: tuple[float, float, float] | None = (5, 2, 60), deadline: float = 1800, **kw):
        """Resume on `event` (optionally filtered by match(ctx, env)) and/or when until(ctx) is truthy (polled with
        exponential backoff poll=(initial, factor, cap); poll=None evaluates only on events/deadline). At the deadline the
        run is PARKED (status needs_attention), never failed."""
        evs = [event] if isinstance(event, str) else list(event or [])
        if until is None and not evs:
            raise ValueError("wait needs `until` or `event`")
        return self._add(name, "wait", None, after, opts={"until": until, "events": evs, "match": match, "result": result,
                                                          "poll": poll, "deadline": deadline}, **kw)

    def approval(self, name, proposal_id: Callable[[Any], int | None], after=None, *, deadline: float | None = None, **kw):
        """Wait on the decision for proposal_id(ctx). Output {"decision": approved|rejected|expired|superseded|approved_edited,
        "proposal_id"}. Does not create proposals (the execution stream does). deadline default: settings.approval_ttl_hours."""
        def until(ctx):
            pid = proposal_id(ctx)
            r = ctx.conn.execute("SELECT status FROM ops.proposal WHERE id=%s", (pid,)).fetchone() if pid else None
            return {"decision": r["status"], "proposal_id": pid} if r and r["status"] in DECIDED else None
        g = self.wait(name, until, after, event=list(PROPOSAL_EVENTS), poll=None, deadline=deadline or -1,
                      match=lambda ctx, env: env.payload.get("proposal_id") == proposal_id(ctx),
                      result=lambda ctx, env: {"decision": PROPOSAL_EVENTS[env.type], "proposal_id": env.payload.get("proposal_id")}, **kw)
        g.nodes[name].kind = "approval"
        return g

    # ---- helpers
    def order(self) -> list[Node]:
        return list(self.nodes.values())    # declaration order is a valid topological order (deps must exist first)

    def validate(self) -> None:
        if not any(n.kind == "trigger" for n in self.nodes.values()):
            raise ValueError(f"graph {self.name!r} has no trigger node")
