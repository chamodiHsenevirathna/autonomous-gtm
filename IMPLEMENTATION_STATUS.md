# Implementation status

_Last updated: 2026-11-06 (lead)_

## Milestones
| M | Name | Status | Notes |
|---|---|---|---|
| M0 | Foundation | **Done** | Skeleton, schema, config/clock/db, audit hash chain, contracts, seed, test infra |
| M1 | Simulated world | **Done** | Deterministic world (40 companies, 15 enquiries), provider/CRM/outreach/web sims, fault injection, token-enforcing adapters |
| M2 | Orchestration core | **Done** | Events, gap-safe dispatcher, graph builder, durable runner (867 lines; AD-03 exit criterion not triggered), leases, scheduler, LLM wrapper (replay/mock/guarded live) |
| M3 | Data layer | **Done** | Waterfall (sequential/parallel), survivorship, entity resolution (3 bands), soft merge + undo |
| M4 | Approval, gateway, router | **Done** | Single-use hash-bound approvals, ordered check chain, execution tokens, suppression, reply router |
| M5 | Intelligence | **Done** | Mock model, intake, research, qualification, account agent (persistent state), execute, ingest, match-resume |
| M6 | Pipeline monitor, feedback capture, MCP tool layer | **Done** | Stall rules + digest numbers from SQL; lost-deal reviews + verbatim-quote extraction; ToolSession registry with run-bound scope |
| API | Dashboard API + CLI | **Done** | 24 endpoints per frontend/API_SPEC.md |
| FE | Frontend | **Done** | 12 routes, mock + http modes, Playwright e2e incl. real backend |
| EV | Evaluation | **Done** | 10 invariants, 28 scenarios pass on the real system, baseline frozen; 7 scenarios pending |
| M7 | Integration, docs, demo | **Done** (final verification 2026-11-06: 338 backend tests, 28/28 scenarios, 13 unit + 9 browser tests; superseded: 416 backend tests as of 2026-11-07, see the latest update at the end of this file) | README, docs/case-study.md, harness, runtime |

## Blocked
None. See 'Known gaps' below.

## Deferred (per directive section 8)
Full experimentation engine, automated feedback pattern discovery, learning loop, real HubSpot adapter, advanced drift monitoring, Agent SDK experiments, advanced customer engagement and outbound.

## Environment notes
- Postgres via Docker (Colima) started with scripts/db_up.sh (Compose plugin absent; docker-compose.yml kept for reference).

## Known gaps and remaining defects
- Scenarios not yet runnable: S08, S12, S20, S21, S23, S26, S53, S56 (blocked on world/harness hooks; reasons in `backend/scenarios/pending/`). S27, S29 not written.
- Requirements-to-scenarios coverage is partial (41/151 requirement ids have a runnable scenario; the set targets safety and inbound paths).
- Model behaviour is a deterministic mock; the guarded live path has never been run. No claim about real model quality.
- The mock qualifier scores several genuine simulated enquiries as low fit (sparse simulated providers), and labels an injection-spam enquiry 'unclear' (held correctly).
- UI acts as one fixed reviewer, no authentication; demo is single-process; Chromium-only browser verification.
- One test-suite hang (>10 min, an open transaction on a test database) was observed once and did not reproduce in 9 later full or partial runs; cause unidentified.
- Backend/UI open items (minor): `old_payload` is not returned after an edit (UI keeps it per session); reviewer comments are not turned into Feedback items; `last_decision.confidence` is 0.0; evaluation run via the API takes ~30 s; Alerts page has no real data in the default demo.


## Model-evaluation preparation (2026-11-06)
(Historical entry; the active dataset is now v4, 68 cases.) Plan, dataset (56 cases), scorer, mock baseline and live-test procedure are in `model_eval/` (start at `model_eval/README.md`). No live call has been made; live mode remains disabled. Blocking defects in the live client (F1, F2) must be fixed before any live test; awaiting owner approval of the plan.

**Update (zero-cost phase):** live-client defects F1-F6 fixed offline and tested with a mock transport; dataset v2, label-review report, test doubles, validation matrix added; paid live test withdrawn; live mode locked. Real commercial model performance untested.

**Update 2026-11-07:** `apply_hard_constraints` implemented (low-confidence employee count never holds a lead; evidence requested). Dataset v3 (65 cases; superseded by v4, 68 cases). Blind label review recorded in `model_eval/09_independent_label_review.md`. Regression: 28/28 scenarios, 392 tests passing. Local-model rehearsal deferred. Zero-cost restrictions permanent.

**Update 2026-11-07:** region confidence rule, configurable threshold, `triage_gate` (unclear and spam held) implemented; dataset v4 (68 cases); 3 of 9 split decisions resolved, 5 contested. Regression: 28/28 scenarios, 416 tests passing. Gaps listed in `model_eval/10_business_policy.md` section 2 are not built.

