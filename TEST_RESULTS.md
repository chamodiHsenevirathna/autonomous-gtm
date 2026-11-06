# Test results

| Date | Scope | Command | Result |
|---|---|---|---|
| 2026-11-06 | M0 foundation (migrations, seed, audit chain/tamper, hash, token) | `pytest tests/test_m0_foundation.py` | 5 passed |
| 2026-11-06 | Approvals service + execution gateway + reply router (fake adapter facade) | `pytest tests/gateway` | 14 passed |
| 2026-11-06 | Full backend suite (all agents) | `pytest tests` | **332 passed** (67 s) |
| 2026-11-06 | Evaluation suite on the REAL system, first run | `python -m gtm.eval.runner --harness gtm.harness:Harness` | 20/29 passed, 9 failed (7 scenario-assumption bugs, 1 over-broad metric, 1 missing audit event) |
| 2026-11-06 | Evaluation suite after fixes (S20 moved to pending) | same | **28/28 passed**, 0 regressions; baseline frozen |
| 2026-11-06 | Evaluation runner from a brand-new database | `runner --scenarios S01,S25` | 2/2 passed |
| 2026-11-06 | Live HTTP API golden thread (curl) | demo/enquiry -> approve x3 -> advance -> reply -> audit/verify | Works; message parked `sync_pending` then executed; audit chain OK (38 events); 13 gateway checks per execution |
| 2026-11-06 | Frontend | `npm run build`, `npm test`, `npx playwright test` | build OK; 13/13 unit; 7/7 e2e (mock mode) |

Notes: scenario results are *measured on simulation* or *machinery checks*. They are not real-world performance. Pending scenarios (not run): S08, S12, S20, S21, S23, S26, S53, S56.
| 2026-11-06 | Full backend suite after final backend fixes | `pytest tests` | **337 passed** (97 s) |
| 2026-11-06 | Evaluation after final fixes | runner | 28/28 passed; baseline refreshed (S18 provider_b accuracy 0.9375 -> 0.90, sample-size effect); next run 0 regressions |
| 2026-11-06 | Stress: concurrency-sensitive tests x8 | `pytest tests/orchestration tests/agents tests/gateway` | 8/8 clean. (One earlier unexplained hang of the full suite did not reproduce) |
| 2026-11-06 | Clean-environment setup | fresh venv, `pip install -e backend[dev]`, tests + S01 | passed |
| 2026-11-06 | FINAL verification after last fixes (empty-DB overview 500 fixed + regression test; descriptive node names) | backend / eval / frontend | backend **338 passed**; eval **28/28, 0 regressions**; frontend build OK, **13/13** unit, **9/9** Playwright (mock + real backend + http-down) |

## Model-evaluation preparation phase (2026-11-06; no live calls)
| Date | Scope | Command | Result |
|---|---|---|---|
| 2026-11-06 | Baseline reproduction: 28 scenarios against the real system, separate output dir | `python -m gtm.eval.runner --out-dir ../model_eval/baseline_v1/reproduction` | 28/28 pass, 0 regressions; report identical to frozen one except DB row id |
| 2026-11-06 | Baseline reproduction: backend suite | `pytest tests` | 338 passed (before the new tests below) |
| 2026-11-06 | New: model-evaluation harness tests (dataset integrity, mock run, consistency, live-guard refusals incl. CLI with network disabled, scorer negative controls, blinded sheet) | `pytest tests/eval/test_model_eval.py` | 14 passed |
| 2026-11-06 | Mock on the 56-case model-eval set, 3 repeats, 168 calls, $0 | `python -m gtm.eval.model_eval run --mode mock --repeats 3` | recorded in `model_eval/results/mock_v1/`; measured on simulation; no live model involved |

## Zero-cost evaluation phase (2026-11-06; $0, no API calls, no keys)
| Date | Scope | Result |
|---|---|---|
| 2026-11-06 | Full backend suite after live-client repair, dataset v2, doubles | **376 passed, 0 failed** (338 + 38 new) |
| 2026-11-06 | 28 scenarios after the changes | 28/28, 0 regressions |
| 2026-11-06 | Mock on dataset v2, 3 repeats (192 calls, $0) | routing correct 0.96; 5 of 64 cases fail primary criteria; see `model_eval/08_validation_matrix.md` |
| 2026-11-06 | Seven faulty doubles through the harness | each caught by its target metric (tests assert it) |
| 2026-11-06 | `--mode live` via CLI | refused, exit 3, nothing written, network spied on in test |

## 2026-11-07: confidence policy + independent label review (still $0)
| Scope | Result |
|---|---|
| Full backend suite after `apply_hard_constraints` and dataset v3 | **392 passed, 0 failed** |
| 28 scenarios after the policy change | 28/28, 0 regressions (baseline not refreshed; unchanged) |
| New unit tests for the confidence rule | 11 passed |
| Mock on dataset v3 (3 repeats, 195 calls) | routing 0.96; 6 of 65 cases fail primary criteria; see `model_eval/08_validation_matrix.md` |

## 2026-11-07: final business-policy decisions (still $0)
| Scope | Result |
|---|---|
| Full backend suite | **416 passed, 0 failed** |
| 28 scenarios | 28/28, 0 regressions (baseline not refreshed) |
| New unit tests: confidence rule (both fields, boundary, missing, configurable) + triage gate | 26+ passed |
| Mock on dataset v4 (3 repeats, 204 calls) | routing 0.96; 6 of 68 cases fail primary criteria; must-hold held 7 of 10; see `model_eval/08_validation_matrix.md` |

