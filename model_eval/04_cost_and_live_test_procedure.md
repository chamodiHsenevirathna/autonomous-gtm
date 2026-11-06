# 4. Cost and live-test procedure: SUSPENDED (superseded 2026-11-06)

**Total external API budget for this phase: $0.00. The staged paid test described in the first version of this file is withdrawn.** No live call, small or otherwise, will be made under any stage. The restriction is permanent for this phase unless the owner explicitly changes it in writing.

What is in force:
- `model_eval/ZERO_COST_LOCK.md` exists. While it exists, `LiveClient` refuses any real-network use **before** reading `ANTHROPIC_API_KEY`, and `model_eval.guard_live` refuses `--mode live` (exit code 3, nothing written). Tests assert both, with the network and the environment spied on.
- Mode is `mock`; `GTM_ALLOW_LIVE` unset; budget 0. No key was requested, read or used. No third-party paid service was touched.
- Provider-agnostic: no OpenAI, Gemini or any other paid API was called either.

What was kept, as information only:
- `python -m gtm.eval.model_eval estimate` prints a local, offline token/cost estimate (about $0.7 for one pass on a mid-priced model at the planning prices in `gtm/llm/client.py` `MODEL_PRICES`). It exists so the owner could, in a future phase and **only on their explicit decision**, know the order of magnitude. It is not a proposal and not a recommendation to spend.
- The live client's fixes (see `02`), which make a future test *possible* without making one *happen*.

If the owner ever lifts the restriction, a new plan would be needed; this file's earlier staged procedure should not be reused without being re-reviewed against the then-current API documentation.
