# gtm.api: dashboard backend

`create_app(database_url=None, *, reset=True) -> FastAPI` serves the JSON shapes in `frontend/API_SPEC.md` (snake_case, simulated-clock timestamps,
newest-first lists). It holds ONE `gtm.runtime.Runtime` on the demo DB behind a lock (reset on start unless `reset=False`), mounts the simulators at
`/sim/...` (e.g. `/sim/control/state`), and allows CORS from the Vite dev origin (localhost/127.0.0.1:5173).

State-changing endpoints (decision, demo/*) run the system to quiet via `Harness.run_until_idle` (including `gtm.agents.ingest.pull_and_route`) and commit.

| Endpoint | Notes |
|---|---|
| GET health, config, overview, leads, accounts, accounts/{id}, opportunities, pipeline/alerts, runs, runs/{id}, audit?limit, audit/verify, events?limit, feedback | read-only mappings in `views.py`; account fields come from `gtm.data.survivorship.get_resolved`, `ai_*` fields have owner `agent` |
| GET proposals?status=, proposals/{id} | `execution.checks` always has the 13 steps of docs/execution-architecture.md 13.2; unreached/not applicable = `skipped`. Dependency-blocked pending proposals show `blocked` (or `superseded` if the dependency was rejected); a gateway soft block shows `blocked` with `block_kind: soft` and can be decided again |
| POST proposals/{id}/decision | 404 unknown, 422 missing `reason_code` (reject) / `edited_payload` (edit) / invalid edit / commercial block, 409 not pending or dependency not executed, 403 role / not human / own proposal. Runs the workflow; if no `execute_proposal` workflow handled it, the gateway is called directly |
| GET evals, POST evals/run | run uses `GTM_TEST_DATABASE_URL` only; 503 if it equals the demo DB or the suite is unavailable. A summary copy is stored in the demo DB (`ops.eval_run.summary`) |
| POST lost-deal-reviews | uses `gtm.feedback.save_lost_deal_review` if its signature matches, else writes `gtm.lost_deal_review` directly (reason code kept as `reason:<code>` in `secondary_reasons`); 422 when no opportunity |
| POST demo/enquiry, reply, advance, reset | accepts `S01-golden-enquiry`/`S01-golden-reply` or `enq_001`/`rpl_001`; repeated or impossible actions return `ok:false` with a message |

`schemas.py` holds strict pydantic models of every shape (used by the tests). Run: `python -m gtm.cli serve` (demo DB `gtm`, 127.0.0.1:8000),
`python -m gtm.cli reset-db`, `python -m gtm.cli eval [runner options]`.

Tests: `cd backend && GTM_TEST_DATABASE_URL=postgresql://gtm:gtm_local_dev_only@127.0.0.1:5433/gtm_test_a python -m pytest tests/api -q`
