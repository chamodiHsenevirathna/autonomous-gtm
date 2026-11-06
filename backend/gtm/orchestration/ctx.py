"""Services container and the per-node execution context."""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass, field
from typing import Any, Callable
from psycopg import Connection
from psycopg.types.json import Jsonb
from .. import audit
from ..clock import Clock
from ..config import Settings
from ..contracts.errors import PermanentError, PolicyDenied
from ..contracts.events import EventEnvelope
from ..contracts.llm import LLMRequest
from . import events as ev


@dataclass
class Services:
    settings: Settings
    clock: Clock
    llm: Any = None
    crm: Any = None
    outreach: Any = None
    providers: dict = field(default_factory=dict)
    web: Any = None
    token_secret: bytes = b""
    extras: dict = field(default_factory=dict)


class Ctx:
    def __init__(self, runner, run: dict, trigger: EventEnvelope, events: list[EventEnvelope], state: dict, node: str, item: str | None, token: int | None):
        self.runner, self.conn, self.clock, self.services = runner, runner.conn, runner.clock, runner.services
        self.settings, self.run_id, self.account_id, self.workflow = runner.services.settings, run["id"], run["account_id"], run["workflow"]
        self.trigger, self.events, self.state, self.node, self.item, self.fencing_token = trigger, events, state, node, item, token
        self.idem_key = f"{run['workflow']}@{run['workflow_version']}:{run['id']}:{node}:{item or ''}"
        self.last_llm = None
        self._emitted, self._steps, self._tools = 0, 0, []
        self._cost = {"usd": 0.0, "in": 0, "out": 0, "models": [], "apply": 0.0, "apply_in": 0, "apply_out": 0}

    # ---- events / audit
    def emit(self, type: str, payload: dict | None = None, *, entity_ref: str | None = None, account_id: int | None = None,
             dedupe_key: str | None = None, source: str | None = None, source_version: int | None = None) -> int | None:
        self._emitted += 1
        env = EventEnvelope(type=type, account_id=account_id if account_id is not None else self.account_id, entity_ref=entity_ref,
                            payload=payload or {}, occurred_at=self.clock.now(), source=source or f"workflow:{self.workflow}",
                            source_version=source_version, dedupe_key=dedupe_key or f"{self.idem_key}:{type}:{self._emitted}")
        return ev.emit(self.conn, self.clock, env)

    def audit(self, event_type: str, data: dict | None = None, *, entity_ref: str | None = None, proposal_id: int | None = None) -> int:
        return audit.append(self.conn, self.clock, actor_type="agent", actor_id=f"workflow:{self.workflow}", event_type=event_type,
                            entity_ref=entity_ref, run_id=self.run_id, proposal_id=proposal_id, data=data or {})

    # ---- tools, idempotency, lease
    def call(self, tool_name: str, fn: Callable, *args, principal: str = "system:orchestrator", **kw):
        """Invoke a tool/adapter function and trace it in ops.tool_call (also on failure or policy denial)."""
        t0 = self.clock.now()
        row = {"principal": principal, "tool_name": tool_name, "args": {"args": list(args), "kw": kw}, "permitted": True, "deny_reason": None, "at": t0}
        self._tools.append(row)
        try:
            return fn(*args, **kw)
        except PolicyDenied as e:
            row.update(permitted=False, deny_reason=str(e))
            raise
        finally:
            row["latency_ms"] = int((self.clock.now() - t0).total_seconds() * 1000)

    def once(self, suffix: str, fn: Callable[[], dict]) -> dict:
        """Run a side effect at most once per (run, node, item, suffix); the record is committed immediately so a
        crash after the effect cannot repeat it. fn must return a JSON-serialisable dict."""
        key = f"{self.idem_key}:{suffix}"
        r = self.conn.execute("SELECT result FROM ops.idempotency_record WHERE key=%s", (key,)).fetchone()
        if r:
            return r["result"]
        out = json.loads(json.dumps(fn()))
        self.conn.execute("INSERT INTO ops.idempotency_record(key, result, created_at) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                          (key, Jsonb(out), self.clock.now()))
        self.conn.commit()
        return out

    def assert_lease(self) -> None:
        self.runner.check_lease(self.run_id, self.account_id, self.fencing_token)

    def tick(self) -> None:
        self._steps += 1
        cap = self.runner.graphs[self.workflow].nodes[self.node].opts.get("max_steps", 8)
        if self._steps > cap:
            raise PermanentError(f"agent step cap {cap} reached")

    # ---- model + cost
    def charge(self, usd: float, tokens_in: int = 0, tokens_out: int = 0, model_id: str | None = None, *, apply: bool = True) -> None:
        c = self._cost
        c["usd"] += usd; c["in"] += tokens_in; c["out"] += tokens_out
        if apply:
            c["apply"] += usd; c["apply_in"] += tokens_in; c["apply_out"] += tokens_out
        if model_id and model_id not in c["models"]:
            c["models"].append(model_id)

    def llm(self, task, input: dict, *, prompt_version: str = "v1", max_cost_usd: float = 0.0) -> dict:
        llm = self.services.llm
        if llm is None:
            raise PermanentError("no LLM client in Services")
        r = llm.complete(LLMRequest(task=task, prompt_version=prompt_version, input=input, max_cost_usd=max_cost_usd), run_id=self.run_id)
        self.last_llm = r
        self.charge(r.cost_usd, r.tokens_in, r.tokens_out, r.model_id, apply=getattr(llm, "conn", None) is None)
        return r.output
