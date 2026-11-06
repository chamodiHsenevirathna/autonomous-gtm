# Technology decisions

**New file (Phase 3).** Compares options and recommends the simplest architecture that supports the design, under the free or low-cost constraint. Recommendations are **[P]**. Statements about third-party tools reflect my general knowledge, not a fresh review, and are marked **[A]** where a Phase 4 spike should verify them. I have not benchmarked anything.

## 1. Summary of recommendations

| Concern | Recommendation | n8n? |
|---|---|---|
| Language / API | Python 3.12+, FastAPI | n/a |
| Orchestration | Small in-house durable graph runner on Postgres | Optional edge |
| LLM access | Claude Messages API, our own bounded tool loop; recorded-response replay | n/a |
| Agent SDK | Not in MVP; optional spike for the research node | n/a |
| MCP | Two in-process-capable MCP servers (data/read, proposal/write); no send tool | n/a |
| Database and state | PostgreSQL only (JSONB for state; FTS and trigram for retrieval) | n/a |
| Events and jobs | Postgres outbox, `SKIP LOCKED` job table, scheduler loop | Optional notifications |
| Simulated outside world | Small FastAPI simulators (CRM, 3 providers, outreach tool, mail/calendar) | n/a |
| Dashboard | React + TypeScript (Vite) | n/a |
| Local runtime | Docker Compose: Postgres + app + worker + simulators | Optional container |

## 2. Workflow orchestration

| Option | Pros | Cons | Fit |
|---|---|---|---|
| **n8n** (self-hosted) | Visual, many connectors, fast to prototype triggers/webhooks | Weak at durable waits with custom idempotency, versioned/testable graphs, offline replay and per-step cost/trace accounting. Self-hosting licence and operational terms **[A]** should be checked. JSON workflows are awkward to code-review | Good at the edges, poor as core |
| **LangGraph** (open source) | Graph model, checkpointing, human-in-the-loop interrupts, in the same Python ecosystem | A framework dependency whose checkpoint store is separate from our audit/event/outbox design; two sources of truth to reconcile; abstractions may leak **[A]** | Credible alternative. Strongest fallback |
| **Temporal** | Best-in-class durable execution | Heavy: server, workers, new programming model; overkill for this scale | Over-engineered |
| **Prefect / Airflow / Dagster** | Mature scheduling and DAGs | Batch/data-pipeline oriented; awkward for event-driven, long waits for humans and per-account wakes | Poor fit |
| **Celery/Arq/RQ + Redis** | Familiar task queues | Adds Redis; no graph semantics, durable waits or idempotent step records; we would build those anyway | Adds a dependency without removing work |
| **In-house runner on Postgres** | One datastore; transactions cover step, event, audit and state together; exact semantics we need; fully testable offline | We own the code and its bugs | **Recommended** with a size trigger |

**Decision AD-03:** build a minimal runner (job table with row locking, run/step tables, eleven node types, retry/backoff, wait/resume, idempotency) because our requirements are specific and small, and the consistency benefit of a single transactional store is large. **Exit criterion:** if it grows beyond ~1,500 lines, needs distributed workers, or reimplements features LangGraph provides, switch to LangGraph for graph execution while keeping our tables for events/audit. This is a judgement, and a reviewer could reasonably choose LangGraph from the start; the cost of that choice is the dual-store reconciliation described above.

**n8n position (AD-08):** optional. Valid uses: webhook intake that forwards to our endpoint; scheduled pings; notification fan-out. Anything correctness-critical stays out of it. A short appendix may show an n8n workflow calling our API to demonstrate the option, but no feature depends on it.

## 3. Claude API tool use versus Claude Agent SDK

| Aspect | Messages API + own loop | Agent SDK |
|---|---|---|
| Control of permissions, budgets, step limits | Total | Available through its configuration **[A: verify]** |
| Tracing and recorded-response replay (needed for free regression tests) | We build it, simple at the Messages boundary | Harder to intercept at the right level **[A: verify]** |
| Convenience for open-ended agent loops (file/web tools, context management) | We write the loop (small) | Built in |
| Dependency and surface area | Minimal | Larger |
| Fit for our nodes | Most nodes are single calls with structured output; the agent loop is needed only for research | Fits the research node best |

**Recommendation AD-05:** use the Messages API directly with a thin, project-owned wrapper that handles structured output validation, tool loop with step/cost limits, caching hooks, retries, recorded responses and cost accounting. Run a time-boxed spike in Phase 4 comparing the Agent SDK for the research node only; adopt it only if it reduces code without weakening permissions, tracing or replay.

**Model routing [P]:** a small model for classification and extraction, a mid-tier model for drafting and account reasoning, and a larger model only when evaluation shows a quality gap that matters. Concrete model ids are configured, not hard-coded, and chosen in Phase 4 from the current lineup and measured quality/cost. Prompt caching is used for stable prefixes (rubrics, action menu) where it helps.

## 4. MCP server architecture

Where MCP fits: MCP is the interface *agents* use to call tools; deterministic nodes call the same service functions directly. This avoids routing every internal call through a protocol layer and keeps MCP as the permissioned surface for model-driven actions, which is the property worth demonstrating.

| Option | Pros | Cons |
|---|---|---|
| One server with all tools | Simple | Permission differences become per-tool logic; larger blast radius |
| **Servers split by risk: `gtm-read` and `gtm-propose`** | Read-only server can be granted widely; write-ish server limited to proposals and `ai_*` field writes; there is *no* execution server visible to agents | Slightly more setup |
| Server per system (CRM, enrichment, etc.) | Familiar mapping | Many servers, duplicated auth, little added safety |

**Recommendation AD-10:** two servers, split by risk, over stdio for local use (in-process transport in tests). Tools are scoped by the agent's profile and by account. The execution gateway is deliberately **not** exposed over MCP. A third optional server could expose the simulated CRM as a standalone demonstration of a "CRM MCP server" for reviewers, mirroring the pattern in the job postings (E1). Tool list and schemas are specified in [mcp-integrations.md](mcp-integrations.md).

## 5. Database and persistent state

| Option | Verdict |
|---|---|
| **PostgreSQL** (JSONB, FTS, `pg_trgm`) | **Chosen.** Relational integrity for entities; JSONB for flexible agent state; FTS and trigram for retrieval and entity blocking; transactions for outbox, queue and audit |
| SQLite | Simpler, but no row-locking queue semantics or `pg_trgm`; your brief names Postgres |
| Redis | Not needed |
| Vector DB / pgvector | Deferred. Start with structured retrieval plus keyword/trigram search. Add pgvector only if evaluation shows retrieval misses |
| Graph database | Not needed. Hierarchies are shallow; adjacency in relational tables suffices |
| Event store product (Kafka etc.) | Overkill. Outbox table plus dispatcher suffices at this volume |

Separate Postgres **schemas** keep concerns apart: `gtm` (core), `ops` (jobs, runs, steps, events, audit), `crm_sim`, `outreach_sim`, `provider_sim`, `mail_sim`. The simulators use their own schemas and are accessed only over HTTP, so the application cannot cheat by reading their tables.

## 6. Events and scheduled jobs

Postgres-native: outbox event table, dispatcher, `SKIP LOCKED` job claim, lease expiry, scheduler loop reading `next_run_at`. Optional `LISTEN/NOTIFY` to reduce polling latency. No external cron, broker or APScheduler dependency; the scheduler is a few dozen lines inside the worker. Deterministic time via an injectable clock enables fast-forward in tests (e.g., simulate 60 days of heartbeats in seconds).

## 7. Simulated CRM and external integrations

| Simulator | Contents | Purpose |
|---|---|---|
| **CRM sim** | HubSpot-shaped objects (contacts, companies, deals, associations, properties, owners), REST API, webhooks | Realistic adapter boundary; lets a real HubSpot adapter be swapped in later (FR-PLT-09). Field policy mirrored |
| **Provider sims A/B/C** | Truth-backed, degraded data with tunable accuracy, coverage, staleness, cost, latency, faults | Waterfall development; provider accuracy evaluation |
| **Outreach-tool sim** | Contacts visible after delay, enrolments, replies | The CRM-to-outreach sync problem; reply events |
| **Mail/calendar sim** | Outbox sink, scripted replies/bounces, bookings, domain reputation | Reply routing; deliverability controls; meeting events |
| **Scenario driver** | Scripts world events on a controllable clock | Deterministic end-to-end tests |

All simulators share a **ground-truth world** generated from a seed and the parameter file ([business-context.md](business-context.md) section 1), and all expose **fault injection** (latency, 429, 5xx, partial data, eventual consistency, duplicate webhooks, out-of-order events).

A real HubSpot adapter (free CRM tier) remains an optional extra: the adapter contract is the same. I have not verified current free-tier API limits **[A]**.

## 8. Dashboard and frontend

React with TypeScript and Vite, calling the FastAPI backend; server-sent events or polling for live approvals. Charts via a small library chosen in Phase 4. No heavy state-management framework until needed.

## 9. Observability

Own trace tables (`run_step`, `tool_call`, `audit_event`) drive the dashboard. OpenTelemetry export is a possible later add-on, not in MVP, because it adds a collector and conceptual weight without improving the case study. Structured JSON logs with run ids complement the traces.

## 10. Dependency budget

Planned third-party runtime dependencies, each to be justified in an ADR on first use: FastAPI, Pydantic, an async Postgres driver, an HTTP client, the Anthropic SDK, an MCP SDK, pytest. Frontend: React, Vite, a chart library. No ORM mandated (decision in Phase 4), no message broker, no Redis, no workflow framework, no vector database, no LLM framework (LangChain-style).

## 11. Cost expectations

Infrastructure: zero beyond a laptop. The only variable cost is LLM usage in live runs. Controls: replay mode for tests, small models for classification, per-run and per-account budget caps, prompt caching for stable prefixes, change detector to skip unnecessary account wakes. A concrete monthly budget is an open question.

## 12. Decisions log (ADR index)

| ID | Decision | Status |
|---|---|---|
| AD-01 | Modular monolith + worker + simulators | Proposed |
| AD-02 | Postgres as sole datastore | Proposed |
| AD-03 | In-house durable graph runner (exit criterion defined) | Proposed |
| AD-04 | Event-driven virtual account agents | Proposed |
| AD-05 | Messages API with own loop; Agent SDK spike for research node | Proposed |
| AD-06 | Field ownership enforced in data layer | Proposed |
| AD-07 | Merges and sends are proposals only | Proposed (safety, fixed) |
| AD-08 | n8n optional at the edge | Proposed |
| AD-09 | Truth-backed simulators with fault injection | Proposed |
| AD-10 | Two MCP servers split by risk; no execution tool exposed | Proposed |
| AD-11 | Insight, backlog and experiment capabilities are shared services in the monolith, not agents | Proposed (section 13) |
| AD-12 | Feedback items require a code-verified verbatim quote | Proposed |
| AD-13 | Experiments are configurations of existing workflows; launch, resume, expand and stop-for-success are human-only | Proposed (safety, fixed) |
| AD-14 | Backlog priority is human-owned; scores advisory | Proposed |
| AD-15 | Embeddings (pgvector) and statistics libraries deferred until a failing evaluation justifies them | Proposed |

## 13. Technology implications of the GTM product loop

**[P]** No new infrastructure. Compared options:

| Concern | Options | Recommendation |
|---|---|---|
| Where new capabilities live | Separate agents or services / shared services in the monolith | **Shared services (AD-11).** A new agent per capability would multiply prompts, permissions and evaluation surface without adding capability; extraction, theme matching and narration are bounded LLM calls inside workflows |
| Theme grouping | Keyword/trigram + LLM comparison against theme definitions / embeddings + clustering | **Start with trigram plus batched LLM comparison.** Add pgvector only if the theme-recall evaluation shows misses that retrieval would fix (AD-15) |
| Experiment statistics | Standard-library arithmetic for normal-approximation tests (Python's `statistics.NormalDist` exists in the standard library) / SciPy or statsmodels | **Standard library first**, including exact small-count methods written and tested against known cases. Add a statistics library only if exact methods become necessary; ADR required (AD-15) |
| Experiment scheduling | Existing scheduler loop and job table | No new component |
| Backlog UI | Part of the existing React dashboard | No new component |
| Experiment platforms (third-party) | Adopt / build minimal | **Build minimal.** Our needs (deterministic assignment, claims, one metric type) are small, and a third-party platform would sit outside the audit and approval path |

Cost control: extraction uses a small model per interaction; theme refresh is weekly and batched; experiment statistics and guardrail monitoring are code with no model cost.
