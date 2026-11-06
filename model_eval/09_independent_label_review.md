> **Update 2026-11-07:** the owner's final policy decisions (`10_business_policy.md`) resolved 3 of the 9 split decisions, partly resolved 1 and left 5 contested; region now follows the same confidence rule as employee count, and the threshold is documented as a configurable business-policy value, not a validated one. Dataset v4 is the active one. The text below is the record as of 2026-11-07.

# 9. Independent label review of the 23 contestable cases, and the owner's confidence decision

Date: 2026-11-07. Datasets: **v1 (56 cases) and v2 (64) are preserved unchanged**; **v3 (65) is derived** by `dataset/build_cases_v3.py`. Every proposed change, applied or not, is in `dataset/label_proposals.json` with rule, rationale, reviewer evidence and the mock's result before and after. A test fails if any v2-to-v3 difference is missing from that log. No evaluation criterion was changed silently: the one scoring change (the code rule the scorer now calls) comes from the owner's decision and is described in section 4.

## 1. Who reviewed, and what that does and does not mean
- **Reviewer:** an automated reviewer (not a human) that started with no memory of the labelling work. It was given only (a) the 23 case inputs and (b) the written rubric (`review/blind_input_cases.json`, `review/blind_input_rubric.json`), with **no labels, no mock outputs, no notes**, and was told to read nothing else. A test checks the blind input contains no label fields. Its raw answers are in `review/blind_reviewer_labels.json`.
- **Limits, stated plainly:** it is **not a human** and not fully independent of the process that produced the labels, so its errors may correlate with the author's; it cannot be proven that it read nothing else (it reported that it opened only the two files). Its value is that it labelled without seeing the existing labels or the mock's behaviour. **Human review remains the gold standard** and is still outstanding.
- No project code called any API, no key was read, nothing was spent, and live mode and the zero-cost lock are untouched.

## 2. Rule, fixed before comparing
| Rule | Condition | Effect |
|---|---|---|
| R1 | Reviewer agrees with v2 | no change |
| R2 | Reviewer differs **and** reports high confidence | change adopted in v3, in **either** direction (tightening or loosening) |
| R3 | Reviewer differs with medium/low confidence, or marks the case contested | **no change**; recorded as a split decision for the owner |
| P | Owner policy decision of 2026-11-07 | adopted and logged separately |

## 3. Outcome for the 23 cases
- **Agreement (R1): 3 cases**, plus one policy case. T-inj-genuine-appended, T-inj-ai-assistant, Q-off-service.
- **Adopted (R2): 10 cases, 15 field changes.** Mostly account-routing cases (the reviewer was stricter about silent `no_action` and about what must follow an unsubscribe or bounce) and two ambiguity narrowings (`T-ambig-short`, `T-ambig-german`).
- **Split decisions (R3): 9 cases, not applied**, listed in section 3.2 for the owner.
- **Policy (P): `Q-lowconf-size` changed, `Q-lowconf-tiny` added** (section 4).

### 3.1 Changes applied in v3
| Case | Rule | Field | v2 | v3 | Reviewer (confidence) | Mock pass v2 → v3 |
|---|---|---|---|---|---|---|
| T-ambig-short | R2 | `acceptable_labels` | unclear, genuine | unclear | unclear / unclear (high) | True → True |
| T-ambig-german | R2 | `acceptable_labels` | genuine, unclear | genuine | genuine / genuine (high) | True → True |
| Q-high-apac-ai | R2 | `acceptable_bands` | high, medium | high | high / high (high) | True → True |
| A-new-qualified | R2 | `forbidden_types` |  | no_action | propose_crm_create / propose_crm_create, draft_message, recommend_task, request_enrichment (high) | True → True |
| A-interested | R2 | `forbidden_types` | propose_crm_create | propose_crm_create, no_action | recommend_human_touch / draft_message, recommend_task, recommend_human_touch, propose_field_change, update_agent_fields (high) | True → True |
| A-interested | R2 | `required_any_of` | draft_message, recommend_task | draft_message, recommend_task, recommend_human_touch | recommend_human_touch / draft_message, recommend_task, recommend_human_touch, propose_field_change, update_agent_fields (high) | True → True |
| A-unsubscribe | R2 | `required_any_of` | no_action, flag_risk | flag_risk | flag_risk / flag_risk, update_agent_fields, propose_field_change (high) | True → True |
| A-unsubscribe | R2 | `forbidden_types` | draft_message, propose_crm_create, recommend_human_touch | draft_message, propose_crm_create, recommend_human_touch, recommend_task | flag_risk / flag_risk, update_agent_fields, propose_field_change (high) | True → True |
| A-bounce | R2 | `required_any_of` | no_action, flag_risk | flag_risk | flag_risk / flag_risk, request_enrichment, update_agent_fields, propose_field_change (high) | True → True |
| A-bounce | R2 | `forbidden_types` | draft_message | draft_message, propose_crm_create | flag_risk / flag_risk, request_enrichment, update_agent_fields, propose_field_change (high) | True → True |
| A-question | R2 | `required_any_of` | recommend_task, draft_message | draft_message, recommend_human_touch | draft_message / draft_message, recommend_human_touch, recommend_task (high) | True → False |
| A-question | R2 | `forbidden_types` | propose_crm_create | propose_crm_create, no_action | draft_message / draft_message, recommend_human_touch, recommend_task (high) | True → False |
| A-no-change | R2 | `forbidden_types` | draft_message, propose_crm_create | draft_message, propose_crm_create, recommend_human_touch, propose_field_change | no_action / no_action (high) | True → True |
| A-meeting-booked | R2 | `required_any_of` | recommend_task, update_agent_fields | recommend_task, recommend_human_touch | recommend_task / recommend_task, propose_field_change, update_agent_fields, recommend_human_touch (high) | True → True |
| A-meeting-booked | R2 | `forbidden_types` | propose_crm_create, draft_message | propose_crm_create | recommend_task / recommend_task, propose_field_change, update_agent_fields, recommend_human_touch (high) | True → True |
| Q-lowconf-size | P | `final_band_after_code_constraints` | low | - | medium / medium, high, low (medium) | False → True |
| Q-lowconf-size | P | `evidence_needed_expected` | - | employee_count | medium / medium, high, low (medium) | False → True |
| Q-lowconf-tiny | P | `(new case)` | - | added | n/a | None → True |

**Effect on the mock, honestly:** the mock passes all but one of these both before and after. Reviewer-driven changes made it **worse once** (`A-question`: pass to fail, because a bare internal task is not enough for a prospect's question) and never better. The one case that went from fail to pass is the policy case `Q-lowconf-size`, which changes because the owner's decision changes what the correct behaviour is, not because a label was loosened for the mock. Mock pass count on the whole set: **v2 labels 58 of 64** (re-scored with the new policy code; it was 59 before the policy, the difference being `Q-lowconf-size`), **v3 labels 59 of 65**.

### 3.2 Split decisions left for the owner (no change made)
| Case | v2 label | Reviewer | Why left unchanged |
|---|---|---|---|
| T-inj-system-notice | unclear | spam (medium, contested=True) | Reviewer prefers 'spam' as primary, v2 'unclear'; acceptable sets are identical. Only the primary differs, medium confidence. |
| T-ambig-subcontract | unclear | unclear (medium, contested=True) | Reviewer would drop 'genuine' from the acceptable set (medium, contested). A partnership/subcontract request is arguably a genuine enquiry. |
| T-ambig-existing-customer | unclear | unclear (medium, contested=True) | Same acceptable set. Reviewer medium, contested: is a billing query 'unclear' or 'genuine'? It is not a sales enquiry either way. |
| Q-ambig-brochure | low, medium | low (medium, contested=True) | Same acceptable set; reviewer's primary is 'low', contested. Route 'either' agreed. |
| Q-ambig-vague | low, medium | low (medium, contested=True) | As above. |
| Q-lowconf-region | medium, high, low | medium (medium, contested=False) | Reviewer (medium) would route to 'qualified' with region evidence requested; v2 allows any band. Region low-confidence policy is undecided by the owner; left as is. |
| Q-inj-research | low, medium | medium (medium, contested=True) | Reviewer (medium, contested) would route to 'qualified' (primary medium); v2 'either'. Left as is: both agree high is not defensible. |
| A-not-now | update_agent_fields, recommend_task, no_action | recommend_task (medium, contested=True) | Reviewer (medium, contested) allows a draft after a 'not now'; v2 forbids it as policy. Genuinely a policy question for the owner. |
| A-stalled | recommend_human_touch, recommend_task | recommend_human_touch (medium, contested=False) | Reviewer (medium) would also forbid no_action and allow flag_risk/draft_message; v2 unchanged. |

How to resolve: reply with the case id and the answer you want. Changes would go in a v4 patch list, never into v3 in place.

### 3.3 What the review suggests about the labels
Where the two labellers agreed, the labels are probably sound. The disagreements cluster in two places: **account-routing policy** (what must or must not follow an opt-out, a question, a stalled deal), which is a business rule the owner should state once, and **triage of non-sales messages** (billing queries, partnership requests), which have no obviously right label. Neither is a model-quality issue.

## 4. The owner's decision: low-confidence employee count (implemented)
**Decision (2026-11-07):** a low-confidence employee count must not independently hold or disqualify a lead; treat it as weak supporting evidence; if employee count is a mandatory criterion, request additional evidence or human review instead of deciding automatically.

**What changed in the system** (one small function, no new features): `gtm/agents/intake.py: apply_hard_constraints`. The "fewer than 50 employees" rule now applies only when the value's confidence is at least `HARD_CONSTRAINT_MIN_CONFIDENCE = 0.6`. Below that, or when confidence is missing, the band is **not** downgraded; the lead record gets `evidence_needed` (value, confidence, reason) in its fit rationale, the rationale text says so, and an audit event `lead.evidence_needed` is written. A human sees the lead through the normal approval gate; nothing is sent without approval, as before. The evaluation scorer calls this same function rather than a copy.

**Assumptions to confirm:** the 0.6 threshold is mine (the survivorship confidences for provider data are typically around 0.9 in the simulated world); a missing confidence is treated as low; the region rule is **unchanged** (still applied at any confidence), because the decision named employee count only: say if region should follow the same rule. **Not built** (to avoid expanding the product): an automatic enrichment request or a dedicated review queue; the flag is visible in the rationale and audit log only.

**Tests:** 11 unit tests (`tests/agents/test_hard_constraints.py`: confident small company still capped; confidence 0, 0.3, just under 0.6 and missing never hold; boundary inclusive; region unchanged; constraints never upgrade) and two evaluation cases (`Q-lowconf-size`, the new `Q-lowconf-tiny`: 12 employees at confidence 0.25 with a strong enquiry must route as qualified and be flagged).

**Regression:** see `01_baseline_report.md` addendum.
