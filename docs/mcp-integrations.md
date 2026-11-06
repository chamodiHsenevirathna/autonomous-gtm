# MCP and integrations

**Modified (Phase 3):** replaces the earlier stub. Design only, **[P]**. Rationale for the server split is in [technology-decisions.md](technology-decisions.md) section 4. I have not verified MCP SDK specifics; implementation details are for a Phase 4 spike **[A]**.

## 1. Principles

1. MCP is the **permissioned tool surface for model-driven calls**. Deterministic nodes call the same underlying services directly.
2. **Split by risk:** a read server and a propose server. Agents never see an execution tool.
3. **Absence of capability is the control.** No tool exists to send, create CRM records, change human-owned fields, merge entities or delete anything.
4. Every call is scoped (principal, account), validated, logged to `tool_call` (including denied calls) and counted against run budgets.
5. Tool outputs containing external text are labelled as untrusted data.

## 2. Servers and tools

### `gtm-read` (read-only)

| Tool | Purpose | Scope |
|---|---|---|
| `get_account_context(account_id)` | Resolved fields with confidence/freshness, hierarchy, owner, open opportunities | Account |
| `get_context_pack(account_id)` | The assembled pack (agents normally receive this pre-built) | Account |
| `search_interactions(account_id, query, since?)` | Keyword/trigram search over interactions | Account |
| `get_opportunity(opportunity_id)` | Stage, history, contacts, activities | Account |
| `get_signals(account_id, active_only)` | Unexpired buying signals | Account |
| `get_suppression_status(contact_id)` | Whether outreach is blocked and why (read-only) | Contact |
| `get_feedback_digest(account_id)` | Prior human decisions | Account |
| `list_provider_status()` | Source registry, health, costs | Global |
| `search_web_sim(query)` / `fetch_page_sim(url)` | Synthetic web for the research agent; returns untrusted text | Research profile only |

### `gtm-propose` (writes limited to proposals, drafts, agent-owned data)

| Tool | Purpose | Restrictions |
|---|---|---|
| `create_proposal(type, target, payload, evidence, rationale, confidence)` | Request any gated change | Type must be in allowed list; validated; never executes |
| `create_draft(contact_id, purpose, content, sources)` | Store a draft in the outbox | Draft only; cannot send; claim-check and commercial screen run |
| `update_agent_fields(account_id, fields)` | Write `ai_*` fields | Field policy rejects anything else |
| `patch_agent_state(account_id, version, patch)` | Update persistent state | Optimistic lock; size caps |
| `request_enrichment(entity, fields, budget)` | Run the waterfall | Cost cap; rate-limited |
| `flag_risk(account_id, risk, evidence)` | Notify owner | Creates a notification, not a state change |

### Optional `crm-sim-mcp`
A standalone MCP server exposing the simulated CRM (search, get, list) read-only, to demonstrate the "governed access to a core revenue system" pattern referenced in the job postings (E1). It uses the same field policy and is for demonstration, not part of the core path.

### Explicitly absent
`send_email`, `send_message`, `create_contact`, `create_account`, `update_opportunity`, `merge_entities`, `delete_*`, `set_price`, `book_meeting`, `enrol_sequence`. These exist only inside the execution gateway, which is not MCP-exposed.

## 3. Permission profiles

| Profile | gtm-read | gtm-propose tools |
|---|---|---|
| research-agent | Subset (entity facts), web sim tools | `request_enrichment` |
| account-agent | Account-scoped all | all six |
| pipeline-monitor | Opportunity and activity reads | `create_proposal`, `flag_risk` |
| meeting-assistant | Account-scoped reads | `create_draft`, `create_proposal` |
| evaluation-harness | Everything, against simulators | n/a |

A call outside the profile or account scope is denied, logged, and counted as a safety metric (target: zero attempts in normal runs; adversarial scenarios intentionally provoke them).

## 4. Non-MCP integration boundaries

| Boundary | Protocol | Notes |
|---|---|---|
| App to CRM sim | REST (+ webhooks back) | Adapter interface identical for a real HubSpot adapter |
| App to provider sims | REST | Rate limits and faults injected |
| App to outreach/mail/calendar sims | REST + webhooks | Eventual consistency, scripted replies |
| Webhooks in | HTTP with idempotency key and signature check (simulated shared secret) | Optional n8n forwarder |
| Dashboard to backend | REST + server-sent events | Auth simplified for the demo; roles enforced |

## 5. Auditing MCP use

`tool_call` rows hold tool, arguments (redacted), result reference, permitted flag, latency and run id. Denied calls are first-class evidence for the safety evaluation.

## 6. Additions for the GTM product loop

Design only, **[P]**. Principle unchanged: agents get read tools and proposal tools, never decision or execution tools.

**Added to `gtm-read` (account-scoped):** `search_feedback(account_id, kind?, since?)` returns the account's feedback items with quotes (untrusted text, labelled as data); `get_experiment_membership(contact_id)` returns experiment id, variant and holdout status, read-only.

**Added proposal type** for `create_proposal`: `backlog_submission` (an agent may suggest a backlog item for human triage; it cannot set priority or status).

**Not exposed to agents:** the insight service's portfolio-read scope (cross-account aggregation), theme confirmation, backlog priority or status changes, and every experiment-control operation.

**Explicitly absent tools:** `launch_experiment`, `resume_experiment`, `update_experiment`, `assign_variant`, `change_allocation`, `expand_audience`, `confirm_theme`, `set_backlog_priority`, `close_lost_deal`. A red-team scenario (S42) attempts these and expects denial.

## 7. Review amendments

1. **Scope is bound to the run, not passed as an argument.** At run start the principal and account are bound to a run context. Any tool call with an id that does not resolve to that account is denied and logged as a denied call.
2. **Precise profiles.** research-agent: `get_account_context` (facts only, no interactions), `search_web_sim`, `fetch_page_sim`, `request_enrichment`. pipeline-monitor: `get_opportunity`, `get_account_context`, `search_interactions`, `create_proposal`, `flag_risk`.
3. **Research agent exfiltration controls:** no private data in search queries; `fetch_page_sim` limited to an allow-list; drafts get a link screen ([execution-architecture.md](execution-architecture.md) section 13.5).
4. **Stored-injection labelling:** agent state and `ai_*` fields are marked "derived from untrusted input" and are re-wrapped as data when read back into later context packs.
5. **Delivery:** the `gtm-propose` server and the execution-token mechanism are delivered in milestone M4; the `gtm-read` server in M5.
