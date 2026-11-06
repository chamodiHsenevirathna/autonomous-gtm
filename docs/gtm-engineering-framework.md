# GTM engineering framework: what we take from the talk

**New file (Phase 3).**

## 1. Source and its limits

**[F, public listing]** Everett Berry, "GTM Engineering: The Technical Bits", AI Engineer World's Fair 2026. A speaker page confirms he appeared at the 2026 conference ([ai.engineer speaker page](https://ai.engineer/speakers/everett-berry)); the speaker is described there as leading GTM engineering at Clay.

**Provenance caveat:** everything below attributed to the talk comes from the project owner's written summary. I have not watched or read the talk and did not locate a transcript. Where this document says "the talk says", read "the summary of the talk says". Nothing here claims to describe Clay's internal architecture. We borrow engineering principles and test them in a small, fictional, synthetic setting.

## 2. The four areas as summarised

| Area | Summary of the talk's points **[F, via owner summary]** |
|---|---|
| Data | Accurate, continuously updated view of accounts, contacts, market. Hierarchies, firmographics, technographics, buying signals, first/third-party data, waterfalling, provider evaluation, entity resolution, freshness |
| Orchestration | Coordinate GTM systems and keep data in sync. Triggers, schedules, dependencies, waiting/polling, conditionals, parallelism, retries, failure handling, fan-out/fan-in. Graph with agent, tool, conditional, code and map/reduce nodes |
| Agents | Maintain account context over long cycles. Persistent account-level agents woken by triggers or heartbeats; ingest current context; reason about next actions; keep agent-specific state; separate agent-owned CRM fields from human-owned and deterministic-system-owned fields |
| Execution | Coordinate customer-facing actions across channels. Reply routing, email-domain reputation, sequence suppression, preventing conflicting campaigns, coordinating humans with agents |

## 3. Mapping to our Phase 1 and 2 work

| Talk area | Already in our docs | Gap the talk exposes | Where addressed |
|---|---|---|---|
| Data | Dedupe at intake (I1), research brief (I2), shared data model, "unknown is valid" | We assumed enrichment is one agent step. No provenance per field, no freshness, no conflict handling, no hierarchies | [data-model.md](data-model.md) |
| Orchestration | n8n for triggers; "deterministic automation plus narrow LLM" | No durable execution semantics, no waiting for out-of-sync systems, no idempotency design | [orchestration.md](orchestration.md) |
| Agents | Research agent, pipeline monitor with daily scan | Our agents were stateless per run. Nothing maintains account context across a 60 to 120 day cycle; no field ownership model | [account-agents.md](account-agents.md) |
| Execution | Draft-only outbox, approval gates (FR-OUT-05, NFR-SAF-01) | No reply routing, suppression, conflict prevention, deliverability, or multi-channel coordination | [execution-architecture.md](execution-architecture.md) |

## 4. Where we deliberately differ from the talk's direction

| Topic | Talk's emphasis **[F, via summary]** | Our position **[P]** | Reason |
|---|---|---|---|
| Autonomy in execution | Agents coordinate with human reps across channels | Agents **never** send or commit. A deterministic gateway performs only human-approved actions | Project principle, risk R-02 |
| Scale | *[A: my inference, not in the summary]* a large commercial platform | One fictional consultancy, tens of accounts to low thousands | Portfolio scope; low volume, high value ([business-context.md](business-context.md) section 4) |
| Providers | Third-party data, waterfalling and provider evaluation | Simulated providers with known ground truth | Free tooling; also gives us measurable accuracy |
| Orchestration | The summary describes a graph with typed nodes | A small durable graph runner on Postgres | No framework without a reason (NFR-MNT-02) |

## 5. MVP versus later

| Capability from the talk | MVP | Later | Not planned |
|---|---|---|---|
| Multi-provider waterfall with provenance, confidence, freshness | Yes (3 mock providers + first-party) | More providers, cost-based routing | Live paid APIs |
| Entity resolution with human-reviewed merges | Yes (accounts, contacts) | Cross-source graph, ML matcher | |
| Account hierarchy | Basic parent/child | Roll-ups, ownership inheritance | Full corporate-structure data |
| Technographics, buying signals | Simulated signals as inputs | Signal monitoring (O2 stays deferred) | Live scraping |
| Graph orchestration | Yes (11 node types, durable, retries, waits) | Visual editor, versioned graph deployment | |
| Persistent account agent | Yes (event-driven, state in Postgres) | Cadence tuning, richer memory | One always-on process per account |
| Field ownership model | Yes (core safety mechanism) | Per-field UI policy editor | |
| Reply routing, suppression, conflict prevention | Yes (email + call task) | Additional channels | |
| Email-domain reputation | Simulated throttles and circuit breaker | Real deliverability monitoring | Warm-up/DNS management |
| Sequences | Single-message sends; multi-step with just-in-time approval | Pre-approved sequences (policy decision, see open questions) | Autonomous cold sequences |
| Multi-channel (LinkedIn, calling) | Calls and LinkedIn as human tasks | Telephony integration | |

## 6. Second source (added later): the GTM-as-product interview

A second source, an interview with Clay's first GTM Engineer (listed as Yash Tekriwal), adds a different dimension: not *what to build* but *how GTM engineering decides what to build*. As with the first source, content comes from the project owner's summary only. See [gtm-product-loop.md](gtm-product-loop.md) section 1.

| Concept **[F, via owner summary]** | Where it lands | Relationship to the talk's four areas |
|---|---|---|
| GTM as an iterative product process; teams as feedback sources | [gtm-product-loop.md](gtm-product-loop.md) sections 3 to 5 | Uses Data (interactions, signals), Orchestration (new workflows) and Agents (read feedback) |
| Recurring problems become workflows, automations, experiments | Backlog and experiment service | Execution (experiments run through the gateway) |
| Experimentation | [experimentation-engine.md](experimentation-engine.md) | Execution plus Data (audience over resolved fields) |
| Maturity stages | [maturity-and-scope.md](maturity-and-scope.md) | Scope control across all four areas |
| Automate the manual, not the important | [maturity-and-scope.md](maturity-and-scope.md) section 4 | Constrains Agents and Execution |

No conflicts with the first source were found. One tension is recorded: experiments invite volume and automation in execution, which the project's rules keep behind per-message human approval, so MVP experiments are small ([experimentation-engine.md](experimentation-engine.md) sections 5 and 7).
