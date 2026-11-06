# Frontend API specification

What the UI expects from `/api/*` when `VITE_API_MODE=http`. TypeScript source of truth: `src/api/types.ts` (mirrors
`backend/gtm/contracts/api.py` where that file defines a DTO). The mock backend (`src/api/mock/`) produces exactly these shapes.

Conventions
- JSON, **snake_case**. Timestamps: ISO-8601 UTC strings (`2026-03-09T09:00:00Z`) on the **simulated clock**.
- Errors: non-2xx with FastAPI-style `{"detail": "message"}`; the UI shows `detail`. Used codes: 404 unknown id, 409 conflict (e.g. proposal not decidable, blocked by dependency), 422 validation.
- `data_origin(s)`: one of `GT SIM SCR MOD HUM-sim HUM-real PLT` (`gtm.contracts.provenance.DataOrigin` values).
- `evidence_basis`: `measured_on_simulation | machinery_check | modelled_impact`.
- Nullable means the key is always present with `null`.
- Lists are returned bare (no envelope). Lists are expected newest first where it matters (`/audit`, `/events`, `/proposals`, `/leads`, `/runs`).

Endpoints from `contracts/api.py` ENDPOINTS: `HealthOut`, `ConfigOut`, `DecisionIn`, `ProposalOut`, `AuditRow`, `AuditVerifyOut`, `DemoResultOut` are used exactly as defined there. Extra detail the UI needs inside `ProposalOut` (typed dict fields) is specified below. **DTOs the contract file does not define** are marked NEW.

## Demo ids (scripted)
`POST /api/demo/enquiry` body `{"enquiry_id": "S01-golden-enquiry"}` and `POST /api/demo/reply` body `{"reply_id": "S01-golden-reply"}`. If the backend scenario library uses other ids, change `GOLDEN_ENQUIRY_ID` / `GOLDEN_REPLY_ID` in `src/api/client.ts`. Demo actions must be idempotent (return `ok:false` with a message instead of an error when repeated). `POST /api/demo/advance` body `{"seconds": 86400}`. UI reads `message`, `ok`, `clock`.

## GET /api/health, /api/config
```json
{"ok": true, "db": true, "clock": "2026-03-09T09:00:00Z"}
{"llm_mode": "mock", "live_enabled": false, "data_notice": "All data is synthetic. ..."}
```

## GET /api/overview  (NEW: OverviewOut)
```json
{
  "clock": "2026-03-09T09:00:00Z",
  "counts": {"leads": 4, "accounts": 4, "open_proposals": 3, "runs": 5, "alerts": 1, "audit_events": 22},
  "golden_thread": [
    {"key": "enquiry", "label": "Enquiry received", "done": true, "detail": "Lead #101"}
  ],
  "recent_activity": [{"at": "2026-03-09T09:00:00Z", "text": "proposal.created (agent:account)", "ref": "proposal:301"}]
}
```
`golden_thread` is an ordered list of exactly these keys (labels free text; `detail` null when not done):
`enquiry, triage, account, agent, crm, send, reply, intel`. `open_proposals` counts status in `pending|blocked|parked`.

## GET /api/leads  (NEW: LeadOut[])
```json
{
  "id": 101, "received_at": "2026-03-09T09:00:00Z", "name": "Priya Raman", "email": "priya.raman@harbourline.example",
  "company": "Harbourline Freight Group", "message": "We run 14 regional freight hubs ...",
  "triage_class": "real_lead",
  "fit_score": 0.86, "fit_band": "high",
  "status": "qualified", "held": false, "held_reason": null,
  "account_id": 201, "service_line": "Data platform", "data_origins": ["SCR", "MOD"]
}
```
- `triage_class`: `real_lead | existing_customer | vendor | recruiter | spam | unclear | null`
- `fit_band`: `high | medium | low | null`; `fit_score` 0..1 or null
- `status`: `new | triaged | held | qualified | disqualified | nurture | converted`
- Held items (`held: true`) must carry `held_reason` (shown to the reader; held items are reversible, never deleted).

## GET /api/accounts  (AccountRow[])
```json
{
  "id": 201, "name": "Harbourline Freight Group", "domain": "harbourline.example", "industry": "Freight and logistics",
  "employees": 1150, "lifecycle": "active", "owner": "Maya Okafor", "open_proposals": 2,
  "last_interaction_at": "2026-03-09T09:00:00Z", "fit_band": "high", "data_origins": ["SCR", "SIM", "MOD"]
}
```
`lifecycle`: `unprovisioned | active | quiet | dormant | needs_attention | archived` (docs/account-agents.md section 3).

## GET /api/accounts/{id}  (NEW: AccountDetail = AccountRow +)
```json
{
  "...AccountRow fields": "...",
  "fields": [
    {
      "key": "employees", "label": "Employees", "value": 1150, "owner": "provider",
      "source": "orgdata (simulated)", "confidence": 0.7, "as_of": "2026-01-06T09:00:00Z",
      "freshness_days": 62, "freshness": "aging", "conflict": true,
      "alternatives": [{"source": "firmo (simulated)", "value": 840, "confidence": 0.55, "as_of": "2025-08-31T09:00:00Z"}],
      "data_origin": "SIM"
    },
    {"key": "ai_next_step", "label": "AI suggested next step", "value": "Reply within one business day...", "owner": "agent",
     "source": "account agent (mock model)", "confidence": 0.81, "as_of": "2026-03-09T09:00:00Z", "freshness_days": 0,
     "freshness": "fresh", "conflict": false, "alternatives": [], "data_origin": "MOD"}
  ],
  "agent_state": {
    "lifecycle": "active", "version": 2, "updated_at": "2026-03-09T15:00:00Z", "mode": "mock",
    "summary": "...", "summary_refs": ["lead:101", "reply:S01-golden-reply"],
    "stakeholders": [{"name": "Priya Raman", "role": "VP Operations", "stance": "champion", "source_ref": "lead:101"}],
    "risks": [{"text": "...", "severity": "medium", "refs": ["lead:101"]}],
    "commitments": [{"party": "Priya Raman", "text": "...", "due": "2026-03-12", "status": "open", "refs": ["reply:..."]}],
    "open_questions": ["Who owns the budget?"],
    "next_actions": [{"id": 3, "action": "recommend_task", "text": "...", "status": "pending_approval", "proposal_id": 303, "rationale": "..."}],
    "last_decision": {"action": "recommend_task", "confidence": 0.84, "would_change_mind": "..."}
  },
  "interactions": [{"id": 7002, "at": "...", "kind": "email_in", "summary": "Customer reply received", "detail": "full text or null", "ref": "reply:S01-golden-reply", "data_origin": "SCR"}],
  "proposals": ["ProposalOut ..."],
  "opportunities": ["OpportunityRow ..."]
}
```
- `fields[].owner`: `provider | human | agent | system`. **Agent-owned fields are exactly the `ai_*` keys and must have `owner: "agent"`**; the UI labels them "AI-written". Human-owned fields (`owner: "human"`) are labelled; the UI never lets the agent change them.
- `freshness`: `fresh` (<=30d) `| aging` (<=120d) `| stale`, `freshness_days` relative to the simulated clock.
- `conflict: true` requires non-empty `alternatives` (providers differing by >20%).
- `agent_state` may be `null` (not provisioned). `agent_state.mode`: `mock | replay | live`. `stakeholders[].stance`: `champion | neutral | unknown | blocker`. `commitments[].status`: `open | proposed | done`. `next_actions[].status`: `proposed | pending_approval | done | dismissed`. `interactions` newest first; `kind`: `enquiry | email_out | email_in | crm | agent | system | human`. `risks[].severity`: `low | medium | high`.

## GET /api/opportunities  (NEW: OpportunityRow[])
```json
{"id": 501, "account_id": 201, "account_name": "Harbourline Freight Group", "name": "Harbourline - data platform scoping",
 "stage": "Qualified", "amount": null, "currency": "EUR", "owner": "Maya Okafor", "days_in_stage": 0, "status": "open", "data_origin": "SIM"}
```

## GET /api/pipeline/alerts  (NEW: PipelineAlert[])
```json
{"id": 1, "opportunity_id": 11, "opportunity_name": "Data platform assessment", "account_id": 1, "account_name": "Meridian Biologics",
 "severity": "high", "kind": "stalled", "days_stalled": 52,
 "reasons": ["52 days in Proposal; the stall threshold is 45 days.", "No customer reply for 31 days."],
 "recommendation": "Call the new finance lead ...", "raised_at": "2026-03-02T09:00:00Z", "data_origin": "PLT"}
```
`severity`: `low|medium|high`. `kind`: `stalled | no_reply | no_next_step | champion_change`.

## GET /api/proposals?status=   and  GET /api/proposals/{id}  (ProposalOut)
Per `contracts/api.py`. Detail the UI relies on:
```json
{
  "id": 302, "type": "message", "gate_id": "G5", "status": "blocked",
  "account_id": 201, "account_name": "Harbourline Freight Group",
  "payload": {"...": "type specific, see below"},
  "payload_hash": "<sha256 hex, gtm.contracts.proposals.payload_hash>",
  "evidence": [{"kind": "enquiry", "ref": "lead:101", "text": "...", "source": "website form", "data_origin": "SCR"}],
  "rationale": "...", "confidence": 0.81, "required_role": "AE",
  "created_at": "...", "expires_at": "...",
  "depends_on": 301, "block_reason": "Waiting for proposal #301 ...",
  "decisions": [{"decision": "approve", "decided_by": "user:maya", "at": "...", "reason_code": null, "comment": null,
                 "edited": false, "old_hash": null, "new_hash": null}],
  "execution": null,
  "data_origins": ["MOD", "SCR", "GT"]
}
```
- `status`: `pending approved approved_edited rejected expired superseded executing parked blocked executed failed`.
- **Dependency**: `depends_on` = id of the proposal that must be `executed` first. While it is not, the dependent has `status: "blocked"`, `execution: null`, and a `block_reason`. When the dependency executes the backend sets the dependent to `pending` (clears `block_reason`); if the dependency is rejected the dependent becomes `superseded` with a `block_reason`. `POST decision` on a dependent whose dependency is not `executed` returns **409**.
- A **soft block from the gateway** (`status: "blocked"` and `execution.block_kind: "soft"`) can be decided again (the UI offers edit-and-approve / reject). Hard blocks are terminal.
- `payload` for `type: "message"` = `MessagePayload` (channel, contact_id, resolved_recipient, sender_identity, subject, body, links, attachments, claims[{text, source_ref|null}], thread_id, experiment_id, variant_id, design_hash). `claims[].source_ref == null` renders as "unsupported claim".
- `payload` for `crm_write` = `CrmWritePayload` (`operations[{object, action, local_ref{type,id}, properties}]`). Other types are rendered as a generic key/value list (task: owner, title, detail, due_at; field_change; lead_disposition; match; ...).
- `decisions[].old_hash/new_hash/old_payload`: set on `approve_with_edits` (hash before/after edit, and the complete payload before the edit; the UI renders a diff of `old_payload` vs the current `payload`. Without `old_payload` it shows the hashes only). After an edit `payload_hash` is the **new** hash and `payload` the edited payload.
- `execution` (NEW typed object, null until a decision reaches the gateway):
```json
{
  "status": "executed", "adapter": "outreach.send", "idempotency_key": "exec:302:ab12...",
  "executed_at": "2026-03-09T09:00:00Z", "outcome": "Message handed to the simulated outreach provider ...",
  "hash_verified": true, "approval_consumed": true, "block_kind": null, "external_ref": "sim-msg-302",
  "checks": [{"step": 1, "name": "Approval valid (role, expiry, hash match, unconsumed)", "status": "passed", "detail": "..."}]
}
```
`execution.status`: `executed | blocked | failed | parked | executing`. `block_kind`: `soft | hard | null`. `checks[].step` is 1..13 from docs/execution-architecture.md 13.2; `status`: `passed | failed | skipped` (skipped = not applicable or not reached). Return all 13 entries.
- Decision request (`DecisionIn`): reject **requires** `reason_code` (422 otherwise); `approve_with_edits` requires `edited_payload` (the **complete** replacement payload). The response is the updated `ProposalOut`, already including `execution` (gateway runs synchronously in the demo).
- Reason codes the UI sends: reject `wrong_recipient inaccurate_claim tone not_ready duplicate policy other`; edit `fact_fix tone_edit removed_claim other`. `decided_by` is `user:maya`.

## GET /api/runs  (NEW: RunRow[])  and GET /api/runs/{id}  (NEW: RunDetail = RunRow + steps)
```json
{
  "id": 403, "workflow": "inbound_enquiry", "status": "waiting", "trigger": "event:lead.received",
  "account_id": 201, "account_name": "Harbourline Freight Group",
  "started_at": "...", "finished_at": null, "steps_total": 11, "steps_done": 9, "cost_usd": 0.0,
  "steps": [
    {
      "id": 9005, "seq": 5, "node": "enrich_orgdata", "node_type": "tool", "status": "succeeded", "attempts": 2,
      "started_at": "...", "finished_at": "...",
      "error": {"class": "RetryableError", "message": "429 rate limit on attempt 1; retried"},
      "parked_until": null, "waiting_for": null, "cost_usd": 0.0, "sim_units": 3, "model_mode": null, "note": "..."
    }
  ]
}
```
- `RunRow.status`: `running | succeeded | failed | parked | waiting | dead_letter`. `account_id/account_name` nullable.
- `node_type`: `trigger code tool llm agent conditional map reduce wait approval`. `RunStep.status`: `succeeded failed parked waiting running skipped dead_letter`.
- `error` is the **last** error even when the step later succeeded (shows retry history). `parked_until` set when status `parked`. `waiting_for` like `approval:301` (UI links `approval:<id>` to the proposal). `model_mode` set on `llm`/`agent` nodes (`mock|replay|live`). `cost_usd` is model money; `sim_units` is simulated provider units, **never money**.
- The list endpoint omits `steps`.

## GET /api/audit?limit=  (AuditRow[]), GET /api/audit/verify  (AuditVerifyOut), GET /api/events?limit=  (NEW: EventRow[])
Audit per contract (newest first). Verify: `{"ok": true, "checked": 22, "first_bad_seq": null}` or `{"ok": false, "checked": 2, "first_bad_seq": 3}`.
```json
{"id": 31, "at": "...", "event_type": "lead.received", "entity_ref": "lead:101", "source": "system", "dedupe_key": "lead:101"}
```

## GET /api/evals and POST /api/evals/run  (NEW: EvalSummaryOut)
```json
{
  "run_id": 1, "ran_at": "...", "mode": "mock", "notice": "free text; UI also shows its own honest statement",
  "totals": {"passed": 7, "failed": 1, "total": 8},
  "invariants": [{"name": "audit_chain_verifies", "passed": true, "violations": []}],
  "scenarios": [
    {
      "id": "S06", "title": "Spam / vendor / recruiter hold", "description": "...", "passed": true,
      "evidence_basis": "measured_on_simulation", "data_origins": ["GT", "MOD"],
      "metrics": [{"name": "Held-item precision", "value": 0.97, "target": ">= 0.95", "unit": "ratio", "passed": true, "evidence_basis": "measured_on_simulation"}],
      "detail": "free text or null"
    }
  ],
  "baseline": {"compared": true, "regressions": 0}
}
```
`metrics[].value/target` may be number or string; `passed` null for modelled/illustrative metrics. Every scenario and metric must carry `evidence_basis` (gtm/eval).

## GET /api/feedback  (NEW: FeedbackRow[])
```json
{"id": 1, "kind": "lost_deal_review", "created_at": "...", "account_id": 2, "account_name": "Aldous & Pryce LLP",
 "summary": "Lost to an incumbent advisory firm ...",
 "quotes": [{"text": "verbatim, unedited", "speaker": "Managing partner (scripted)", "source_ref": "interaction:9001"}],
 "tags_human": ["incumbent"], "tags_ai_suggested": ["panel-agreement"], "reason_code": "lost_to_incumbent",
 "created_by": "user:maya", "data_origin": "SCR"}
```
`kind`: `lost_deal_review | reviewer_edit | customer_reply | win_note`. Human and AI-suggested tags are always separate arrays.

## POST /api/lost-deal-reviews  (NEW: LostDealReviewIn -> LostDealReviewOut)
```json
{"account_id": 2, "opportunity_id": null, "reason_code": "lost_to_incumbent", "primary_reason": "free text",
 "competitor": null, "could_we_have_won": "maybe", "what_would_change_it": "free text",
 "verbatim_quotes": ["exact words"], "reviewer": "user:maya"}
```
Response: `{"id": 12, "feedback_id": 12, "created_at": "...", "ok": true}`. `reason_code` is one of `lost_to_incumbent lost_to_competitor price_budget timing no_decision scope_fit champion_left other`. The review must then appear in `GET /api/feedback`.

## POST /api/demo/*  (DemoResultOut)
`{"ok": true, "message": "Enquiry submitted ...", "clock": "...", "created": {"lead_id": 101, "account_id": 201, "proposal_ids": [301, 302]}}`.
Expected backend behaviour for the golden thread (the UI hints assume proposal ids 301 CRM create, 302 intro reply `depends_on` 301, third proposal = owner task after the reply; ids may differ, the UI never hard-codes them except in hint text on the Demo page).
