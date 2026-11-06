# Requirements

Requirements are **[P]**, derived from the workflows and principles. Priority uses MoSCoW: **M** must, **S** should, **C** could. "Release" refers to the sequence in [use-case-prioritisation.md](use-case-prioritisation.md) section 5 (step 0 = foundations). Each requirement should become testable in Phase 5; the "Verification" column hints how.

## 1. Functional requirements

### 1.1 Shared platform (step 0)

| ID | Requirement | Pri | Verification |
|---|---|---|---|
| FR-PLT-01 | Store accounts, contacts, leads, opportunities, activities, meetings, documents and tasks in one shared database | M | Schema test, cross-motion scenario |
| FR-PLT-02 | Provide a simulated CRM exposed through a REST API, with an interface that a HubSpot adapter could implement | M | Contract tests |
| FR-PLT-03 | Expose CRM and data operations to agents through MCP tools with per-agent permissions | M | Tool-call correctness eval; permission tests |
| FR-PLT-04 | Provide an approval queue where every gated action is stored as a proposal with evidence, then approved, edited or rejected by a named human | M | Gate-compliance eval |
| FR-PLT-05 | Write an immutable audit record for every agent run, tool call, proposal and decision (who/what, inputs, outputs, timestamp, model, cost) | M | Audit completeness test |
| FR-PLT-06 | Receive inbound events through webhooks with idempotency keys | M | Replay test |
| FR-PLT-07 | Generate reproducible synthetic data (accounts, leads, deals, notes, transcripts) from a seed and a parameter file | M | Determinism test |
| FR-PLT-08 | Use n8n (or equivalent) only for deterministic orchestration such as triggers, schedules and notifications; reasoning lives in the agent service | S | Architecture review |
| FR-PLT-09 | Optional HubSpot adapter behind the same interface | C | Contract tests against the free tier |

### 1.2 Inbound

| ID | Requirement | Pri |
|---|---|---|
| FR-INB-01 | Normalise enquiries from web form, email and referral into one lead schema | M |
| FR-INB-02 | Detect exact and fuzzy duplicates (email, domain, name similarity) before any record is created | M |
| FR-INB-03 | Classify enquiries as genuine, vendor/sales, recruiter, spam, or unclear, with confidence and reason | M |
| FR-INB-04 | Research the company and contact, producing a brief in which every factual claim cites a source or is marked unknown | M |
| FR-INB-05 | Score fit against a documented ICP rubric (service need, size, sector, region, timing, budget signal) and explain the score | M |
| FR-INB-06 | Recommend an owner using routing rules (territory, service line, load), explaining any conflict | M |
| FR-INB-07 | Draft a reply and propose meeting times for human review | S |
| FR-INB-08 | Only auto-archive items classed as spam above a configurable confidence; everything else goes to a human | M |
| FR-INB-09 | Record the human's final decision and edits as feedback data | S |

### 1.3 Outbound

| ID | Requirement | Pri |
|---|---|---|
| FR-OUT-01 | Check target accounts against CRM, do-not-contact list and recent contact history | M |
| FR-OUT-02 | Produce an account dossier with sources, signals and confidence | S |
| FR-OUT-03 | Propose a service-line hypothesis and persona for each target | S |
| FR-OUT-04 | Draft personalised messages whose claims are checked against the dossier sources | S |
| FR-OUT-05 | Hold all drafts in an outbox; no agent tool may transmit externally | M |
| FR-OUT-06 | Route replies into the inbound workflow with the dossier attached | C |

### 1.4 Pipeline management

| ID | Requirement | Pri |
|---|---|---|
| FR-PIP-01 | Detect stalled deals with configurable rules (days without activity, stage dwell, past close date, no next step, single-threaded) | M |
| FR-PIP-02 | Detect CRM hygiene issues: missing fields, inconsistent stage/value, duplicates | M |
| FR-PIP-03 | Explain each flagged deal's risk using retrieved notes and activities, citing evidence | S |
| FR-PIP-04 | Recommend next actions as proposals, never as direct changes | S |
| FR-PIP-05 | Produce a weekly digest where all numbers come from queries and the language model only writes commentary | S |
| FR-PIP-06 | Require approval for any change to stage, value, close date, owner or forecast category; Won/Lost transitions are human-only | M |
| FR-PIP-07 | Record dismissals with reasons and expose false-positive rates per rule | S |

### 1.5 Customer engagement

| ID | Requirement | Pri |
|---|---|---|
| FR-CUS-01 | Generate a meeting brief (history, stakeholders, open actions, risks, suggested questions) from internal data | M |
| FR-CUS-02 | Process a transcript into summary, decisions, action items, risks and commercial mentions, with supporting quotes | S |
| FR-CUS-03 | Draft a follow-up email for human review | S |
| FR-CUS-04 | Propose CRM updates from a meeting as an approvable change set | S |
| FR-CUS-05 | Flag possible expansion or risk signals with evidence and confidence | C |
| FR-CUS-06 | Never include pricing, dates or scope commitments in drafts; flag the passages that touch them | M |

### 1.6 Dashboard and evaluation

| ID | Requirement | Pri |
|---|---|---|
| FR-DSH-01 | Show leads, accounts, opportunities, agent runs, pending approvals, pipeline alerts, customer interactions | M |
| FR-DSH-02 | Let a reviewer approve, edit or reject from the dashboard, with evidence next to each proposal | M |
| FR-DSH-03 | Show evaluation results, regression status and operational/business metrics with stated denominators | M |
| FR-EVL-01 | Provide a labelled synthetic scenario set covering normal, edge, adversarial and failure cases | M |
| FR-EVL-02 | Run the suite automatically on prompt, model or tool changes and flag regressions | M |
| FR-EVL-03 | Measure qualification accuracy, research factuality, tool-call correctness, CRM write success, duplicate prevention, approval compliance, latency and cost | M |

## 2. Non-functional requirements

| ID | Category | Requirement | Pri |
|---|---|---|---|
| NFR-SAF-01 | Safety | Agents have no tool capable of sending external communications or committing pricing. Absence of capability, not prompt instructions, enforces this | M |
| NFR-SAF-02 | Safety | Approval gates are enforced in application code. A proposal cannot be executed without a recorded human decision | M |
| NFR-SAF-03 | Safety | All external text (emails, web pages, transcripts) is treated as untrusted data; injection test cases exist | M |
| NFR-SEC-01 | Security | Role-based permissions per agent and per human role, least privilege, deny by default | M |
| NFR-SEC-02 | Security | Secrets only through environment variables; none in the repository, logs or prompts | M |
| NFR-SEC-03 | Security | Retrieval scoped by account; no cross-account context in a single run unless explicitly required | M |
| NFR-SEC-04 | Security | Personal data minimised; synthetic data only in this repository; logs redact contact details where possible | S |
| NFR-REL-01 | Reliability | Retries with exponential backoff on transient failures; dead-letter state for permanent failures | M |
| NFR-REL-02 | Reliability | CRM writes are idempotent; partial failures leave no half-written state | M |
| NFR-REL-03 | Reliability | Structured model output is schema-validated, with one repair retry, then a safe fallback to human review | M |
| NFR-REL-04 | Reliability | Every run has a timeout and a cost cap | M |
| NFR-OBS-01 | Observability | Each run emits a trace: steps, tool calls, model, tokens, latency, cost, outcome | M |
| NFR-OBS-02 | Observability | Alerts or dashboard indicators for failure rate, queue age, cost spikes | S |
| NFR-AUD-01 | Auditability | Any record change can be traced to a proposal, an approver and an agent run | M |
| NFR-EXP-01 | Explainability | Every recommendation shows its evidence and its uncertainty; "insufficient evidence" is a valid output | M |
| NFR-PER-01 | Performance | Inbound processing to a ready-for-review proposal under ~2 minutes median (target to confirm against measured results) | S |
| NFR-COST-01 | Cost | Free or low-cost stack; model choice routed by task difficulty; cost per workflow reported | M |
| NFR-COST-02 | Cost | The system runs end to end offline against recorded model responses so tests are free and reproducible | M |
| NFR-MNT-01 | Maintainability | Prompts, skills, rubrics and thresholds are versioned files, not inline strings | M |
| NFR-MNT-02 | Maintainability | No framework added without a documented reason (architecture decision record) | M |
| NFR-PRT-01 | Portability | Runs locally with containers; no cloud account needed | S |
| NFR-HON-01 | Honesty | Evaluation reports state sample sizes, synthetic provenance and limitations; no unmeasured claims | M |

## 3. Constraints and assumptions

- Python/FastAPI back end, TypeScript/React dashboard, PostgreSQL, Claude API, MCP and n8n are the intended stack. This is the starting point and Phase 3 must justify each piece (for example, whether n8n earns its place).
- No paid enrichment or sending services. Real LLM calls need an API key and have a cost; a budget is an open question.
- All people, companies and transcripts are synthetic.
- Model output is nondeterministic; evaluation uses repeated runs and thresholds, not exact matching.

## 4. Traceability sketch

| Problem | Requirements |
|---|---|
| P-01, P-03 | FR-INB-01, -03, -05, -06, -07; NFR-PER-01 |
| P-02, P-05 | FR-INB-04, FR-OUT-02, -04 |
| P-04 | FR-INB-02, FR-PIP-02, FR-OUT-01, NFR-REL-02 |
| P-06, P-07, P-08 | FR-PIP-01 to -07 |
| P-09, P-10, P-11, P-12 | FR-CUS-01 to -06, FR-PLT-01 |
| P-13 | FR-DSH-03, FR-EVL-03, NFR-OBS-01 |
| R-01 to R-13 | NFR-SAF, NFR-SEC, NFR-REL, NFR-AUD, FR-EVL-01 |

---

# Phase 3 addendum (new requirements; sections above unchanged)

Added after incorporating the GTM Engineering talk (see [gtm-engineering-framework.md](gtm-engineering-framework.md)). Priority marks MVP (M) or later (S/C). Traceability: problems P-14 and P-15 plus existing P-04, P-06, P-12.

## 4. Data requirements

| ID | Requirement | Pri |
|---|---|---|
| FR-DAT-01 | Store every enrichment datum as an immutable observation with source, observed/fetched time, confidence and raw reference | M |
| FR-DAT-02 | Resolve current field values by documented survivorship rules; retain superseded observations | M |
| FR-DAT-03 | Provide a data-source registry with per-field reliability priors, cost and TTL | M |
| FR-DAT-04 | Implement a waterfall over first-party data and at least three simulated providers, with a cost cap per run, in sequential and parallel modes | M |
| FR-DAT-05 | Track freshness state (fresh, stale, expired) per field; expired values are not used for scoring | M |
| FR-DAT-06 | Flag conflicts when top candidate values are close, and lower confidence accordingly | M |
| FR-DAT-07 | Resolve entities in three bands (link, proposal, distinct); merges are always proposals and soft/undoable; negative matches are remembered | M |
| FR-DAT-08 | Model account hierarchy as relationships with provenance; attach contacts to the most specific supported account | M (basic) |
| FR-DAT-09 | Enforce a field-ownership policy (human, system, provider, agent, shared) in the data-access layer and the CRM adapter | M |
| FR-DAT-10 | Record buying signals with strength and expiry | S |

## 5. Orchestration requirements

| ID | Requirement | Pri |
|---|---|---|
| FR-ORC-01 | Execute workflows as durable graphs with trigger, schedule, code, tool, conditional, LLM, agent, map, reduce, wait and approval nodes | M |
| FR-ORC-02 | Resume runs after worker crash without repeating completed side effects | M |
| FR-ORC-03 | Derive idempotency keys for every side effect and return prior results on repeat | M |
| FR-ORC-04 | Apply per-node retry policies (backoff, jitter, retryable error classes), timeouts and cost caps | M |
| FR-ORC-05 | Support parallel fan-out with concurrency limits and deterministic fan-in | M |
| FR-ORC-06 | Provide wait nodes resumable by event, time or predicate, with bounded polling and parking on timeout | M |
| FR-ORC-07 | Track sync state per (entity, target system) and prevent use of an entity before it is visible in the target | M |
| FR-ORC-08 | Use an outbox so state changes and domain events commit atomically; deduplicate events | M |
| FR-ORC-09 | Provide a dead-letter / needs-attention queue with one-click retry | M |
| FR-ORC-10 | Version workflow definitions; record version, prompt versions and model ids on every run | M |

## 6. Account-intelligence requirements

| ID | Requirement | Pri |
|---|---|---|
| FR-ACC-01 | Maintain persistent, versioned, evidence-linked state per account | M |
| FR-ACC-02 | Wake the account agent on events and scheduled heartbeats, coalescing bursts and allowing one wake per account at a time | M |
| FR-ACC-03 | Skip model calls when a deterministic change detector finds no material change | M |
| FR-ACC-04 | Restrict agent output to a typed action menu, including `no_action` | M |
| FR-ACC-05 | Allow the agent to write only agent-owned fields and its own state directly; all else via proposal | M |
| FR-ACC-06 | Implement lifecycle states (active, quiet, dormant, archived, needs-attention) with reactivation triggers | M |
| FR-ACC-07 | Capture human feedback with reason codes and feed a digest into future context | M |
| FR-ACC-08 | Rebuild account state from source records on demand | S |

## 7. Execution requirements

| ID | Requirement | Pri |
|---|---|---|
| FR-EXE-01 | Route all outbound actions through a deterministic gateway that verifies a human approval bound to the exact payload hash, role and expiry | M |
| FR-EXE-02 | Gateway enforces suppression, do-not-contact, outreach claims, frequency caps, duplicate-outreach keys, domain circuit breaker and sync preconditions | M |
| FR-EXE-03 | Classify and route replies; apply unsubscribe, bounce and out-of-office handling automatically in the safe direction | M |
| FR-EXE-04 | Stop sequences automatically on reply, booking, unsubscribe, bounce, suppression or opportunity creation | M |
| FR-EXE-05 | Require just-in-time approval for each sequence step in the MVP | M |
| FR-EXE-06 | Handle meeting-booking events (stop outreach, record meeting, wake agent, start brief) | S |
| FR-EXE-07 | Let owners pause agents per account/contact; human actions supersede conflicting proposals | M |
| FR-EXE-08 | Provide a complete audit trail from draft to external effect | M |

## 8. Additional non-functional requirements

| ID | Requirement | Pri |
|---|---|---|
| NFR-SIM-01 | Simulators share a seeded ground-truth world and support fault injection (latency, 429, 5xx, partial data, eventual consistency, duplicate and out-of-order events) | M |
| NFR-SIM-02 | System uses an injectable clock so long simulated periods run fast and deterministically | M |
| NFR-EVL-01 | Safety invariants (no effect without approval, no field-policy violation, no duplicate side effect) are checked automatically over every scenario's event log | M |
| NFR-AUD-02 | Audit store is append-only at the database permission level | M |
| NFR-DAT-01 | Provider accuracy, entity-resolution quality and confidence calibration are measurable against ground truth | M |
| NFR-OPS-01 | n8n is optional; the system runs end to end without it | M |

---

# Phase 3b addendum: GTM product loop (new requirements; all sections above unchanged)

Added after the second source ([gtm-product-loop.md](gtm-product-loop.md), [experimentation-engine.md](experimentation-engine.md), [maturity-and-scope.md](maturity-and-scope.md)). Priority: **M** = MVP, **X** = MVP-stretch (first to cut), **L** = later. Traceability to problems P-16 and P-17 (added to problem-discovery) plus P-13.

## 9. Feedback intelligence

| ID | Requirement | Pri |
|---|---|---|
| FR-FBK-01 | Extract feedback items (objection, pain point, request, competitor mention, lost reason, praise, risk) from interactions, with a verbatim quote and its location in the source | M |
| FR-FBK-02 | Reject any extracted item whose quote is not found in the source text, in code | M |
| FR-FBK-03 | Capture a structured lost-deal review for every closed-lost opportunity, with human-entered reasons; AI suggestions are separate and labelled | M |
| FR-FBK-04 | Attach a segment snapshot (service line, industry, size band, deal-size band) to each item at extraction time | M |
| FR-FBK-05 | Group items into themes; count distinct accounts, not mentions; keep singletons on a watch list below the recurrence threshold | M |
| FR-FBK-06 | Show counter-evidence, segment mix, trend and linked revenue with every theme; never rank by count alone | M |
| FR-FBK-07 | Themes require a human decision to confirm, merge, split or reject (G11) | M |
| FR-FBK-08 | Record human interviews and lost-deal debriefs as first-class sources | M |
| FR-FBK-09 | Provide a weekly insight digest; handoff records with acknowledgement status | L |
| FR-FBK-10 | Support simulated support, signup and website-activity sources | L |

## 10. Backlog

| ID | Requirement | Pri |
|---|---|---|
| FR-BKL-01 | Maintain one GTM improvement backlog with problem/opportunity, source, occurrences, distinct accounts, affected teams, impact, revenue relevance, effort, advisory score, priority, status and outcome | M |
| FR-BKL-02 | Priority and status are human-owned; the advisory score never sets them | M |
| FR-BKL-03 | Link backlog items to themes, experiments and workflow versions; record outcomes with metric references | M |
| FR-BKL-04 | Keep "won't do" items with their reasons | M |
| FR-BKL-05 | Operate with a single centralised GTM Engineering team as the owner; no multi-team intake workflow | M |

## 11. Experimentation

| ID | Requirement | Pri |
|---|---|---|
| FR-EXP-01 | Support a hypothesis record linked to a backlog item, with audience, variants, primary and guardrail metrics, minimum sample, runtime limits and stop rules, frozen by hash at approval | X |
| FR-EXP-02 | Define audiences from a versioned ICP definition over fresh resolved fields; exclude suppressed, claimed and expired-data contacts; freeze an audience snapshot at launch | X |
| FR-EXP-03 | Assign variants deterministically by hash; support holdouts | X |
| FR-EXP-04 | Require human approval for design (G14) and launch (G15); no agent tool may launch, resume, expand, reallocate or stop-for-success | X |
| FR-EXP-05 | Experiment messages use the standard per-message approval and gateway; experiment claim prevents overlapping experiments | X |
| FR-EXP-06 | Automatically pause on pre-defined guardrail breach (safe direction), with audit and notification | X |
| FR-EXP-07 | Compute results in code at pre-registered analysis points with intervals and a label (conclusive, directional, inconclusive); the LLM only narrates | X |
| FR-EXP-08 | Produce a rule-based continue/modify/stop/ship recommendation; the decision is human (G16) | X |
| FR-EXP-09 | Validate the engine with an A/A run and planted-effect runs | X |
| FR-EXP-10 | Learning library; multiple concurrent experiments; templates; sequential or Bayesian analysis | L |

## 12. Scope and human-involvement requirements

| ID | Requirement | Pri |
|---|---|---|
| FR-HUM-01 | No action exists that replaces a customer conversation with automation; the account agent may `recommend_human_touch` | M |
| FR-HUM-02 | Summaries, themes and recommendations link to raw quotes; review screens show raw quotes first | M |
| FR-HUM-03 | Report human-conversation coverage of key accounts (last 90 days) on the dashboard | X |
| FR-HUM-04 | Draft debrief question guides for lost-deal calls; the call itself is human | X |
| NFR-SEC-05 | Cross-account analysis is limited to the insight service's portfolio-read scope; agents remain account-scoped; role-based anonymisation of theme evidence | M |
| NFR-COST-03 | Feedback extraction uses a small model; theme refresh is batched; experiment statistics are code | M |
| NFR-SCP-01 | New capabilities are shared services, not standalone agents, and need an evaluation scenario before being built | M |

---

# Phase 3c addendum: review amendments (all sections above unchanged unless stated)

Added after design review. Priority M = MVP.

## 13. New and amended requirements

| ID | Requirement | Pri |
|---|---|---|
| FR-PLT-10 | Provide the `gtm-propose` MCP server (M4) and `gtm-read` MCP server (M5), with scope bound to the run | M |
| FR-EVL-04 | Provide a thin evaluation harness (scenario runner, event-log invariant checker, baseline format) from M0 and M2 | M |
| NFR-AUD-01 (amended) | Every change traces to a proposal and approver **or** to a rule/system actor with rule id and version, plus an agent run where one exists | M |
| NFR-AUD-03 | Audit events form a hash chain in the MVP; automatic actions record actor, rule/model and version, input reference, confidence and reversal reference | M |
| NFR-SAF-04 | Approvals bind to a defined hash (recipient, channel, sender, content, links, attachments, experiment ids, policy version), are single-use, and the hash is recomputed at execution | M |
| NFR-SAF-05 | Side-effecting adapters require a gateway-issued execution token; workflow lint rejects direct references | M |
| NFR-SAF-06 | Suspected spam is held reversibly, never silently destroyed; exact-match linking excludes role mailboxes and free-mail domains | M |
| FR-GOV-01 | Every human override is gated, evidenced and audited; suppression lifting is human-only with evidence | M |
| NFR-SEC-06 | Principal and account are bound to a run; out-of-scope ids are denied and logged | M |
| NFR-SEC-07 | Separation of duties for G6, G12, G14, G16 | M |
| NFR-SEC-08 | Insight and experiment services use their own service principal; narratives use anonymised inputs | M |
| NFR-EVT-01 | At-least-once delivery with idempotent consumers, gap-safe dispatch, version-based stale-event handling, one canonical event catalogue | M |
| NFR-DAT-02 | Provenance labels (`data_origin`, `evidence_basis`) on all non-production records and reported metrics | M |

## 14. Priority reconciliation

| Requirement | Was | Now | Reason |
|---|---|---|---|
| FR-INB-07 (draft reply) | S | **M** | It is a step of the golden thread |
| FR-CUS-01, FR-CUS-06, FR-OUT-01 | M | **M within their motion**; the motion is MVP-stretch (M8) | They are not in the golden thread |
| FR-PIP-05 (weekly digest) | S | S (stretch within M6) | Named M6 deliverable but not required for the golden thread |
| FR-ACC-08 (state rebuild) | S | **M** | Needed by S27 and risk AR-05 |
| FR-EXE-06 (booking events) | S | S | S19 is verified without the brief in M4 |
| FR-DAT-08 (basic hierarchy) | M (basic) | M: parent/child link and subsidiary-contact attachment only; no roll-ups | Clarifies "basic" |
