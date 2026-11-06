> **Update 2026-11-07:** the 23 contestable labels below were then reviewed blind and the owner decided the confidence question (change 6 and 'Hard constraints ignore confidence'). See `09_independent_label_review.md`. The text below describes v2 as it was on 2026-11-06; v3 is the active dataset.

# 6. Label-review report (dataset v1 to v2)

Scope: all 56 v1 labels were re-read against the written rubric and against the generated world's own data; 8 cases were added. v1 (`dataset/cases.jsonl`) is **left unchanged**; v2 (`dataset/cases_v2.jsonl`, 64 cases) is derived by `dataset/build_cases_v2.py`; every difference is in `dataset/label_changes.json` with a reason. A test fails if a v1 case differs from v2 without a logged change.

**Who reviewed:** one reviewer, the same author who wrote the mock, the world and v1. This is a self-review, not independent validation. The owner has not yet reviewed the labels.

## 1. Label status (every v2 case has one)
| Status | Meaning | Cases |
|---|---|---|
| `ground_truth` | Taken from the generated world's own fields (enquiry kind, expected band, true company data). Still synthetic, and written by this project: it means "what the simulation says", not what a real market would say. | 21 |
| `judgement` | One answer chosen by the author from the rubric; the author is confident. | 20 |
| `ambiguous` | Several answers are defensible; all acceptable ones are listed. | 14 |
| `policy` | The label encodes this system's own rule (for example, no drafts after an unsubscribe), not a fact about the world. | 9 |
| total | | 64 (triage 23, qualify 23, research 9, account 9) |

The report separates results on `ground_truth` + `judgement` ("reliable") from `ambiguous` + `policy` ("contestable"), with 95% Wilson intervals, so a reader can discount the contestable ones.

## 2. Problems found in v1, and what was done
| # | Problem | Cases | Action | Seen mock output first? |
|---|---|---|---|---|
| 1 | **Invented inputs.** For enquiries from the world, v1 used company data I had made up (for example Harrowgate "2,200 employees, EMEA, application modernisation" where the world says 1,926, APAC). Labels "from the world" were therefore attached to inputs that were not the world's. | Q-high-clear, Q-high-modernise, Q-medium-explore, Q-medium-thin, Q-low-cheap, Q-followup-nudge | Rebuilt `resolved`/`contact` from the world's true values (confidence 0.9) | I had seen v1 results, but the change follows the world's data and makes the mock's bands fail more, not less |
| 2 | **Vague acceptance.** Three world-derived cases accepted any band, which cannot fail. | Q-medium-explore, Q-medium-thin, Q-followup-nudge | Expected band set to the world's (`medium`) | Same as above: stricter, not looser |
| 3 | **Overrode the world.** World says `T-enq_013` is spam; v1 labelled it `unclear` with no reason. | T-enq_013 | Primary label restored to `spam`; `unclear` kept acceptable (the first sentence reads like a real request) | **Yes** (the mock said `unclear`; with the change the mock's answer is only "acceptable", not exact) |
| 4 | A message with no business need, only instructions to an AI, is better called spam than unclear. | T-inj-ai-assistant | Primary `spam`; `unclear` stays acceptable | No (the mock answered `unclear`; the change makes its answer inexact) |
| 5 | **Internal inconsistency.** Band `medium` routes to `qualified`, but the expected route was `low`. A mobile-game build matches no service line. | Q-off-service | Acceptable bands narrowed to `low`/`none` | **Yes** (the mock was already failing the route check) |
| 6 | The <50-employee hard constraint is applied to a value with confidence 0.3. | Q-lowconf-size | Expected final band recorded as `low` (current behaviour). Flagged as a **design question** below, not a model failure | No |
| 7 | Policy presented as truth: "no draft after not-now". | A-not-now (and all account cases) | Re-labelled `policy` | No |

Net effect on direction: changes 3 and 5 were made after I had seen the mock's v1 output. Neither makes the mock look better (3 makes it less exact; 5 keeps a failure), and both are flagged `seen_mock_output: true` in the change log. No label was loosened to make the mock pass.

## 3. Additions (8 cases, coverage)
`Q-enq_007` (no contact, seniority unknown), `Q-enq_014`, `Q-enq_015` (world-derived); `T-fwd-genuine` (forwarded thread with a legal footer), `T-phish-verify` (phishing wording with none of the mock's spam keywords), `T-inj-german` (injection in German); `R-html-noise` (markup, navigation and cookie banner text); `A-meeting-booked`. Written before running the mock on them. The mock then fails three on the primary criterion (phishing wording, German injection, markup/cookie noise); the three world-derived qualify cases expose the band disagreement described below.

## 4. Remaining weaknesses (not fixed; read before trusting any number)
- **Same-author circularity.** The generator's `expected_band` and the mock were written together. Result: for **every** world-`medium` enquiry (all large, senior, well-matched companies) the mock says `high`. The disagreement is about what "medium" means: the generator seems to grade the vagueness of the enquiry, the mock grades firmographic fit. High and medium both route to `qualified`, so no routing decision changes. Because of this, the **primary qualify criterion is the routing decision**, with band agreement reported separately (0.70, interval 0.49 to 0.84). This choice was made after seeing the mock's bands (disclosed, and the band figure remains in every report).
- **`acceptable` lists are generous on ambiguous cases** (up to 3 labels). A model that hedges would pass more often than one that commits. Strict exact accuracy is reported alongside.
- **Contestable labels:** 23 of 64 cases. The owner's review of these is the most valuable remaining step.
- **Hard constraints ignore confidence** (change 6). A company with a 0.3-confidence "45 employees" is capped at `low` and held. Whether that is right is a product decision for the owner; the evaluation records it, it does not decide it.
- **The research-grounding checks are lexical**, so an inaccurate paraphrase made of correct words passes. Labelled as necessary, not sufficient.
- Dataset size is small (64; 9 to 23 per task). Intervals in the reports show how wide the uncertainty is.

## 5. How to review (about 30 minutes)
Open `dataset/cases_v2.jsonl`; filter `label_status` in (`ambiguous`, `policy`) first (23 cases). For each, check whether the listed acceptable answers are right; reply with case ids and the change you want. Changes would be made as v3 through a patch list with reasons, never by editing v2 in place.
