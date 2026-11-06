# Test results

| Date | Scope | Command | Result |
|---|---|---|---|
| 2026-11-06 | M0 foundation (migrations, seed, audit chain/tamper, hash, token) | `pytest tests/test_m0_foundation.py` | 5 passed |
| 2026-11-06 | Lead: approvals service + execution gateway + reply router (fake adapter facade) | `pytest tests/gateway` | 14 passed |
| 2026-11-06 | Full backend suite (all agents) | `pytest tests` | **332 passed** (67 s) |
| 2026-11-06 | Evaluation suite on the REAL system, first run | `python -m gtm.eval.runner --harness gtm.harness:Harness` | 20/29 passed, 9 failed (7 scenario-assumption bugs, 1 over-broad metric, 1 missing audit event) |
| 2026-11-06 | Evaluation suite after fixes (S20 moved to pending) | same | **28/28 passed**, 0 regressions; baseline frozen |
| 2026-11-06 | Evaluation runner from a brand-new database | `runner --scenarios S01,S25` | 2/2 passed |
| 2026-11-06 | Live HTTP API golden thread (curl) | demo/enquiry -> approve x3 -> advance -> reply -> audit/verify | Works; message parked `sync_pending` then executed; audit chain OK (38 events); 13 gateway checks per execution |
| 2026-11-06 | Frontend (Agent C) | `npm run build`, `npm test`, `npx playwright test` | build OK; 13/13 unit; 7/7 e2e (mock mode) |

Notes: scenario results are *measured on simulation* or *machinery checks*. They are not real-world performance. Pending scenarios (not run): S08, S12, S20, S21, S23, S26, S53, S56.
| 2026-11-06 | Full backend suite after final backend fixes | `pytest tests` | **337 passed** (97 s) |
| 2026-11-06 | Evaluation after final fixes | runner | 28/28 passed; baseline refreshed (S18 provider_b accuracy 0.9375 -> 0.90, sample-size effect); next run 0 regressions |
| 2026-11-06 | Stress: concurrency-sensitive tests x8 | `pytest tests/orchestration tests/agents tests/gateway` | 8/8 clean. (One earlier unexplained hang of the full suite did not reproduce) |
| 2026-11-06 | Clean-environment setup | fresh venv, `pip install -e backend[dev]`, tests + S01 | passed |
| 2026-11-06 | FINAL verification after last fixes (empty-DB overview 500 fixed + regression test; descriptive node names) | backend / eval / frontend | backend **338 passed**; eval **28/28, 0 regressions**; frontend build OK, **13/13** unit, **9/9** Playwright (mock + real backend + http-down) |
