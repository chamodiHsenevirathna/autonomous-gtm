# gtm.agents

Workflows and the deterministic stand-in model. `build_graphs()` registers the mock model and returns five graphs: `inbound_intake`, `account_wake`, `execute_proposal`, `sim_ingest`, `match_resume`.
All model output here is **simulated** (`mode='mock'`, `model_id='mock-heuristic-v1'`); it says nothing about real model quality.

| Module | Contents |
|---|---|
| `mockmodel.py` | `register_all()` (idempotent): rule-based triage, qualify, research_brief, account_decide, draft_message, reply_intent. Injection-looking sentences are stripped before any rule runs and flagged. |
| `context.py` | `build_context_pack(conn, clock, account_id)` (priority order, token budget, `content_hash`), `change_detector(conn, clock, account_id, event_type=None)` (deterministic; no material change means no model call). |
| `intake.py` | `submit_enquiry(conn, clock, enquiry) -> lead_id` (inserts the lead, idempotent on `enq:<id>`, emits `lead.received`); graph `inbound_intake`. Held leads are never destroyed and create no proposals. A "possible" match creates a G1 proposal and holds the lead (`match_pending`). |
| `account.py` | graph `account_wake` (lease, coalescing), `lifecycle_filter(conn, env, workflow)` for `Runner(lifecycle=...)`. Applies actions only through `ToolSession(profile='account-agent')`. |
| `execute.py` | graph `execute_proposal` (trigger `proposal.approved`): Wait node polls `gateway.attempt`; NOT_READY keeps waiting, BLOCKED/EXECUTED end the run. |
| `resume.py` | graph `match_resume` (events `execution.completed`, `proposal.rejected`): when the G1 match proposal(s) of a lead held as `match_pending` are decided, re-submits `lead.received` with a `resume` payload (same = link to the existing record via the executed match, distinct = `record_match_rejection` and keep the new records). Never merges; idempotent per outcome. `execute_proposal` registers the match/merge executors. |
| `ingest.py` | `pull_and_route(conn, clock, services) -> {"routed","duplicates","cursor"}`; graph `sim_ingest` on event `sim.poll`. |

Wiring: `Runner(conn, clock, services, lifecycle=gtm.agents.account.lifecycle_filter)`; `for g in build_graphs(): runner.register(g)`;
`add_schedule(conn, clock, "sim.poll", "global", 60)` to poll the simulators; heartbeats are scheduled by each account wake (`heartbeat.due`, 7 days).
Tests: `cd backend && python -m pytest tests/agents -q` (golden thread in `test_golden_thread.py`).
