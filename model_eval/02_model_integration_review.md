# 2. Model integration review

> **Update 2026-11-06 (zero-cost phase).** F1 to F6 were fixed **offline** in `gtm/llm/client.py` and the new `gtm/llm/prompts.py`, with 20 mock-transport tests (`tests/llm/test_live_client_offline.py`) and one existing test adjusted (unknown models are now refused). The fixes encode my reading of the API documentation; **none has been checked against the real service**, and none can be without a paid call. F7, F8 and F10 remain open. Section 4 below is therefore implemented, not proposed; read the status column.

| Finding | Status |
|---|---|
| F1 forced `tool_choice` | Fixed: `tool_choice: {"type":"auto"}`; the system prompt instructs the `emit_result` call. Unverified against the real API |
| F2 no task prompts | Fixed: `prompts.py` with a rubric per task (used by the live client only; mock/replay hashes unchanged). Effectiveness unknown |
| F3 output cap / thinking | Partly: `max_tokens` 4096; optional `GTM_LIVE_EFFORT` is sent only if set (not defaulted, because I cannot verify which models accept it) |
| F4 one price pair | Fixed: per-model `MODEL_PRICES`; unknown model refused before any request |
| F5 unenforced cap | Fixed: worst-case cost (input estimate + every output token allowed) is checked **before sending** against the run budget and `max_cost_usd`; every billed turn counts, tool call or not |
| F6 live outputs not recorded | Fixed: recorded under `fixtures/live/` so they cannot overwrite mock recordings |
| New | Refusal, `max_tokens`, HTTP 4xx and missing-tool-call are distinct `failure_class` values on the error |
| New | `ZERO_COST_LOCK.md` blocks real-network use before any key is read |
| F7 permissive output models, F8 nondeterminism, F10 workflow-level LLM failure test | Open |

Reviewed: `gtm/llm/client.py` (177 lines), `gtm/contracts/llm.py`, `gtm/config.py`, `gtm/agents/mockmodel.py`, the call sites in `gtm/agents/intake.py` / `account.py` / `orchestration/ctx.py`, `gtm/gateway/router.py`, `gtm/eval/*`, and `tests/llm/test_llm.py`. API facts below were checked against the current Claude API reference available in this environment; they should be re-verified against the live docs when the live-code change is made.

## 1. How it fits together
- Seven tasks (`triage`, `qualify`, `research_brief`, `account_decide`, `draft_message`, `reply_intent`, `feedback_extract`), each with a Pydantic output model (`OUTPUT_MODELS`). Callers go through `LLMClient.complete(LLMRequest)`; the workflow never sees which backend answered.
- Three backends behind one `BaseClient.complete`: `MockClient` (registered Python functions), `ReplayClient` (fixtures keyed by SHA-256 of task + prompt version + input), `LiveClient` (Anthropic Messages API over `httpx`).
- Output is validated against the Pydantic model; on failure there is **exactly one** repair retry with the validation errors; a second failure raises `PermanentError`.
- Untrusted text is passed under `input["untrusted"]`; `LiveClient` re-labels it `untrusted_data` and the system prompt tells the model to treat it as data.
- Live mode needs all of: `GTM_LLM_MODE=live`, `GTM_ALLOW_LIVE=1`, `GTM_LIVE_BUDGET_USD>0`, and `ANTHROPIC_API_KEY` in the environment. Default: all off.
- Safety is **not** delegated to the model: agents cannot send, merge, decide or write human-owned fields; the code applies hard ICP constraints that can only *downgrade* the model's band (`intake._decide`); every external action still needs human approval and passes the gateway. So a misbehaving model can produce a wrong *recommendation*, not an unapproved *action*. This is why evaluating the model is a quality question, not a safety-critical one.

## 2. Smallest change to evaluate a real model without altering the workflow architecture
The four tasks in scope are pure functions of their input, so they can be evaluated **outside the workflow** (no database, graph or gateway), through the same `LLMClient` interface the workflow uses. That is what `gtm/eval/model_eval.py` does. The architecture stays untouched; only `LiveClient` needs repair (section 4). Swapping the backend inside the full graph is possible later through configuration, with no graph changes.

## 3. Findings
Severity: **B** blocks any valid live test; **M** would distort results; **L** minor.

| ID | Sev | Finding | Evidence | Consequence |
|---|---|---|---|---|
| F1 | **B** | `LiveClient` sends `tool_choice: {"type":"tool","name":"emit_result"}`. Forced tool choice (`any` / `tool`) is rejected with HTTP 400 on Sonnet 5.5, Opus 5.5 and Fable 5.1. The client's default model is `claude-sonnet-5-5`. | `client.py` request body; API reference for those models | First live call fails (`PermanentError: anthropic 400`). Only `MockTransport` tests exist, so this was never observable. |
| F2 | **B/M** | No task instructions. `prompt_version` is only a hash/label; nothing selects a template. The model receives one generic system prompt, the input JSON and the output schema. The rubric the mock implements (company-size bands, region list, score thresholds 70/45/15, criteria names, which action types fit which events, "claims must come from the pages") is nowhere in the live request. | `SYSTEM_PROMPT`; `_produce` builds `user = canonical({task, input, untrusted_data})` | A live model would be graded against an unstated rubric. Results would measure prompt absence. Task-specific prompts are required before any comparison is fair. |
| F3 | M | `max_tokens` is 2048 and no `thinking`/`effort` setting is sent. Current Sonnet 5.5 runs adaptive thinking by default and thinking tokens count toward output. | `json={... "max_tokens": 2048 ...}` | Possible truncation before the tool call (`max_tokens` stop) and unpredictable cost. Needs an explicit effort level and a larger cap. |
| F4 | M | Price constants are one pair ($3 / $15 per million tokens) for every model. Sonnet 5.5 is listed at $2 / $10, Haiku 5.5 at $0.10 / $0.50, Fable-tier at $10 / $50. | `PRICE_IN/PRICE_OUT`; skill price table (cached 2026-10-06) | Budget guard and reported cost are wrong by model: over-counts cheap models (safe), **under-counts Fable-tier models by ~3x (unsafe)**. |
| F5 | M | `LLMRequest.max_cost_usd` is accepted and propagated but **never enforced**. The budget guard checks `spent >= budget` *before* each call, so the call that crosses the cap still happens; repair retries add calls. | `grep max_cost_usd`: only `ctx.py` and the contract | Overshoot by up to one call (+ repair). Small, but the guard is not a hard cap. The runner adds `--max-calls` and a per-run budget cap to compensate. |
| F6 | M | Live responses are never recorded; recording happens only when `mode == "mock"`. | `if self.mode == "mock" and self.record` | A live run cannot be replayed through the workflow afterwards. The new runner stores every raw output, which is sufficient for scoring but not for workflow replay. |
| F7 | L | Output models are permissive: `confidence` has no 0..1 bound; `score` and `band` can disagree (e.g. score 90, band `low`); `evidence_ref` and `source_ref` are free strings never checked against the input; `claims[].source_ref` may be `None` (the intake graph drops such claims, which is the right behaviour). | `contracts/llm.py` | Structurally valid but semantically bad output passes validation. The new scorers check these things objectively; consider tightening later (not now). |
| F8 | L | Nondeterminism is uncontrolled and cannot be pinned: sampling parameters (`temperature`, `top_p`) are rejected by current models. | API reference | Consistency must be *measured* by repeats, not assumed. |
| F9 | L | The repair loop appends the validation error text to the user message. Fine, but the error text can echo model output; no secrets involved. | `_produce` | None. Noted for completeness. |
| F10 | info | Failure handling: a `PermanentError` from the LLM raises inside a graph node. Existing tests cover the client side (repair then success, repair then failure) and the runner's retry policy by error class, but **no test exercises the full workflow with a live-like failing model**. | `tests/llm/test_llm.py` | Failure handling at workflow level is not evidenced for LLM errors. Add one scenario using a registered failing mock (cheap, no API). Proposed in `05`. |
| F11 | info | `draft_message`, `reply_intent` and `feedback_extract` exist but are outside this evaluation's seven requested areas. | n/a | Excluded deliberately; `reply_intent` only matters after hard signals (unsubscribe/bounce) have been handled in code. |

What is sound and should be kept: the triple guard, key only from the environment, fixed single tool (inputs cannot add tools), untrusted-data labelling, schema validation with one repair, mock/replay/live behind one interface, token and cost accounting per run.

## 4. Proposed live-path change (needs approval; not made)
Kept deliberately small. All of it is inside `LiveClient` and one new module; mock and replay behaviour and every existing fixture hash are unaffected as long as `prompt_version` stays `v1` for them.

1. **Tool choice.** Remove forced `tool_choice`; send `{"type":"auto"}` (or omit), set `strict: true` on the `emit_result` tool and add one instruction sentence naming the tool. Alternatively use structured outputs (`output_config.format`). Keep the existing "ask once more if no tool call" loop as the fallback.
2. **Task prompts.** Add `gtm/llm/prompts.py` with one instruction block per task (rubric, allowed values, "cite only from provided data", "say unknown rather than guess", the untrusted-data rule). Selected by `(task, prompt_version)` and used only by `LiveClient`; store the prompt text hash in the response so results are tied to a prompt version. Bump to `v2`, keep `v1` for the mock.
3. **Output budget.** `max_tokens` 4096, `output_config: {effort: "low"}` for these classification-style tasks (to be tuned in Stage 2), and read `usage` for billing as today.
4. **Price table.** Replace the two constants with a per-model table; refuse unknown models; make `max_cost_usd` and the run budget hard (check projected cost using input-token estimate before sending).
5. **Test.** Extend `tests/llm/test_llm.py` with `MockTransport` cases asserting: no forced `tool_choice` in the request body, task prompt present, cost uses the per-model table, refusal when the budget would be exceeded.
6. **Stop-reason handling.** Treat `stop_reason == "refusal"` or `"max_tokens"` as a distinct, recorded failure class (not a silent parse error).

Open API question to confirm at implementation time with the live docs: whether to request fallbacks for refusals. For this evaluation they should stay **off** so that refusals are visible as results.
