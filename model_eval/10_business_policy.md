# 10. Final business policy decisions: what was applied, what was resolved, what is still open

Date: 2026-11-07. Zero-cost restrictions unchanged: no API calls, no keys, no spending, no installation, no live-model use; `ZERO_COST_LOCK.md` is in place. Datasets **v1 (56), v2 (64), v3 (65) are preserved unchanged**; **v4 (68) is derived** and justified below. Frozen baseline preserved (see section 7). No new feature, queue or service was built.

## 1. Confidence thresholds (employee count and region): a business-policy setting
**0.6 is a configurable business-policy threshold. It is not statistically validated** (there is no data in this project from which to validate it; the simulated providers happen to report about 0.9). It is retained provisionally by the owner's decision. Set it with `GTM_HARD_CONSTRAINT_MIN_CONFIDENCE` (0 to 1; other values raise an error), default in `config.Settings.hard_constraint_min_confidence`.

One rule, applied identically to both mandatory facts, in `gtm/agents/intake.py: apply_hard_constraints`:

| Evidence | Effect on qualification | Human verification |
|---|---|---|
| Confidence at or above the threshold | The rule may influence qualification: a breach (under 50 employees; region not EMEA/NA/APAC) caps the band at `low` | not requested |
| Confidence below the threshold | **No automatic downgrade** | requested (`evidence_needed`) |
| Confidence missing | Treated as low confidence: as above | requested |
| Value unknown | Nothing to decide on; no downgrade | requested (mandatory criterion unverified) |

`evidence_needed` carries field, value, confidence, `would_have_applied` and a reason. It appears in the lead's fit rationale, in the rationale text, and in an audit event `lead.evidence_needed`. Nothing is rejected silently. The verification request is visible information for the human reviewer; a queue or an enrichment request was **not** built. Changes from the previous version: region now follows the same rule (it used to apply at any confidence), and a low-confidence value that would *not* breach, and unknown values, are now also flagged rather than ignored.

## 2. Account-routing policy: where each rule stands in the implementation
"Implemented" means present in code and covered by a test or scenario; "gap" means the policy is not fully realised and **was deliberately not built** (no new features).

| # | Policy | Status | Where / evidence |
|---|---|---|---|
| 1 | Explicit promotional opt-out: suppress promotional outreach immediately | **Implemented, with a gap** | The reply router detects the opt-out first, before any model call, and writes an address-level suppression; the gateway re-reads suppression under lock before any send. **Gap:** suppression blocks *every* system-sent message to that address. That is safe today because every system-sent message is a sales message. The system has no transactional/service message class and no promotional-only suppression scope; service obligations are handled by humans outside the gateway. After an opt-out the account agent flags the owner (so a human can honour any service obligation). A marketing opt-out is **not** treated as permission to ignore service obligations: evaluation labels allow human tasks after an opt-out and forbid only drafts and CRM creation |
| 2 | Customer question: route to a human sales rep | Implemented | The account agent recommends a task for the owner (`recommend_task`) or a human touch; evaluation requires one of them (`A-question`) |
| 3 | Not now: record objection and timing; no automatic follow-up | **Implemented, with a gap** | Records the reply in the agent fields and creates a human task; no draft. **Gap:** the mock does not extract timing context ("next quarter") |
| 4 | Meeting request: prioritise human sales follow-up | **Implemented, with a gap** | A booked meeting creates a preparation task for the owner. **Gap:** there is no priority field, so "prioritise" is only a human task |
| 5 | Support issue: route to support / customer-success owner | **Gap (not built)** | There is no support class or owner mapping. The mock triages a billing query as `genuine`, which would send it into sales qualification: measured as a failure on `T-ambig-existing-customer` |
| 6 | Stalled opportunity: flag for human review; never change stage automatically | Implemented | Flag + human-touch/task only; deal stage can change only through an approved proposal |
| 7 | Spam or phishing: hold for review, never silently archive | **Implemented; mock detection is weak** | **Changed in this round:** spam is now held at any confidence and for any sender (previously only at confidence 0.8 or more from an unknown sender). Held leads keep their row and can be released by a human. The *mock's* detection misses phishing without spam keywords (`T-phish-verify`), a measured failure |
| 8 | Unclear intent: require human review | Implemented (changed this round) | **Changed:** `unclear` triage now holds the lead for human review; before, it went on to qualification. Replies with unclear intent already produced a human-review task |

Production code changed for the policy: `apply_hard_constraints` (region, low-confidence, unknown handling), the new `triage_gate` (unclear and spam held), the configurable threshold. The evaluation scorer calls the same functions rather than copies.

## 3. The nine split decisions
Rule applied: change a label only where the policy gives an unambiguous answer; leave the rest contested. Details with mock before/after are in `dataset/label_policy_changes.json`.

| Case | Status after policy | Which rule | What it means |
|---|---|---|---|
| A-not-now | **Resolved** | 3 | Record only; no draft (the reviewer's "a draft is acceptable" is superseded) |
| A-stalled | **Resolved** | 6 | Flag for human review; no_action and stage changes forbidden. A draft stays allowed (policy silent) |
| T-ambig-existing-customer | **Resolved** | 5 + 8 | A support query must not enter sales qualification; `unclear` (held for human review) is the only acceptable label. The routing to support is a known gap |
| Q-lowconf-region | **Partly resolved** | region policy | Flag region for verification, never reject: decided. Whether the route should be `qualified` (the reviewer's view): not decided, stays open |
| T-inj-system-notice | **Contested** | none | Spam and unclear are both held for review, so they are operationally the same; the policy does not choose a primary label |
| T-ambig-subcontract | **Contested** | none | Policy says unclear needs a human; it does not say whether this is genuine, unclear or vendor |
| Q-ambig-brochure | **Contested** | none | Policy silent on a "just browsing" request from a large company |
| Q-ambig-vague | **Contested** | none | Same |
| Q-inj-research | **Contested** | none | Policy silent; both labellers agree "high" is indefensible |

So **3 resolved, 1 partly resolved, 5 still contested**, which are marked `contested: true` in v4 and were not forced to agree.

## 4. v4: why it exists and every change
v4 exists because the policy gives unambiguous answers for several labels and adds new testable expectations. Changes (17 log entries; full text in `dataset/label_policy_changes.json`):
- Resolved split decisions: `A-not-now` (2 fields), `A-stalled` (2), `T-ambig-existing-customer` (2), `Q-lowconf-region` (1).
- **Policy supersedes two earlier reviewer-adopted (v3) labels:** `A-question` (route to a human, not "draft or human") and `A-unsubscribe` (human tasks after an opt-out are no longer forbidden, because a marketing opt-out does not cancel service obligations). Noted as policy overrides of the blind review.
- Verification expectations for unknown mandatory fields on `Q-missing-size-region`, `Q-missing-all`, `Q-low-student`.
- Three new cases: `Q-lowconf-region-unserved`, `Q-nocnf-tiny`, `Q-nocnf-region`.
- `must_hold` on 10 triage cases (spam/phishing, unclear-only, injection), checked with the **production gate**.
Mock effect: 59 of 65 cases passed under v3; **62 of 68 under v4**. Fails (6): `Q-off-service`, `R-html-noise`, `T-recruiter-subtle`, `T-phish-verify`, `T-inj-german`, and `T-ambig-existing-customer` (new, policy-driven: the billing query is not held).

## 5. What the policy checks now measure (mock only; not Claude)
Triage: **must-hold cases held 7 of 10** (misses: phishing without spam keywords, German injection, the billing query). No genuine enquiry was held. Qualify: routing correct 26 of 27; every low-confidence, missing-confidence and unknown mandatory field was flagged, none was used to hold a lead. Account routing: required action present 9 of 9, no forbidden action. These are measurements of a deterministic stand-in on 68 synthetic cases, nothing more.

## 6. Still open (owner)
Nothing blocks. Optional: human review of the 5 contested + 1 partly resolved cases; whether to build later (each a separate decision): a transactional/promotional message class (rule 1), a support route (5), timing extraction (3), a priority field (4), a verification queue or enrichment trigger (confidence policy).

## 7. Verification
See the addendum in `01_baseline_report.md`. Summary: frozen copies and the v1/v2/v3 dataset files verify unchanged; 28/28 scenarios with 0 regressions; full backend suite passes.
