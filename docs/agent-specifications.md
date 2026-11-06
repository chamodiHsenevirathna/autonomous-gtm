# Agent and workflow-node specifications

**Modified (Phase 3):** replaces the earlier stub. Design only, **[P]**. "Agent" is used loosely in the brief; here each unit is specified with its true technique (code, LLM call or agent loop) per [orchestration.md](orchestration.md) section 3. Budgets and thresholds are **[A]** starting values.

## 1. Specification template

Every unit defines: purpose · trigger · technique · inputs · tools (via MCP profile) · outputs · autonomy and gate · failure modes · evaluation · budget.

## 2. Units

### U1 Intake and entity resolution (code)
- **Purpose:** normalise an enquiry, deduplicate, link or create contact/account candidates.
- **Trigger:** `lead.received`. **Technique:** code. **Inputs:** raw payload. **Tools:** direct service calls (not MCP).
- **Outputs:** lead record; link, or match proposal for ambiguous cases.
- **Autonomy:** automatic link on exact keys; everything else a proposal.
- **Failures:** malformed payload (reject with reason), duplicate event (dropped by idempotency key).
- **Evaluation:** ER precision/recall on labelled pairs; zero duplicate creations on replayed events. **Budget:** no LLM cost.

### U2 Triage classifier (LLM)
- **Purpose:** label genuine / vendor / recruiter / spam / unclear.
- **Technique:** one LLM call, small model, structured output. **Inputs:** enquiry text only (treated as untrusted).
- **Autonomy:** auto-archive only for spam above a high confidence; sampled for audit. Everything else continues.
- **Failures:** injection attempts in text (must not change behaviour), over-confident spam labels.
- **Evaluation:** confusion matrix vs labels, including adversarial injection cases. **Budget:** under ~$0.002 per lead **[A]**.

### U3 Enrichment waterfall (code + tools)
- **Purpose:** gather and resolve account and contact fields from first-party data and providers.
- **Trigger:** called by workflows; `enrichment.requested` from agents. **Technique:** map/reduce over provider tools plus deterministic survivorship.
- **Outputs:** observations with provenance; resolved fields; conflict flags; cost spent.
- **Autonomy:** automatic within a cost cap.
- **Failures:** provider 429 or timeout (retry, then skip and mark unknown), conflicting values (flag), cost cap reached (stop, report gaps).
- **Evaluation:** per-provider and combined field accuracy against ground truth; cost per correct field; calibration of confidence. **Budget:** simulated cost units per run (cap configurable).

### U4 Research agent (agent loop)
- **Purpose:** produce a source-linked brief on a company/contact when the needed facts are not in structured sources.
- **Trigger:** inbound fit uncertain or outbound dossier requested. **Technique:** bounded tool loop. **Inputs:** entity ids, question list.
- **Tools:** `gtm-read` (subset), `search_web_sim`, `fetch_page_sim`, `request_enrichment`. No write tools except returning a brief.
- **Outputs:** brief with claims, each linked to a source or marked unknown; confidence; list of unanswered questions.
- **Autonomy:** produces information only; internal.
- **Failures:** hallucinated facts, prompt injection in fetched pages, runaway loops (step and cost caps), stale sources.
- **Evaluation:** claim-level factuality against ground truth; injection resilience; steps and cost. **Budget:** max 8 tool calls, ~$0.05 per brief **[A]**.

### U5 Qualification and routing (LLM + code)
- **Purpose:** score fit against the ICP rubric and recommend an owner.
- **Technique:** code applies hard constraints (region served, minimum size); one LLM call scores soft criteria with a rationale; code applies routing rules.
- **Autonomy:** recommendation only (proposal), except where spam rules already archived.
- **Failures:** wrong disqualification (largest risk), rubric drift, routing conflicts.
- **Evaluation:** accuracy, precision/recall of "qualified" against labelled set, with false negatives reported separately. **Budget:** ~$0.01 per lead **[A]**.

### U6 Account agent (LLM, optional agent loop later)
- **Purpose:** maintain account state; recommend next actions.
- **Trigger:** events and heartbeat via change detector. **Technique:** one LLM call over a context pack; action menu output ([account-agents.md](account-agents.md) section 7).
- **Tools:** `gtm-read` (account scope), `gtm-propose` (proposals, `ai_*` fields, state patch, enrichment request, draft creation). No execution tools.
- **Autonomy:** may write agent-owned fields and its state; all else is a proposal.
- **Failures:** acting when nothing should be done, repeating rejected advice, drifting summary, wrong facts in drafts.
- **Evaluation:** acceptance rate, `no_action` precision, recommendation rubric score, factuality of evidence references. **Budget:** per wake and per account per day caps.

### U7 Pipeline monitor (code + LLM)
- **Purpose:** detect stalled/at-risk deals and hygiene issues; write the weekly digest.
- **Technique:** SQL rules (stall flags, dwell, single-threading, missing fields), LLM for risk explanation and commentary over computed numbers.
- **Autonomy:** sets system-owned flags directly; field fixes and tasks are proposals.
- **Failures:** noisy flags, stale CRM giving false alerts, numbers misquoted (prevented by passing numbers as data and verifying output against them).
- **Evaluation:** precision/recall vs seeded stalled deals; digest numeric accuracy 100%. **Budget:** low, mostly code.

### U8 Meeting assistant (LLM)
- **Purpose:** meeting briefs (internal, read-only) and post-meeting summary, actions and follow-up draft.
- **Technique:** single LLM calls over context pack or transcript. **Autonomy:** brief needs no gate; everything that writes or sends is gated.
- **Failures:** missed action items, invented commitments, pricing/date content in drafts (screened by code).
- **Evaluation:** action-item recall/precision against labelled transcripts; commitment fidelity; zero commercial terms in drafts.

### U9 Reply classifier and router (code + LLM)
- **Purpose:** route replies; stop sequences; surface intent.
- **Technique:** rules first (bounce, unsubscribe, auto-reply), LLM for intent.
- **Autonomy:** automatic suppression and sequence stop (safe direction); everything else notifies the owner.
- **Evaluation:** routing accuracy; time-to-suppression; zero sends after unsubscribe.

### U10 Drafting skill (LLM, shared)
- **Purpose:** produce drafts for replies, follow-ups, outreach.
- **Technique:** single call with style guide and per-claim source references; code claim-checker and commercial-content screen.
- **Autonomy:** none; drafts only.

### U11 Execution gateway (code only)
- **Purpose:** perform human-approved actions after deterministic checks ([execution-architecture.md](execution-architecture.md)).
- **No model calls, no discretion.**
- **Evaluation:** property tests that no external effect occurs without a valid approval; all blocked cases return reasons.

## 3. Reusable skills **[P]**

Versioned files, not inline strings (NFR-MNT-01): ICP rubric; qualification rubric; routing rules; style guide and tone; claim-citation format; action menu schema; reply-intent taxonomy; commercial-content screen patterns; escalation policy. Each skill file has a version and changelog; runs record the versions used.

## 4. Context engineering rules **[P]**

1. Context assembled by code in priority order within a token budget (account-agents.md section 6).
2. Untrusted text (emails, web pages, transcripts) is wrapped and labelled as data, with instructions in the system prompt stating it must never be followed.
3. Stable content (rubrics, schemas) is placed first for caching; volatile content last.
4. Structured output with schema validation for every non-draft output.
5. "Unknown" and "no_action" are valid, encouraged outputs.
6. Context packs and model responses are stored by reference for replay.

## 5. Units added for the GTM product loop

Design only, **[P]**. These are LLM steps or code inside shared services, **not new standalone agents** (AD-11).

### U12 Feedback extractor (LLM)
- **Purpose:** extract feedback items from an interaction, transcript or lost-deal review.
- **Trigger:** `feedback-extract` workflow. **Technique:** one LLM call, small model, structured output; code verifies each quote exists in the source and attaches the segment snapshot.
- **Autonomy:** items are stored as *suggested*; low-confidence or sensitive sources go to a reviewer.
- **Failures:** invented or paraphrased quotes (rejected in code), over-extraction, misclassified kind, prompt injection in transcript text (treated as data).
- **Evaluation:** precision/recall, kind accuracy, pre-check hallucination rate, injection cases. **Budget:** ~$0.005 per interaction **[A]**.

### U13 Theme matcher (code + LLM)
- **Purpose:** assign new items to existing themes or propose candidate themes.
- **Technique:** code blocking by topic and trigram similarity; batched LLM comparison for ambiguous cases; deterministic count recomputation.
- **Autonomy:** proposes only; humans confirm (G11); human assignments override and are remembered.
- **Failures:** theme sprawl, over-merging, loud-account inflation (prevented by distinct-account counting).
- **Evaluation:** recall of planted themes, false-theme rate, singleton handling, run-to-run stability.

### U14 Experiment analyst (code + LLM)
- **Purpose:** compute results at analysis points and narrate caveats.
- **Technique:** statistics in code; rule-based recommendation; one LLM call for narrative that is checked against the computed numbers.
- **Autonomy:** none beyond writing result snapshots; decisions are G16.
- **Failures:** declaring winners on thin data (prevented by labels), narrative contradicting numbers (checked).
- **Evaluation:** A/A false-positive rate, detection of planted lifts, label correctness, numeric consistency of narratives.

Drafting for variants reuses U10. Backlog scoring is a code function. The insight digest is code for numbers plus one LLM narrative call.
