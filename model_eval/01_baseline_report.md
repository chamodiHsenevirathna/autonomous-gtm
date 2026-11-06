# 1. Baseline report (frozen 2026-11-06)

## Git situation (checked, nothing changed)
- Project path: the project root (`Autonomous GTM/`).
- Repository root: the author's home directory (a personal-machine detail, not part of this project). Branch `main`, **zero commits**, everything untracked. No `.git` exists inside the project or its subfolders (searched, excluding `node_modules` and `.venv`).
- No repository was initialised, nothing was staged or committed, nothing was pushed. Because there is no commit, "freezing" is done by **copying files and recording SHA-256 hashes**, not by a tag.

## What is frozen (`model_eval/baseline_v1/`)
| Artifact | Copy | SHA-256 recorded in `MANIFEST.sha256` |
|---|---|---|
| 28-scenario report (json + md) | `eval_output/` | yes |
| Scenario baseline thresholds | `fixtures/baseline.json` (unchanged; identical hash to `backend/fixtures/baselines/baseline.json`) | yes |
| Test and status trackers | `TEST_RESULTS.md`, `IMPLEMENTATION_STATUS.md` | yes |
| Mock model, LLM client, LLM contracts, intake graph, config (hash only, not copied) | `backend/gtm/agents/mockmodel.py`, `llm/client.py`, `contracts/llm.py`, `agents/intake.py`, `config.py` | yes |

Mock-model outputs: the mock is a pure function of its input (no randomness, no clock), so "preserving the outputs" means preserving its source hash plus the recorded per-case outputs on the new dataset (`results/mock_v1/`, hashes in `dataset_and_results.sha256`). The scenario-level mock outputs are embedded in the preserved scenario report. No recorded-response fixtures existed (`backend/fixtures/recorded/` is absent): the system has only ever run in mock mode.

## Reproduction (done)
| Check | Result |
|---|---|
| Re-ran all 28 scenarios against the real system into a separate directory (`reproduction/`) | **28/28 pass, 0 regressions** vs. baseline |
| Compared the new report with the frozen one, ignoring timing fields | Identical except the database row id `eval_run_id` (None vs 1), which is bookkeeping, not behaviour |
| Re-ran the backend suite | **338 tests, all passed** (log: `pytest_reproduction.log`). Run before the 14 new model-eval tests were added; those pass separately |
| Frontend (build, 13 unit, 9 browser) | Not re-run: unchanged and not part of this phase. Last result is in `TEST_RESULTS.md` |
| Existing evaluation fixtures modified | **None.** `baseline.json` hash unchanged; no scenario file touched |

Caveat carried forward: one unexplained full-suite hang (10+ min) was seen once earlier and did not reproduce in 9 later runs, including this one.

## What the baseline does and does not establish
It establishes that the **workflow and its safety controls behave as designed with a deterministic mock**. It says nothing about real model quality. That is exactly the gap this phase addresses.

## Addendum (zero-cost phase): integrity re-check after code changes
- Frozen copies (`eval_output/`, `fixtures/baseline.json`, trackers) verify against `MANIFEST.sha256`: **all OK**.
- Source files hashed before this phase: `mockmodel.py`, `contracts/llm.py`, `intake.py`, `config.py` **unchanged**. `llm/client.py` **changed on purpose** (live-path repair, see `02`); the manifest keeps the pre-change hash as the record.
- After the changes: 28/28 scenarios, 0 regressions (`results/regression_after_changes/`); full backend suite **376 passed, 0 failed** (`results/final_pytest_junit.xml`; 338 earlier + 38 new tests).

## Addendum 2 (2026-11-07): after the confidence policy and dataset v3
- Frozen copies verify against `MANIFEST.sha256`: **all OK**. `baseline.json` hash unchanged (`b20ecb77...`). `cases.jsonl` (v1) and `cases_v2.jsonl` hashes unchanged.
- Source files that changed since the baseline was hashed: `llm/client.py` (previous addendum) and now `agents/intake.py` (owner's confidence policy: one new function `apply_hard_constraints`, plus recording `evidence_needed`). Both are intended and documented; `mockmodel.py`, `contracts/llm.py`, `config.py` are unchanged.
- Regression after the policy change: **28/28 scenarios, 0 regressions** (`results/regression_after_policy/`); full backend suite **392 passed, 0 failed** (`results/final_pytest_junit_v3.xml`). The scenario baseline did not need refreshing: no scenario exercises a low-confidence employee count below the threshold.

## Addendum 3 (2026-11-07): after the final business-policy decisions
- Frozen copies verify against `MANIFEST.sha256`: all OK. `baseline.json` unchanged (`b20ecb77...`). Dataset files `cases.jsonl` (v1), `cases_v2.jsonl`, `cases_v3.jsonl` unchanged (hashes match the recorded ones).
- Source files changed since the baseline was hashed, all intended: `llm/client.py`, `agents/intake.py` (region/low-confidence/unknown handling, `triage_gate`), `config.py` (configurable threshold). `mockmodel.py`, `contracts/llm.py` unchanged.
- Regression: **28/28 scenarios, 0 regressions** (`results/regression_after_final_policy/`); **416 backend tests passed, 0 failed** (`results/final_pytest_junit_v4.xml`). The scenario baseline was not refreshed.
