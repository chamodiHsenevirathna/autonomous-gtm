# Decisions log (implementation)

Architecture decisions AD-01..AD-15 from docs/ are preserved. Entries below are implementation-level decisions and deviations.

| ID | Date | Decision | Rationale |
|---|---|---|---|
| I-01 | 2026-11-06 | No git initialisation, no nested repo, no commits. Parallel work isolated by directory ownership + conformance tests | Directive section 9 forbids a nested repo; the enclosing home repo has no HEAD, so branches/worktrees are impossible and commits there are excluded |
| I-02 | 2026-11-06 | Postgres runs in a Docker container started by `scripts/db_up.sh` (Compose plugin not installed; `docker-compose.yml` retained) | Avoids installing a global tool; same settings |
| I-03 | 2026-11-06 | Python 3.12 venv at `.venv`; sync psycopg 3 with dict rows; FastAPI sync endpoints | Simplicity; deterministic tests |
| I-04 | 2026-11-06 | Simulators are separate ASGI apps mounted in one process by default (separately runnable). Adapters take an `httpx.Client`; tests inject `TestClient` | Keeps the HTTP boundary (AD-09) without extra processes |
| I-05 | 2026-11-06 | Sims use a pull model (`GET /events?since=`) instead of push webhooks | Deterministic; allows duplicate and out-of-order injection |
| I-06 | 2026-11-06 | Model calls: `mock` (deterministic heuristic standing in for the model) and `replay` modes are the defaults; `live` is implemented behind a guard and only tested with `httpx.MockTransport` | Budget is $0; mock/replay outputs are labelled simulated and are never presented as measured model quality |
| I-07 | 2026-11-06 | Each agent uses its own test database | Parallel pytest runs would otherwise truncate each other's data |
| I-08 | 2026-11-06 | Audit hash chain in the MVP (per review decision 17); `audit.append` normalises timestamps to UTC | Tamper evidence; DB trigger forbids update/delete/truncate |
| I-09 | 2026-11-06 | MVP feedback is structured capture only (lost-deal review, feedback_item); themes/backlog/experiments are not implemented | Directive section 8 |
| I-10 | 2026-11-06 | Autonomy levels renamed A0-A4 (docs) and audit hash chain moved into the MVP | Review findings A-12, B-05 |
| I-11 | 2026-11-06 | Default API port 8765 (not 8000) | Another application on this machine answers on 8000 |
| I-12 | 2026-11-06 | Approval hash recomputed at execution from live recipient; approvals single-use; adapters need a gateway execution token | Review finding B-01, B-02 |
| I-13 | 2026-11-06 | After the first real eval run (20/29), 7 scenarios were corrected (they omitted simulated time for the sync lag, wrong approver role, wrong audit event name, schedule not registered), the hold metric now counts only triage holds, S20 moved to pending. History recorded in TEST_RESULTS.md | Scenario SQL had been written before the system existed; changes are not hidden |
| I-14 | 2026-11-06 | `audit.append` JSON-encodes non-JSON values (datetimes) with `default=str`; hash input already did | Bug found during implementation |
| I-15 | 2026-11-06 | Runtime creates and migrates its database if absent; registers a daily `pipeline.scan` schedule and the account lifecycle filter | Fresh-checkout robustness; S22 needs the scan |
| I-16 | 2026-11-06 | Baseline refreshed after the match-resume path: S18 provider_b accuracy 0.9375 -> 0.90 (more leads now continue to enrichment; sample of 10-16 observations). A cross-account link bug found by the scope guard (denied tool call) was fixed first | The change is a sample-size effect, not a degradation; recorded rather than loosened |

## Model-evaluation phase (2026-11-06)
- **E-01 No live calls in preparation.** Mode stayed `mock`, budget $0, no key used. New live-run code refuses without all existing guards plus `--approved-budget-usd` and an owner-created approval file. Tested with network disabled.
- **E-02 Evaluate tasks as functions, outside the workflow.** `triage`, `qualify`, `research_brief`, `account_decide` are pure functions of their input, so the real-vs-mock comparison needs no database or graph. Workflow architecture untouched.
- **E-03 No change to existing code or fixtures.** Only new files (`gtm/eval/model_eval.py`, its tests, `model_eval/`). Baseline copies and SHA-256 manifest in `model_eval/baseline_v1/`.
- **E-04 Live client defects recorded, not fixed.** Forced `tool_choice` (HTTP 400 on the default model), no task prompts, single price pair, unenforced `max_cost_usd`, live outputs not recorded. Fix proposed in `model_eval/02_model_integration_review.md` section 4; awaiting approval.
- **E-05 Labels are labelled by origin** (18 world-truth, 38 designer). Ambiguous cases use acceptable-sets. Owner review requested.

- **E-06 Zero-cost directive (owner, 2026-11-06).** Budget $0, permanently for this phase: no live or small test calls, no keys, no live mode, no other paid APIs. The paid staged plan (E-04 follow-up) is withdrawn. A lock file `model_eval/ZERO_COST_LOCK.md` makes `LiveClient` refuse real-network use before reading any key.
- **E-07 Live client repaired offline** (forced tool_choice removed, task prompts, per-model prices, pre-send cost caps, failure classes, live recordings kept separate). Tested only with `httpx.MockTransport`; unverified against the real API. One existing test changed on purpose: unknown models are now refused.
- **E-08 Dataset v2** (64 cases) derived from v1 (unchanged) with 15 logged changes; label statuses ground_truth/judgement/ambiguous/policy. Primary `qualify` criterion = routing, chosen after seeing mock band disagreement (disclosed).
- **E-09 Local model not installed.** Llama 3.2 3B weights exist but no runtime; the local-model rehearsal is deferred and not planned.

- **E-10 Owner decisions 2026-11-07.** (1) Independent review of the 23 contestable labels: done as a blind pass by an automated reviewer under a pre-fixed rule (R1 agree / R2 adopt if reviewer high-confidence / R3 split decision / P policy); v1 and v2 preserved, v3 derived, every proposal logged with rationale and mock before/after. (2) A low-confidence employee count must not hold or disqualify a lead: implemented as `apply_hard_constraints` with threshold 0.6 (assumption), `evidence_needed` in the lead rationale, audit event `lead.evidence_needed`; region rule unchanged. (3) Local-model rehearsal deferred: nothing installed or downloaded. (4) Zero-cost restrictions permanent.
- **E-11 Limits of the review:** the reviewer was automated and not a human, so its errors may correlate with those of whoever wrote the labels; 9 split decisions need the owner; the 0.6 threshold and treating missing confidence as low are unconfirmed.

- **E-12 Final business policy (owner, 2026-11-07).** (1) The nine split decisions: resolved only where the account-routing policy is unambiguous (A-not-now, A-stalled, T-ambig-existing-customer); Q-lowconf-region partly resolved; five left contested (not forced). v1-v3 preserved, v4 created with a full change log. (2) 0.6 confidence threshold retained provisionally and documented as a configurable business-policy value (env `GTM_HARD_CONSTRAINT_MIN_CONFIDENCE`), not statistically validated; missing confidence = low. (3) Region uses the same rule as employee count (flag for human verification, never auto-disqualify); unknown mandatory values are flagged too. (4) Account-routing policy applied: `triage_gate` now holds unclear intent and spam at any confidence. Documented gaps, deliberately not built: promotional vs transactional message class, support routing, timing extraction, priority field, verification queue/enrichment trigger.

