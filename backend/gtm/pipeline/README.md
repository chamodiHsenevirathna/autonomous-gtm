# gtm.pipeline (U7 pipeline monitor)

Deterministic SQL/rules; no model calls.
- `scan_pipeline(conn, clock, principal="agent:pipeline-monitor", params=ScanParams())`: for each open opportunity computes last activity (opportunity, activity, account interactions), days in stage, and stall reasons. Stalled = no activity >= 14 days, stage dwell above threshold (30 days default), or close date passed; `no_next_step` and `single_threaded` are added to the reason when stalled. Writes only `is_stalled`, `stall_reason`, `days_in_stage` through `set_opportunity_system_fields` (checked against `ops.field_policy`). Emits `deal.flagged` once per new flag (dedupe key includes last-activity stamp) and creates a `task` proposal. Flags clear on the next scan after activity.
- Hygiene (missing close date/amount/next step, duplicate open opportunities per account) produce `task` proposals only, idempotent per week and skipped while one is outstanding.
- `weekly_digest(conn, clock, narrative_fn=None)`: all numbers from SQL; an optional narrative is dropped if `check_narrative` finds a number not in the digest.
- `build_graphs()` returns graph `pipeline_scan` (trigger `pipeline.scan`; schedule it with `add_schedule(conn, clock, "pipeline.scan", "global", 86400)`).

Tests: `cd backend && python -m pytest tests/pipeline -q`
