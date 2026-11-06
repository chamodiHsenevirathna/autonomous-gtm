# 3. Evaluation dataset, methodology and comparison metrics

## 3.1 Evidence labels (never blended)
| Label | Meaning here |
|---|---|
| **GT** | A label taken from the generated world's ground truth (e.g. `enq_008` is a vendor). 18 of 56 cases are `world_truth`. |
| **Designer** | A label I chose from the rubric. A judgement, can be wrong, and is **not** ground truth. 38 of 56 cases. Ambiguous cases list several acceptable answers instead of one. |
| **MOD** | Any output produced by the mock or a model. Mock results are *measured on a simulation*; they say nothing about real model quality. |
| **Objective check** | Computed by code from the case and the output; reproducible. |
| **Human-judged** | Requires a person (groundedness of reasoning, appropriateness of tone and action). Never auto-scored. Produced as a blinded sheet. |
All cases are synthetic and fictional. None is real customer data. No business outcome (conversion, revenue, time saved) is measured or implied.

> **Revised 2026-11-07.** The active dataset is now **v4** (`cases_v4.jsonl`, 68 cases) after the owner's final business-policy decisions (`10_business_policy.md`); triage cases carry a checkable `must_hold` expectation evaluated with the production `triage_gate`, qualify cases carry `evidence_needed_expected`, and `contested` marks cases deliberately left unresolved. Everything below describes earlier versions where it differs.
>
> **Earlier (2026-11-07).** The active dataset is now **v3** (`cases_v3.jsonl`, 65 cases; ground_truth 21 / judgement 20 / ambiguous 14 / policy 10) after the blind label review and the owner's confidence policy (`09_independent_label_review.md`); the `qualify` scorer now calls the production rule `apply_hard_constraints` and checks that low-confidence values raise an evidence request instead of holding a lead.
>
> **Earlier note (2026-11-06).** v2 was **v2** (`dataset/cases_v2.jsonl`, 64 cases; label statuses ground_truth 21 / judgement 20 / ambiguous 14 / policy 9). v1 (56 cases) is kept unchanged. Counts in 3.1 and 3.2 below describe v1; see `06_label_review_report.md` for v2 and every change. Rates are computed over distinct cases (repeats are not independent), with 95% Wilson intervals; the primary `qualify` criterion is the routing decision (disclosed as chosen after seeing results). Live comparison sections (3.5 step 1 and the human-sheet comparison against a real model) are **suspended**: only mock, doubles and, if approved, a local model are in scope.

## 3.2 Dataset (v1 description, `dataset/cases.jsonl`, 56 cases)
Each case contains the exact `input` passed to the client, `expected` objective labels, `label_basis`, and notes. Rebuild with `python dataset/build_cases.py` (deterministic).

| Task | Cases | Requested area covered |
|---|---|---|
| `triage` | 20 | genuine qualified (4), spam/vendor/recruiter (6), low-fit people who are still genuine (2), injection (4), ambiguous (4) |
| `qualify` | 20 | qualified (5), low-fit incl. hard ICP limits (5), ambiguous (3), missing data (3), conflicting / low-confidence data (2), injection in message or in research text (2) |
| `research_brief` | 8 | grounded pages (3), conflicting sources (1), injected pages (2), no sources (1), tempting-inference trap (1) |
| `account_decide` (routing) | 8 | new qualified lead, interested reply, unsubscribe, bounce, not-now, stalled deal, question, no change |

Counts by category (dataset-wide): qualified 9, spam/vendor 6, low-fit 7, injection 8, ambiguous 8, missing data 3, conflicting data 2, grounded 5, conflicting sources 1, routing 5, safety 2.

Expected outcomes are of four kinds: an exact label; a set of **acceptable** labels/bands (for ambiguous cases); a **routing** expectation (`qualified` / `low` / `either`) and the final band **after** the code-enforced ICP constraints; and **forbidden** behaviours (a number that must not appear, an action that must not be proposed, a claim substring that would prove an injection or fabrication succeeded).

Honest design notes: (a) several `qualify` cases deliberately pair a strong message with a hard-constraint breach (30 employees, unserved region) because the *final* decision is the code's downgrade, not the model's band; (b) conflicting provider data reaches `qualify` only as a single value with a confidence, because that is how the real workflow passes it, so "conflict" here means low confidence; (c) one `research_brief` case uses pages that contradict each other, to see whether each claim stays tied to its own page.

## 3.3 Objective metrics (computed by `model_eval.py`)
**Qualification decisions.** `triage`: exact accuracy; acceptable-set accuracy; per-class precision and recall (support is tiny: report counts, never only rates); genuine enquiries wrongly rejected (the costly error). `qualify`: band within the acceptable set; final routing correct (`qualified` vs `low`) after the code constraints; final-band correct where specified.

**Precision and recall (where labels support them).** Routing as a binary decision on cases with a definite expected route (`qualified` recall; `qualified` precision over definite cases; low-fit correctly held). Injection detection recall and false-positive rate for `triage`. Citation validity and injection-page recall for `research_brief`. Not computed where labels are the designer's judgement on ambiguous cases.

**Evidence grounding and unsupported claims.** `research_brief`: every claim must cite a URL that was actually supplied (citation validity); every number in a claim must appear in the cited page and at least 60% of its content words must (lexical support: necessary, not sufficient); forbidden claim substrings absent; zero claims when there are no sources. `qualify`: no numbers (other than the score and counts below 20) that are absent from the input; no `met` criterion citing a `resolved:` field that was not supplied; no use of a planted false figure; `unknowns` must list required missing fields. Anything that passes lexical support still goes to human review for paraphrase-level errors.

**Routing recommendations.** `account_decide`: at least one required action type for the event; no forbidden action type (e.g. no draft or CRM proposal after an unsubscribe or bounce; no CRM create when a CRM record exists); every action carries evidence references. Qualify routing is covered above.

**Structured-output validity.** First-attempt validity rate (no repair needed), validity after the one repair, repair count, hard failures by error class. Measured by wrapping the client's `_produce`, so it works for any backend without changing it.

**Consistency across repeated runs.** Each case run N times (default 3). Per task: share of cases whose decision key (label+injection flag; band+service line; claims-present+flags; action-type set) is identical across all repeats, and mean modal agreement. Mock = 1.0 by construction (a sanity check of the harness, not a result).

**Failure handling.** Number and class of failures (validation, HTTP error, refusal, max-tokens), whether the repair path rescued them, and what the run recorded. Workflow-level handling of an LLM failure is a separate gap (`02` F10).

**Cost and latency.** Tokens in/out, billed cost per run, latency p50 and max per call. Mock reports $0.

## 3.4 Human-judged quality (kept separate)
`human-sheet` creates a CSV of up to 6 cases per task. Output 1 / output 2 are randomly assigned to mock or model per row; the mapping is stored only in `blinding_key.json`, opened after scoring. Reviewers rate **groundedness** (1-5) and **appropriateness of action** (1-5) per output and pick a better one (1 / 2 / tie), with notes. Planned minimum: two reviewers, report agreement; with one reviewer, label it as a single-reviewer result (HUM-real, n=1). Rating is not used to change objective scores.

## 3.5 Comparison protocol
1. Same cases, same inputs, same scorers for mock and model; only the backend differs (`run --mode mock|live`).
2. Report both sides as tables of counts and rates with the case ids of every failure, never a single composite score.
3. `compare` prints per-metric deltas. No significance claims: with 8-24 items per task, differences of one or two cases are noise. State this next to every table.
4. Report mock-vs-model disagreements case by case; a disagreement is a prompt to inspect, not a verdict about who is right.
5. Label-sensitivity check: recompute headline rates with ambiguous (`designer`) cases removed and with them accepted under any listed label; report both.
6. Any prompt change after seeing results creates a new prompt version and a fresh run; results from tuned prompts are labelled as such (the same discipline as the first scenario run in the baseline, where fixes after seeing results were recorded).

## 3.6 Mock results on this dataset (the comparison baseline; `results/mock_v1/`)
3 repeats, 168 calls, $0, all outputs schema-valid on the first attempt, consistency 1.0.
| Task | Result |
|---|---|
| triage (n=20 x 3) | exact accuracy 0.80; acceptable-set 0.95; injection recall 1.0, false positives 0; recruiter recall 0.5; vendor precision 0.67; 0 genuine enquiries wrongly rejected |
| qualify | band acceptable 0.95; routing correct 0.95; `qualified` recall 1.0; precision over definite cases 0.83; low-fit held 0.86; injection never raised the band; no invented numbers, no ungrounded references |
| research_brief | 51 claims; citation validity 1.0; lexical support 1.0; injected pages flagged 1.0 |
| account_decide | required action 1.0; no forbidden actions; no action without evidence |

Mock failures worth knowing (these show the set can discriminate): the subtle recruiter pitch (`T-recruiter-subtle`) is labelled genuine; an off-service request (`Q-off-service`, a mobile game studio) is routed `qualified` because size, region and seniority points outweigh a missed service match; `Q-medium-thin` (600 employees, junior contact, no intent) scores `high` where the designer allowed medium or low. For the mock, injection resistance and claim support are 1.0 **by construction** (it deletes instruction-like sentences and quotes page sentences), so those metrics are only meaningful on the model side.
