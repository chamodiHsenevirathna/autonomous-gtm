# Model evaluation phase: zero-cost edition

**Status 2026-11-06: total external API spend is $0.00 and will stay $0.** No API call of any kind was made (Claude, OpenAI, Gemini, anything paid), no key was requested or read, live mode is off, and `ZERO_COST_LOCK.md` makes the live client refuse real-network use before it touches a key.
**Real commercial model performance (Claude or any other) remains untested.** Everything here was measured with a deterministic mock and deliberately faulty test doubles on 68 synthetic cases.

**Latest (2026-11-07):** final business-policy decisions applied (`10_business_policy.md`): region uses the same confidence rule as employee count, 0.6 documented as a configurable business-policy threshold (not validated), account-routing policy mapped to code and evaluation, dataset **v4** created, 3 of the 9 split decisions resolved, 5 left contested.

**Earlier (2026-11-07):** blind label review done and the owner's decisions implemented: see [`09_independent_label_review.md`](09_independent_label_review.md). The local-model rehearsal is **deferred** (nothing installed). Zero-cost rules remain permanently in force.

Start with [`08_validation_matrix.md`](08_validation_matrix.md) (what can and cannot be validated at $0, plus the results), then [`06_label_review_report.md`](06_label_review_report.md).

| # | Deliverable | File |
|---|---|---|
| 1 | Baseline report | [`01_baseline_report.md`](01_baseline_report.md) (frozen copies in [`baseline_v1/`](baseline_v1/)) |
| 2 | Model integration review | [`02_model_integration_review.md`](02_model_integration_review.md) |
| 3 | Datasets: v1 (56), v2 (64), v3 (65), **v4 (68, active)**; all kept | [`cases_v4.jsonl`](dataset/cases_v4.jsonl) by [`build_cases_v4.py`](dataset/build_cases_v4.py); change logs: [`label_changes.json`](dataset/label_changes.json) (v1→v2), [`label_proposals.json`](dataset/label_proposals.json) (v2→v3), [`label_policy_changes.json`](dataset/label_policy_changes.json) (v3→v4) |
| 4 | Methodology and comparison metrics | [`03_methodology_and_metrics.md`](03_methodology_and_metrics.md) |
| 5 | Cost and live-test procedure: **suspended** | [`04_cost_and_live_test_procedure.md`](04_cost_and_live_test_procedure.md) |
| 6 | Limitations and next steps | [`05_limitations_and_next_steps.md`](05_limitations_and_next_steps.md) |
| 7 | Label-review report | [`06_label_review_report.md`](06_label_review_report.md) |
| 8 | Local-model rehearsal: **deferred by owner** (nothing installed; no proposal document is published) | n/a |
| 9 | What can / cannot be validated, with results | [`08_validation_matrix.md`](08_validation_matrix.md) |
| 10 | Independent label review + confidence policy | [`09_independent_label_review.md`](09_independent_label_review.md); raw reviewer output in [`review/`](review/) |
| 11 | Final business policy, split-decision resolution, v4 | [`10_business_policy.md`](10_business_policy.md) |
| - | Mock results on v2 / doubles (earlier v1 run kept in `results/mock_v1/`) | [`results/mock_v4/`](results/mock_v4/model_eval_report.json), [`results/doubles_v4/`](results/doubles_v4/) (older: `mock_v2`, `doubles`) |

Added: `gtm/eval/model_eval.py` (runner, scorers, intervals, label-reliability breakdown, blinded human sheet), `gtm/eval/doubles.py` (seven deliberately bad stand-ins), `gtm/llm/prompts.py`. Changed (offline, tested): `gtm/llm/client.py` live path. The frozen baseline in `baseline_v1/` is untouched; after the code changes the 28 scenarios still pass 28/28 with 0 regressions (`results/regression_after_changes/`).

Reproduce at zero cost:
```bash
source .venv/bin/activate && cd backend
python -m gtm.eval.model_eval run --mode mock --repeats 3 --out ../model_eval/results/mock_v4
python -m gtm.eval.model_eval run --mode double:fabricator --repeats 2 --out /tmp/fab      # any of the 7 doubles
python -m pytest tests/eval tests/llm -q
```

## Open items (all $0, all optional)
Human review of the 5 contested cases and the partly resolved one; deciding whether to build any of the documented gaps (`10`, sections 2 and 6). The local-model rehearsal is deferred.
