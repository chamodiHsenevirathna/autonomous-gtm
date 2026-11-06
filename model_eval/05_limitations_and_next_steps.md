# 5. Identified limitations of this evaluation, and recommended next steps

## 5.1 Limitations (state them next to any result)
1. **Tiny, synthetic sample.** 56 cases (8 to 20 per task). One case flipping moves a task rate by 5 to 12 points. No confidence intervals are meaningful. Rates are sanity checks.
2. **Labels are mostly mine.** 38 of 56 are designer judgements; 18 come from the generated world, whose "truth" was itself written by the same project. Two readers may disagree on the ambiguous ones. A model that disagrees with a label may be right. Mitigation: acceptable-sets on ambiguous cases, owner label review, and the label-sensitivity check in `03`.
3. **Same author, same blind spots.** The mock, the world, the rubric and the dataset were all written by this project. A real model can fail in ways we did not think to include (long enquiries, multi-language, forwarded threads, HTML artefacts, attachments, adversarial formats beyond the keyword-style injections used here).
4. **Injection coverage is narrow.** 8 cases with plain-language instructions. This shows susceptibility to obvious injection, not robustness. Also the code-level safeguards (no send/merge tools; human approval; gateway) are what protect the system, and are not tested by this dataset.
5. **Lexical grounding is weak evidence.** Number and word-overlap checks catch fabrication and copied-in numbers; they miss a wrong paraphrase made of correct words (e.g. "was acquired" vs "acquired a competitor"). Human review is needed to bound this; it is a small sample.
6. **No semantic check of `qualify` rationales** beyond numbers, references, unknowns and the planted traps. Whether the reasoning is sound is human-judged.
7. **Isolation from the workflow.** Tasks are scored as functions, not inside the graph. Interactions (e.g. research output feeding qualify, hard-constraint downgrade, human review) are not exercised with a real model. The end-to-end effect is a later, separate step.
8. **Consistency needs repeats, and nondeterminism cannot be pinned** (sampling parameters are not accepted by current models). Three repeats show instability but cannot characterise it.
9. **Thinking and effort are free parameters.** Results depend on the effort level and prompt version; a different setting is a different system. Every run records model id, prompt hash and settings.
10. **Cost numbers are estimates** from a cached price table and a crude token heuristic.
11. **Not covered:** `draft_message` quality and claim-checking (the highest-risk generated text, but behind human approval and a code screen), `reply_intent`, `feedback_extract`, latency under load, rate limits, model-version drift over time, cost at volume, bias or fairness across company types, and anything about business outcomes.
12. **Mock is not a calibrated baseline.** It is a deterministic heuristic that reads like a rubric. "Model beats mock" would not mean "model is good enough"; "model loses to mock" may mean a weak prompt. Both need the human review.

## 5.2 Defects found while preparing (no fixes made in this phase)
| Id | Defect | Where | Proposed handling |
|---|---|---|---|
| F1 | Forced `tool_choice` returns HTTP 400 on the default model | `llm/client.py` | **Fixed offline** (unverified against the real API) |
| F2 | No task prompts or rubric sent to a live model | `llm/client.py` | **Fixed offline** (`llm/prompts.py`; effectiveness unknown) |
| F3-F6 | Output cap/thinking, one price pair for all models, unenforced `max_cost_usd`, live outputs not recorded | `llm/client.py` | **Fixed offline** |
| F7 | Permissive output models | `contracts/llm.py` | Defer; objective scorers cover it |
| F10 | No workflow-level test of an LLM failure | tests | Add one scenario with a registered failing mock (no API needed) |
| D1 | Dataset note wrongly said the mock would fail the German case; it passes it by default-to-genuine | `dataset/build_cases.py` | Corrected before delivery |

## 5.3 Next steps (revised 2026-11-07)
Decided by the owner: policy labels resolved where unambiguous; 5 contested cases left contested; 0.6 retained as a configurable business-policy threshold (not validated); region follows the same rule; account-routing policy fixed (`10`); local-model rehearsal deferred; zero-cost restrictions permanent.

Optional, all $0 and all separate decisions (none built): human review of the contested cases; a transactional vs promotional message class; a support route; timing extraction for "not now"; a priority field; a verification queue or enrichment trigger. Real commercial model performance remains untested.
