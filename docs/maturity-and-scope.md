# Company maturity, scope and human-led work

**New file (Phase 3).** Tags: **[F]** sourced, **[A]** assumption, **[P]** proposal.

## 1. Maturity model

**[F, via owner summary]** The interview distinguishes early-stage, growing, scaling and mature organisations, with capabilities appropriate to each. **I do not have the interview's criteria for the stages.** The descriptions below are my own interpretation **[P]** and should be checked against the source when it is available.

| Stage | Typical GTM shape **[P]** | GTM engineering shape | Characteristic capabilities |
|---|---|---|---|
| Early | A few sellers, founder-led; processes informal | Nobody dedicated; scripts and spreadsheets | Manual feedback capture, one data source, basic automations, a simple CRM |
| Growing | Defined roles (BDR, AE, RevOps); repeatable motions; ~10 to 30 GTM staff | **Small central team (1 to 2)** | Shared data layer, enrichment with provenance, approval-gated workflows, theme tracking, a few experiments, a single backlog |
| Scaling | Multiple segments/regions; more handoffs | Central team plus embedded engineers per motion | Experiment programme with mutual-exclusion rules, SLAs, cross-team backlogs, deeper attribution |
| Mature | Large, specialised teams; governance needs | Platform and enablement functions | Formal governance, forecasting, self-service building by non-engineers, advanced attribution, cost allocation |

**Corvane is "growing" ([business-context.md](business-context.md) section 2, ~12 GTM staff) [A].** Consequences: one central GTM Engineering team (1 to 2 people), one backlog, one approval structure with few roles, no governance boards, no embedded pods, no self-service platform.

## 2. Capability by stage (what we build for a growing organisation) **[P]**

| Capability | Early | Growing (**our target**) | Scaling | Mature |
|---|---|---|---|---|
| Shared data model with provenance | No | **Yes** | Yes | Yes + stewardship function |
| Multi-provider waterfall | No | **Yes, 3 sources** | Cost-based routing | Contracted vendor management |
| Entity resolution | Manual | **Rules + review** | ML matcher | Master data management |
| Orchestrated workflows | Scripts | **Durable graph runner** | Visual builder, many owners | Platform with governance |
| Persistent account agents | No | **Event-driven, small** | Portfolio-level | Tiered by account value |
| Execution controls | Manual | **Gateway, suppression, claims** | Multi-channel, deliverability ops | Dedicated deliverability team |
| Human approval | Everything manual | **Gated proposals** | Policy-based pre-approvals | Risk-tiered policy engine |
| Feedback capture | Notes | **Extraction, themes, lost-deal reasons** | Dedicated insight function | Voice-of-customer programme |
| Backlog | Informal | **Single backlog, weekly triage** | Multi-team intake, SLAs | Portfolio planning |
| Experimentation | Ad hoc | **One governed experiment type, honest statistics** | Programme with mutual exclusion and templates | Experimentation platform, advanced methods |
| Evaluation | Spot checks | **Scenario suite, invariants, regression gates** | Continuous production monitoring | Formal model risk management |

## 3. Master scope table: MVP, later, out of scope

This table covers capabilities from all sources. "MVP-core" is the golden thread (M0 to M7). "MVP-stretch" is included in the plan but is the first thing to cut if time is short.

| Capability | Status | Rationale |
|---|---|---|
| Shared data layer, observations, field ownership | MVP-core | Foundation |
| 3-provider simulated waterfall, survivorship, freshness | MVP-core | Talk area 1 |
| Entity resolution (3 bands), basic hierarchy | MVP-core | Duplicate prevention is a core goal |
| Durable graph orchestration, sync-lag handling | MVP-core | Talk area 2 |
| Event-driven account agent with change detector | MVP-core | Talk area 3 |
| Execution gateway, reply routing, suppression, claims | MVP-core | Talk area 4; safety |
| Approval, audit, feedback reason codes | MVP-core | Project principle |
| Evaluation: replay, live-sample, chaos, invariants | MVP-core | Phase 5 |
| Pipeline heartbeat, stall rules, digest | MVP-core | Highest-scoring use cases |
| Lost-deal reason capture (F4) | **MVP** | Highest-scoring new use case; low risk; human-entered |
| Feedback extraction with verbatim evidence (F1) | **MVP** | Reuses LLM-call machinery; internal only |
| Basic recurring-theme detection (F2) with distinct-account counting | **MVP** | Needed to show "patterns, not individual requests" |
| GTM backlog with advisory score, human priority (F3) | **MVP** | Small; makes the loop visible |
| One simulated experiment, end to end (X1/X2) | **MVP-stretch** | Valuable demonstration; most scope risk |
| Customer meeting brief and transcript follow-up (C1, C2) | MVP-stretch (as in Phase 3 roadmap) | Unchanged |
| Insight digest and handoff acknowledgement flow (F5) | Later | Digest text could be simple; tracking is extra |
| Outbound dossier and gated drafts (O1, O3) | Later (M8) | Unchanged |
| Pre-approved sequences / template-level approval | Later, policy decision | Nearer autonomous sending |
| Embedding-based clustering (pgvector) | Later | Add only if theme evals show recall gaps |
| Sequential / Bayesian experiment analysis | Later | Fixed-horizon first |
| Experiment programme: multiple concurrent experiments, templates, holdout *management* (a basic holdout flag is part of the MVP-stretch experiment) | Later | Needs volume |
| Visual workflow editor, versioned deployment tooling | Later | Not needed at this size |
| Real HubSpot adapter | Later, optional | Credibility extra |
| n8n edge workflows | Optional | Never required |
| Expansion detection (C3), signal monitoring (O2), health scoring (C4) | Later (as before) | Low scores, hard to evaluate |
| Autonomous sending, autonomous experiment launch or strategy (O4, X3) | **Out of scope** | Contradicts principles |
| Autonomous pricing, scope or date commitments | **Out of scope** | Contradicts principles |
| Real customer data, live paid enrichment, real telephony | **Out of scope** | Constraints |
| Embedded GTM engineers, governance boards, self-service builder platform | **Out of scope** | Enterprise complexity for a growing company |
| Real revenue attribution and forecasting models | **Out of scope** | Insufficient data; claims would be unsupportable |
| Reproducing any vendor's internal architecture | **Out of scope** | Explicit constraint |

## 4. "Automate the manual, not the important"

**[F, via owner summary and episode title]** The principle. **Its application here is [P].**

### 4.1 The test

For each candidate task, ask in order:
1. Is it **repetitive, information-moving and low in judgement** (preparing, transcribing, summarising, logging, routing, deduplicating, enriching, scheduling)? Automate, with gates where it writes or sends.
2. Does it involve **trust, negotiation, a customer's situation, or a strategic choice**? Keep it human-led.
3. Does it give the team a **chance to learn directly from a customer**? Preserve it; the system may prepare for it and record it, but not replace it.

### 4.2 Human-led by design

| Activity | System role | Human role |
|---|---|---|
| Discovery calls and scoping conversations | Brief before; summary and actions after | Hold the conversation |
| Customer meetings and QBRs | Brief; draft follow-up | Run the meeting; relationship |
| **Lost-deal debrief conversation** | Prepare a question guide; store human-entered reasons | Call the buyer; judge the real reason |
| Customer listening sessions / interviews | Suggest a diverse set of accounts to invite; store notes | Run them; interpret |
| Negotiation, pricing, terms, scope | None (A4) | All |
| Escalations and sensitive feedback (complaints, executive concerns) | Flag and route | Respond personally |
| Choosing experiments and strategy | Draft options and evidence | Decide |
| Theme confirmation and backlog priority | Propose, compute | Decide |
| Expansion conversations | Evidence and timing hints | Conversation and judgement |

### 4.3 Design commitments to preserve learning **[P]**

1. The system **never replaces a customer conversation** with automation and never recommends doing so for strategic accounts. A recommendation may add a human touch; it does not substitute one.
2. Every summary, theme and recommendation **links to the raw quote or recording** so the human can read the original.
3. Theme and backlog review screens show **sample raw quotes first**, before AI summaries.
4. Human interviews and lost-deal debriefs are **first-class feedback sources**, never down-weighted for being few.
5. A **coverage metric** is reported: share of key accounts with a human conversation in the last 90 days. A rise in automation alongside falling human contact is flagged on the dashboard.
6. The account agent's action menu includes `recommend_human_touch` and has no action that sends a customer-facing message by itself.
7. Reviewers are asked for a reason when they approve a theme without opening its evidence (sampled, not mandatory for every item, to avoid review fatigue).

## 5. Complexity guardrails

- No new standalone agent per capability. The new capabilities are **shared services** in the modular monolith ([solution-architecture.md](solution-architecture.md) section 9).
- No new datastore, broker or framework. Embeddings and statistics libraries are justified individually in ADRs when first needed ([technology-decisions.md](technology-decisions.md) section 13).
- A new capability needs a scenario it serves in the evaluation suite before it is built.
