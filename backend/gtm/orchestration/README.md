# gtm.orchestration

Small in-house durable runner (AD-03): outbox events, gap-safe dispatcher, graph builder, Postgres-backed jobs,
per-account lease with fencing, scheduler. Tests: `cd backend && python -m pytest tests/orchestration tests/llm -q`.

## Pieces
| Module | Role |
|---|---|
| `events.emit(conn, clock, env) -> int \| None` | Insert `domain_event` (None on duplicate `dedupe_key`), create `dispatch` rows for enabled matching subscriptions, wake runs waiting on that type. Caller commits. |
| `events.subscribe(conn, event_type, workflow, filter=None)` | Normally done by `Runner.register` from `trigger()`. |
| `Dispatcher` | Claims `pending` dispatch rows `FOR UPDATE SKIP LOCKED`; lifecycle hook; stale-event rule (`ignored_stale`); coalescing; one `job` per dispatch (key `dispatch:<sub>:<event>`); dead-letter after 3 failed attempts -> `job.dead` event. |
| `scheduler.add_schedule(conn, clock, kind, target, cadence_seconds, first_at=None)` / `tick` | Due `ops.schedule` rows -> events. `kind='heartbeat'` -> `heartbeat.due` (a kind containing '.' is used verbatim); `target='account:12'` sets `account_id`. |
| `leases.acquire/check/release` | `ops.account_lease` with fencing token; stale writers get `LeaseLost` (a NOT_READY error: the run re-queues). |
| `Runner` | Executes runs. One job per run; every node attempt is an `ops.run_step`. |

## Builder API (exact)
```python
from gtm.orchestration import Graph, Retry, Runner, Services, emit

g = Graph(name, version="1", *, cost_cap=None, lease=False, coalesce_seconds=0, coalesce_key=None, coalesce_delay=False, park_deadline=None)
g.trigger(name, events: str | list[str], filter: dict | None = None)       # exactly one per graph; subscribes the workflow
g.code(name, fn, after=None, *, when=None, join=False, retry=None, timeout=None, on_error="fail")     # fn(ctx) -> dict
g.tool(name, fn, after=None, *, adapter=None, **same)          # fn(ctx) -> dict; adapter in {crm.write, outreach.import, outreach.send} is rejected
g.llm(name, task, input, after=None, *, prompt_version="v1", **same)       # task: str | fn(ctx)->str; input: fn(ctx)->dict
g.agent(name, fn, after=None, *, max_steps=8, **same)         # fn(ctx) loop; call ctx.tick() per iteration
g.conditional(name, fn, after=None)                           # fn(ctx) -> label; output {"branch": label}
g.map(name, items, fn, after=None, *, key=None, concurrency=3, **same)     # items(ctx)->list; fn(ctx, item)->dict
g.reduce(name, over, fn, after=None)                          # fn(ctx, results: dict[key -> {"ok", "output"|"error"}])
g.wait(name, until=None, after=None, *, event=None, match=None, result=None, poll=(5, 2, 60), deadline=1800)
g.approval(name, proposal_id, after=None, *, deadline=None)   # proposal_id(ctx) -> int | None
```
- `after` is a node name or list; default is the trigger. Dependencies must be declared first (graphs are DAGs by construction).
- Node output is a JSON-serialisable `dict`, stored at `ctx.state[name]` (persisted in `agent_run.state`). Downstream nodes read `ctx.state["prev"]`.
- **Branching:** `g.conditional("c", fn)`; then `g.code("yes", f, after="c", when=("c", "yes"))`. Nodes whose `when` does not match are `skipped`; a skipped dependency skips the node unless `join=True` (runs if at least one dependency ran).
- **Map/reduce:** per-item `run_step` rows (`item_key`), per-item retries and idempotency. A failed item does not fail the node: `state[map] = {"items": {key: {"ok": True, "output": {...}} | {"ok": False, "error", "error_class"}}, "ok": n, "failed": m}`. `reduce` receives that dict in item order and decides how to proceed with partial results.
- **Wait:** satisfied by a matching event (type in `event`, optional `match(ctx, env) -> bool`, optional `result(ctx, env) -> dict`) OR `until(ctx)` truthy (polled with exponential backoff `poll=(initial, factor, cap)`; `poll=None` evaluates only on events and at the deadline). Output `{"via": "event"|"poll", ...}`. At `deadline` (seconds) the run is **parked**: status `needs_attention`, audit `run.parked`; `runner.resume(run_id)` is the one-click retry.
- **Approval:** a wait on `proposal.approved/rejected/expired/superseded` for `proposal_id(ctx)` (also checks `ops.proposal.status`). Output `{"decision": "approved"|"approved_edited"|"rejected"|"expired"|"superseded", "proposal_id"}`; default deadline `settings.approval_ttl_hours`. It never creates proposals.
- **Errors by class:** `RetryableError` -> retry with exponential backoff and deterministic jitter (defaults: tool/map 5 attempts 2s..60s, llm 2, agent 2, code 1; override with `retry=Retry(max_attempts, base, cap)`; `retry_after` is honoured). `PermanentError`/`PolicyDenied`/any other exception -> step `failed`, run `needs_attention` (or `on_error="continue"`: output `{"error", "error_class"}`). `NotReady` -> step `parked`, run `waiting`, re-queued with backoff until `park_deadline` (default `settings.sync_wait_deadline_minutes`), then `needs_attention`.
- `timeout=` is simulated seconds measured on the injected clock; exceeding it is a retryable timeout.
- **Cost cap:** `Graph(cost_cap=usd)`; `ctx.charge(...)`/`ctx.llm` add to `agent_run.cost`; above the cap the run ends `budget_exceeded`.
- **Idempotency:** each step result is stored in `ops.idempotency_record` under `<workflow>@<version>:<run>:<node>:<item>`; a replayed step returns the stored output without calling the node. Side effects inside a node: `ctx.once("suffix", fn)` (committed immediately) and pass `ctx.idem_key` to adapters.
- **Lease:** `Graph(lease=True)` takes the account lease (fencing token in `ctx.fencing_token`) for runs with an `account_id`; it is checked before every commit and released when the run parks or ends. Held by another run: the job retries in 10 s.
- **Coalescing:** `Graph(coalesce_seconds=60, coalesce_key=lambda env: f"account:{env.account_id}", coalesce_delay=False)` folds further events for the same key into the still-queued job (with `coalesce_delay=True` the start is also delayed by the window) (`ctx.events`; `ctx.trigger` is the first).

### Ctx
`ctx.conn, ctx.clock, ctx.run_id, ctx.account_id, ctx.trigger (EventEnvelope), ctx.events, ctx.state, ctx.services, ctx.settings, ctx.node, ctx.item, ctx.idem_key, ctx.fencing_token`;
`ctx.emit(type, payload=None, *, entity_ref=None, account_id=None, dedupe_key=None, source=None, source_version=None) -> int | None` (deterministic default dedupe key, so retries do not duplicate);
`ctx.audit(event_type, data=None, *, entity_ref=None, proposal_id=None)`; `ctx.llm(task, input, *, prompt_version="v1") -> dict` (put untrusted text under `input["untrusted"]`);
`ctx.call(tool_name, fn, *args, principal=..., **kw)` (traced in `ops.tool_call`, also on denial); `ctx.once(suffix, fn)`; `ctx.charge(usd, tokens_in, tokens_out, model_id)`; `ctx.assert_lease()`; `ctx.tick()`.

### Services
`Services(settings, clock, llm=None, crm=None, outreach=None, providers={}, web=None, token_secret=b"", extras={})` (duck-typed; adapters belong to the adapter stream).

### Runner
```python
r = Runner(conn, clock, services, *, worker_id="worker-1", lease_seconds=300, max_job_attempts=5, lifecycle=None)
r.register(graph)
r.start(workflow, env)                     # manual start (also stores the event)
r.run_until_idle(max_steps=1000, advance_clock=True, horizon=None) -> {"jobs","dispatched","scheduled","clock_advances","idle","now","runs"}
r.resume(run_id)                           # needs_attention -> running
```
`run_until_idle` is discrete-event: with a `SimClock` it jumps to the next queued job or lease expiry. Schedules advance the clock only when `horizon` is given (so recurring heartbeats do not loop forever). Pass `advance_clock=False` to leave waits pending (e.g. while a human approves). A crashed runner leaves its job leased; any runner resumes it after `lease_seconds`, skipping completed nodes.

## Example
```python
def fetch(ctx):  return {"urls": ["a", "b", "c"]}
def look(ctx, url):
    if url == "c": raise PermanentError("404")
    return {"title": url.upper()}
def merge(ctx, results): return {"titles": [v["output"]["title"] for v in results.values() if v["ok"]], "gaps": [k for k, v in results.items() if not v["ok"]]}

g = Graph("research", version="1", cost_cap=0.50)
g.trigger("start", "lead.received")
g.tool("fetch", fetch)
g.map("lookup", items=lambda ctx: ctx.state["fetch"]["urls"], fn=look, after="fetch", concurrency=2)
g.reduce("merge", over="lookup", fn=merge)
g.llm("score", "qualify", lambda ctx: {"titles": ctx.state["merge"]["titles"], "untrusted": {"text": ctx.trigger.payload.get("message", "")}}, after="merge")
g.conditional("bar", lambda ctx: "high" if ctx.state["score"]["score"] >= 60 else "low", after="score")
g.wait("synced", until=lambda ctx: ctx.services.outreach.visible(ctx.state["merge"]), event="sync.contact_visible",
       after="bar", when=("bar", "high"), deadline=1800)
g.code("done", lambda ctx: {"ok": True}, after="synced", when=("bar", "high"))

runner = Runner(conn, clock, Services(settings, clock, llm=build_llm(settings, clock, conn=conn)))
runner.register(g)
emit(conn, clock, EventEnvelope(type="lead.received", occurred_at=clock.now(), source="webhook", dedupe_key="lead:1", payload={}))
conn.commit(); runner.run_until_idle()
```
