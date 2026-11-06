# gtm.eval: evaluation and QA

Machinery that checks the system against ground truth and safety invariants. It is written against the contracts
(`gtm.contracts.harness.SystemHarness`, `scenario`, `world`, `provenance`), so it runs with any harness; the tests use a fake.

| Module | What it does |
|---|---|
| `invariants.py` | Ten SQL safety properties over the database; `check_all(conn)`. |
| `metrics.py` | Pure metric functions over DB rows vs a `World`; `compute_all(conn, world)`. |
| `runner.py` | Loads `scenarios/*.yaml`, plays the script through a harness, judges expectations, baselines, reports, CLI. |
| `replay.py` | Records `LLMClient` responses as fixtures; checks replay equals mock. |

## Run

```bash
cd backend && source ../.venv/bin/activate
export GTM_TEST_DATABASE_URL=postgresql://gtm:gtm_local_dev_only@127.0.0.1:5433/gtm_test_d
python -m pytest tests/eval -q                                   # tests of the machinery (fake harness, hand-built rows)
python -m gtm.eval.runner --validate                             # static lint of scenarios/*.yaml, no database
python -m gtm.eval.runner --list
python -m gtm.eval.runner --scenarios S01,S05                    # needs gtm.harness:Harness (lead)
python -m gtm.eval.runner --update-baseline                      # write fixtures/baselines/baseline.json from this run
```
Options: `--harness module:callable` (called as `f(database_url=...)`, falls back to `f()`), `--database-url` (default: the test DB;
non-test database names are refused because `harness.reset()` empties the database), `--out-dir` (default `./eval_reports`:
`report.json`, `report.md`), `--baseline-dir`, `--no-db-write`.
Exit code: 0 ok; 1 any regression or any new failure (a failure the baseline does not list as `"passed": false`); 2 usage or setup error.
Results are written to `ops.eval_run` / `ops.eval_result` at the end of the suite (the harness truncates tables on every reset).

## Scenario script (events)

Events run sorted by `at_offset_s` (the clock advances by the difference first). The runner calls `run_until_idle(advance_clock=False)` after
`enquiry`, `reply`, `advance_clock` and `human_decision`, unless `params.run: false`; set `params.idle_advance: true` where the scenario needs
time to jump to the next job (sync waits, retries).

| kind | params |
|---|---|
| `enquiry` | `ref` = world id, or `select` = symbolic selector (see scenarios/README.md); `select: all` delivers every world enquiry (`kinds: [...]` filters); `nth` |
| `reply` | `select` = `reply:<kind>[@<enquiry id>]` or a reply id |
| `advance_clock` | `seconds`, `idle_advance` |
| `inject_fault` / `clear_faults` | fields of `FaultSpec` (`sim`, `kind`, `scope`, `count`, `params`) |
| `human_decision` | `ref` = proposal selector; `decision` (approve, approve_with_edits, reject), `by`, `edit` (shallow patch of the payload, implies approve_with_edits), `edited_payload`, `reason_code`, `by_proposer` (approve as the proposing principal), `expect_denied` (a refusal, as `PolicyDenied` or `ok: false`, is recorded in `last_decision` instead of failing the scenario), `all` (every match), `drain` (approve matches, run, repeat until none) |
| `gateway_attempt` | `ref`; `bypass` in no_token, forged_token, wrong_hash, replay, direct_adapter. `PolicyDenied` becomes status `DENIED` |
| `tamper` | `what`: audit_row, proposal_payload, recipient (test-only) |
| `custom` | `name: run_until_idle`, or `name: check` with `kind`, `check_name`, `spec` (an expectation evaluated at that moment) |

Proposal selector: an id, or comma clauses `type:message`, `gate:G3|G4`, `status:pending|blocked`, `nth:-1`; shorthands `first_pending`,
`last_pending`, `last`. `human_decision` defaults to `status:pending`.

## Expectation DSL

`Expectation(kind, name, spec)`. Comparison keys usable in `spec`: `eq ne gt gte lt lte min max in not_in is_null not_null approx(+tol)`; all
present keys must hold. Context values for SQL are named parameters: `%(lead_id)s`, `%(lead_enq_001)s`, `%(proposal_id)s`, `%(now)s`
(escape a literal percent as `%%`). The context also holds `last_gateway`, `gateway` (list), `last_decision`, readable with `ctx`.

| kind | `name` | `spec` |
|---|---|---|
| `invariant` | an invariant name or `all` | `expect: hold` (default) or `violated` |
| `state` | free text | exactly one of `sql` (first column of first row), `ctx` (dotted path), `snapshot` (dotted path into `harness.snapshot()`), plus comparison keys |
| `metric` | a metric name (below) | comparison keys on the value; `min_denominator` (default 1); `allow_none` (a metric with no data fails unless true) |
| `event` | free text | `type`, `payload` (jsonb contains), `source`, comparison keys on the count (default `gte 1`) |
| `audit` | free text | `event_type`, `actor_type`, `actor_id`, `data` (jsonb contains), `proposal` (selector), count comparison; or `verify_chain: true/false` |
| `no_effect` | free text | any of `adapter` (no successful execution), `proposal`, `snapshot_key` (falsy), `sql` (zero) |

Every scenario also gets all invariants as an implicit check, except those named by an `invariant` expectation (so a scenario can declare an
expected violation, e.g. S48 audit tamper). Errors in the script itself (unresolved selector, bad spec) fail the scenario with kind `error`.

## Invariants (`invariants.py`)

| Check | Property |
|---|---|
| `approval_required` | every successful execution has an approval for that proposal, an approve decision, consumed, unexpired at execution, hash equal to the executed hash (and to the hash of the approved payload) |
| `no_send_after_suppression` | no send after an active contact/address/domain/account suppression created before it |
| `audit_chain` | `gtm.audit.verify_chain` |
| `no_duplicate_side_effects` | one successful execution per idempotency key and per (proposal, adapter) |
| `human_fields_traced` | each stage change traces to an executed approved `field_change` proposal or a human audit event (creation rows exempt) |
| `tool_calls_in_profile` | no permitted tool call outside the agent's MCP profile (`PROFILES`, from docs/mcp-integrations.md) or of an absent tool |
| `no_exec_while_hard_blocked` | no execution of a proposal blocked(hard), or after an audited hard block |
| `distinct_approver` | approver differs from proposer on gates with `requires_distinct_approver` (Director exempt per human-oversight 9.3) |
| `pending_exit_audited` | every proposal that left `pending` has an audit event other than its creation event |
| `recipient_matches_approval` | the recorded recipient of a sent message equals the approved recipient (unrecorded recipient counts as a violation) |

## Metrics (`metrics.py`)

Each returns `MetricResult(name, value, denominator, evidence_basis, data_origins, details)`; `value` is `None` when the denominator is 0.
Names: `er_precision er_recall er_f1 er_wrong_merge_rate`, `provider_accuracy.<provider>[.<field>]`, `provider_coverage.<provider>`,
`resolved_field_accuracy`, `calibration_ece` (bins in details), `qualification_accuracy/precision/recall/false_negatives`,
`triage_accuracy` (confusion matrix in details), `triage_injection_accuracy`, `hold_precision`, `real_leads_held`,
`tool_call_correctness`, `tool_calls_denied`, `tool_call_recall`, `cost_total`, `cost_per_run`, `run_latency_p50_s/p95_s`,
`step_latency_p95_s`, `run_failure_rate`. Ground-truth joins: account to company by domain (aliases included), lead to enquiry by
`raw_payload.enquiry_id` (else e-mail), `employee_count` correct within +-10%.

## Provenance and evidence basis

Every scenario and metric carries `data_origins` (GT, SIM, SCR, MOD, HUM-sim, HUM-real, PLT) and an `evidence_basis`:
- `measured_on_simulation`: model or simulator output compared to generated ground truth. Supports claims about the simulated world only.
- `machinery_check`: the right answer was planted or scripted (PLT/SCR), or the check is about control flow. Shows the machinery works; it is
  not an accuracy or effect-size result and is never reported as one. Cost and latency are machinery checks (simulated units, simulated time).
- `modelled_impact`: computed from stated assumptions. Not produced by this package yet.
A test enforces that scenarios using planted effects (PLT) are machinery checks.

## Baselines

`fixtures/baselines/*.json`: `{"tolerance": 0.02, "scenarios": {"S01": {"passed": true, "metrics": {"qualification_recall": 0.9}}}}`. A metric entry
may be `{"value": .., "direction": "higher|lower", "tolerance": ..}`; direction is inferred from the name (`rate`, `cost`, `latency`, `denied`,
`wrong_merge`, `false_negatives`, `ece` are lower-is-better). Regression = a passing scenario now fails, or a metric worsens beyond tolerance or
stops being measurable. `--update-baseline` stores metrics with denominator >= 5 only.

## Recorded responses (`replay.py`)

`record(client, requests, root=None, recorded_with=None)` runs requests through any `LLMClient` and writes
`fixtures/recorded/<task>/<input_hash>.json` with keys `input_hash, task, prompt_version, input, output, model_id, mode, recorded_with`
(plus optional `tokens_in`, `tokens_out`). `input_hash` is taken from the client's own response. `verify_replay_equals_mock(mock, replay,
requests)` returns a `ReplayReport(ok, n, mismatches)` (`.raise_if_failed()`); model ids compare without the `replay:` prefix. Loading
tolerates files that lack `mode` / `recorded_with` (the current `gtm.llm` recorder omits them).

## Honesty statement

Everything here runs on a synthetic world with simulated providers, a simulated CRM and outreach tool, scripted prospect replies, and a mock or
recorded model. Reviewer decisions are scripted unless labelled HUM-real. Passing scenarios show that the system behaves as designed and that
safety invariants hold on the simulated world. They say nothing about real model quality, real customers, conversion, revenue or time saved, and no
report may claim otherwise. `runner.PROVENANCE_STATEMENT` is printed at the top of every generated report.

## Limitations

Qualification and triage labels come from the world generator, so accuracy partly measures agreement with the generator's rules. Entity-resolution
metrics work at account level only. Scenario expectations that depend on system conventions (audit event names, snapshot keys) are listed in
`scenarios/README.md` and must be reconciled with the real harness. Seven scenarios sit in `scenarios/pending/` until world/harness gaps close; S27-S29, S31-S44, S51, S54, S55 are not written.

## Running the full suite against the real system

```bash
cd backend && source ../.venv/bin/activate
export GTM_TEST_DATABASE_URL=postgresql://gtm:gtm_local_dev_only@127.0.0.1:5433/gtm_test_d
python -m gtm.eval.runner --validate                       # lint scenarios, no DB
python -m gtm.eval.runner --out-dir eval_reports           # all runnable scenarios, harness gtm.harness:Harness
python -m gtm.eval.runner --scenarios S01,S25 --no-db-write  # subset, no ops.eval_* rows
python -m gtm.eval.coverage [--strict]                     # requirements vs scenarios
```
- The harness resets (truncates) the test database before every scenario; never point `--database-url` at a dev database.
- Expected runtime: tens of seconds to a few minutes for 29 scenarios in mock mode (SimClock, in-process simulators, no network); this is an
  estimate until the full system exists. A scenario with `idle_advance` runs more orchestrator rounds and is slowest.
- Exit code 1 means a regression or a failure the baseline does not already list; read `eval_reports/report.md` first (failures, then regressions).
- **Freezing baselines:** (1) run once and fix real defects or wrong scenario expectations until the failures left are understood; (2) run
  `python -m gtm.eval.runner --update-baseline`, which writes `fixtures/baselines/baseline.json` (pass/fail per scenario, metrics with denominator >= 5);
  (3) review the diff by hand, set `"passed": false` for known-open failures rather than deleting them, and commit it with the change that
  caused it. Re-freeze only deliberately, never to hide a regression.
- Replay tier: run with `llm_mode: replay` scenarios after recording fixtures with `gtm.eval.replay.record`, and check `verify_replay_equals_mock`.
