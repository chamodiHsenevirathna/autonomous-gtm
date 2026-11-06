# Implementation roadmap

**Modified (Phase 3):** replaces the provisional stub. **[P]**. Effort figures are rough relative sizes **[A]** for one developer; they are not estimates from experience on this codebase.

## 1. Goal and discipline

A coherent working demonstration, not an enterprise GTM platform. Everything is judged by one question: *does it make the golden-thread scenario real and testable?* Capabilities from the talk that do not serve that scenario are deferred ([gtm-engineering-framework.md](gtm-engineering-framework.md) section 5).

## 2. Smallest end-to-end scenario: the golden thread

One synthetic enquiry travels through every layer.

1. An enquiry arrives by webhook (S01), from a person at a company that exists in the simulated world, possibly as a subsidiary of a known parent.
2. **Entity resolution** checks for the contact and account, links or proposes (S02–S05 variants).
3. **Waterfall enrichment** queries first-party data and three mock providers; observations are stored with provenance; survivorship resolves conflicts (S09–S10).
4. **Orchestration** runs the graph durably: map over providers, reduce, triage, qualification, with retries on injected faults (S11).
5. **Account intelligence:** the account agent wakes, builds state, and proposes: create account/contact in the CRM, plus a draft reply and a next-step task.
6. **Human approval:** the reviewer approves with an edit in the dashboard (S24).
7. **Controlled execution:** the gateway creates the contact in the simulated CRM, waits for it to appear in the outreach simulator (S13), re-checks suppression and approval validity, then sends the approved draft to the mail simulator.
8. A scripted reply arrives (S18); the router classifies it, stops the sequence, and wakes the account agent, which proposes the next step.
9. 45 simulated days later, with no activity, the heartbeat detects the stall and the agent recommends an action (S22).
10. Every step is in the audit log; the invariant checker confirms no external effect lacked approval; cost and latency are reported.

This single path demonstrates: **data** (waterfall, provenance, ER, freshness), **orchestration** (graph, fan-out/in, waits, retries, idempotency, sync lag), **agents** (persistent state, change detector, action menu, field ownership), **execution** (gateway checks, reply routing, suppression), **oversight** (gates, edits, audit), and **evaluation** (scenarios, invariants, traces).

## 3. Milestones

| M | Name | Deliverables | Exit criteria | Size |
|---|---|---|---|---|
| M0 | Foundations | Repo (own git), Docker Compose, Postgres schemas (`gtm`, `ops`), event/outbox/job tables, audit append-only role, field policy, injectable clock, config file for company parameters | Migrations apply; audit rows cannot be updated or deleted; clock fast-forward works | M |
| M1 | Simulated world | Ground-truth generator (seeded), provider A/B/C sims, CRM sim, outreach sim, mail/calendar sim, fault injection | Deterministic world; each sim returns degraded truth; faults switchable per test | L |
| M2 | Orchestration core | Graph runner: node types, retries, waits, idempotency, map/reduce, trace tables; replay-mode LLM wrapper with recording | Chaos tests: crash/restart resumes; no duplicate side effects; sync-wait scenarios S13–S16 pass | L |
| M3 | Data layer behaviour | Observations, waterfall, survivorship, freshness, ER with three bands and proposals | ER and provider-accuracy evals produce first baseline numbers | L |
| M4 | Oversight and execution | Proposal/approval service, reviewer UI (minimal), execution gateway with all checks, reply router, suppression | Approval-compliance property holds over all scenarios; S17–S21, S24, S25 pass | L |
| M5 | Intelligence | Triage, qualification, drafting, research agent (bounded), account agent with change detector and state | Golden thread (steps 1–8) passes in replay; live-sample run recorded | L |
| M6 | Pipeline heartbeat | Stall/hygiene rules, heartbeat scheduling, dormancy/reactivation, weekly digest | S22–S23 pass; simulated 60-day run costs reported | M |
| M7 | Evaluation and dashboard | Scenario runner, regression gates, metrics, full dashboard (leads, accounts, opportunities, agent activity, approvals, alerts, interactions, evals, ops/business metrics) | All Phase 6 dashboard views populated by real runs; limitations documented | L |
| M8 | Extensions (as time allows) | Customer-engagement: meeting brief (C1) and transcript summary (C2); outbound dossier (O1) with gated drafts (O3); optional HubSpot adapter; optional n8n edge workflow | Each extension has scenarios and metrics before it is called done | M each |

## 4. Relationship to the Phase 2 sequence

The Phase 2 order was: foundations, inbound, pipeline, customer, outbound ([use-case-prioritisation.md](use-case-prioritisation.md) section 5). The use-case ranking is unchanged. What changes is **how foundations are built**:

| Phase 2 | Phase 3 revision | Why |
|---|---|---|
| Step 0 foundations | Split into M0 to M4 (data, world, orchestration, oversight and execution) | The talk's concepts show that data resolution, durable orchestration and controlled execution are prerequisites, not features of one agent |
| Step 1 inbound | M5 (golden thread) | Same use cases I1 to I4, now running on shared layers |
| Step 2 pipeline | M6 | P1, P3, P4 reuse the heartbeat and account agent; P2 becomes an account-agent recommendation |
| Step 3 customer | M8 extension | Customer briefs and follow-ups reuse account state |
| Step 4 outbound | M8 extension, but its *execution machinery* (gateway, suppression, claims) is built earlier in M4 | Safety machinery must exist before any message can be drafted-then-sent, even for inbound replies |

Deferred as before: C3, O2, C4. Not planned: O4.

## 5. Scope guard: MVP versus later

| In MVP (M0 to M7) | Later or optional |
|---|---|
| Three mock providers + first-party waterfall | More providers, learning-based routing |
| ER for contacts and accounts, basic hierarchy | Complex hierarchy roll-ups |
| Graph runner with 11 node types | Visual editor, distributed workers |
| Account agent (single LLM call) with state and heartbeat | Agent loop with retrieval tools, embeddings |
| Single-message sends and just-in-time sequence steps | Pre-approved sequences |
| Reply routing, suppression, claims, caps, domain breaker | More channels, real deliverability |
| Inbound + pipeline demonstrated end to end | Customer and outbound extensions |
| Evaluation with replay, live-sample and chaos tiers | Large-scale statistical studies |

## 6. Risks (architecture and delivery)

| ID | Risk | Mitigation |
|---|---|---|
| AR-01 | **Scope creep.** The talk's breadth tempts a platform build | Golden-thread gate; each addition needs a scenario it serves |
| AR-02 | **Runner becomes a framework.** In-house orchestrator grows | Size trigger (AD-03); LangGraph fallback pre-analysed |
| AR-03 | **Simulators encode our assumptions**, so good results may be self-fulfilling | Report as simulation; vary simulator parameters; hold-out worlds with different seeds and degradation |
| AR-04 | **Over-engineering data model** before use | Build tables as milestones need them; keep the full model as the target |
| AR-05 | **State drift in account agents** | Evidence-linked state, rebuild capability, drift tests (S27) |
| AR-06 | **LLM cost in live tiers** | Replay by default; budgets; small models; sample sizes stated |
| AR-07 | **Reviewer UX is the weakest link** (automation bias, queue overload) | Evidence display, canaries, queue metrics ([human-oversight.md](human-oversight.md)) |
| AR-08 | **Clock and concurrency bugs** in durable execution | Injectable clock, deterministic tests, property tests on idempotency |
| AR-09 | **Talk interpretation risk**, because our source is a summary | Treat as inspiration; verify claims against the actual talk when available; avoid asserting vendor internals |
| AR-10 | **Single-developer bus factor and time** | Milestones deliver demonstrable increments; extensions optional |

## 7. Unresolved decisions (need your input)

1. **Sequence approval policy:** just-in-time per step (MVP default) or allow pre-approved sequences later? The second moves nearer autonomous sending.
2. **LLM budget** for live-sample tiers (a monthly cap and which model tiers are in scope).
3. **Orchestrator choice:** accept the in-house runner with exit criteria, or start on LangGraph to reduce owned code?
4. **Agent SDK spike** for the research node: worth the time-box?
5. **HubSpot adapter:** is a real free-tier connection desired for credibility, or is the simulator enough?
6. **n8n demonstration:** include a small optional edge workflow for show, or omit?
7. **Repository:** approve running `git init` inside this project (not the home repo) before M0?
8. **Talk source:** can you share the transcript or slides, so that talk-derived points can be verified rather than relying on the summary?
9. **Reviewer realism:** should the demo include a simulated "reviewer persona" to generate approval traffic, or is the human (you) the reviewer?
10. **Dashboard scope** if time is short: which views can be minimal?

---

# Addendum: GTM product loop (existing milestones unchanged)

Source: [gtm-product-loop.md](gtm-product-loop.md), [experimentation-engine.md](experimentation-engine.md), [maturity-and-scope.md](maturity-and-scope.md). The golden thread (M0 to M7) is not changed. Two additions:

| M | Name | Deliverables | Exit criteria | Size | Status |
|---|---|---|---|---|---|
| **M6b** | Learning loop (thin) | Lost-deal review capture; feedback extraction with code-verified quotes; basic theme detection (distinct accounts, watch list); backlog list with advisory score and human priority; gates G11 and G12; dashboard panel | S31 to S35 and S44 pass; planted themes recovered; zero priority changes without a human | M | **MVP** |
| **M8a** | One experiment (inside M8) | Experiment tables, ICP definition, assignment, G14/G15/G16, claims, guardrail auto-pause, fixed-horizon analysis, A/A and planted-effect runs | S36 to S43 pass; A/A false-positive rate near nominal; approval-compliance invariant holds | M | **MVP-stretch** (cut first) |

Dependencies: M6b needs M0 (tables, events), M3 (resolved fields for segment snapshot), M4 (approval service) and M5 (LLM-call wrapper and replay mode). M8a needs M4 (gateway), M5 (drafting) and M6b (backlog item as hypothesis source). Neither blocks the golden thread.

Why add M6b to the MVP: the lost-deal capture use case scores 4.40, the highest of the new candidates ([use-case-prioritisation.md](use-case-prioritisation.md) section 8), and it reuses machinery already being built. It is also what makes "patterns, not individual requests" demonstrable. **Justification for the scope increase, and the cost:** roughly one medium milestone. If time is short, drop M8a first, then theme detection, keeping lost-deal capture and extraction.

Additional unresolved decisions:
11. Is M6b in the MVP as proposed, or should the whole learning loop move to "later"?
12. Is the single simulated experiment (M8a) worth its scope, or should experimentation stay a design-only deliverable?
13. Should the demo include a seeded corpus with planted themes (recommended, since it makes theme detection measurable), accepting that results then verify machinery rather than real-world patterns?

---

# Corrections after design review

*These supersede the Exit criteria, Deliverables and Size entries of the milestone table above where they differ.*

| M | Added deliverables | Corrected exit criteria | Revised size **[A]** |
|---|---|---|---|
| M0 | Clock **interface**, config schema, `contracts/` (OpenAPI and JSON Schema, error taxonomy, event envelope, idempotency rule), event/dispatch/job/schedule/lease tables, audit hash chain, **thin eval harness** | Migrations apply; audit insert-only and chain verifies; invariant checker runs on an empty log; contracts versioned | M+ |
| M1 | Webhook emitter; conformance suite for the contracts; M1b: corpus generator for M6b (planted themes, transcripts, declared generator type) | Deterministic world; degraded-truth checks pass; faults switchable per test | L |
| M2 | Clock-aware wait scheduler; LLM wrapper **interface, recorder, schema validation and repair retry** | Crash/restart resumes; no duplicate side effects; **S11 to S15, S26 (against canned bad outputs), S30, S56** pass against stubs/sims. S16 and S17 move to M4 | L+ |
| M3 | Field policy used by survivorship | S02 to S05, S09 to S12 pass; first baselines via the thin harness | L |
| M4 | Minimal reviewer UI (approvals, run timeline, needs-attention queue); `gtm-propose` MCP server; execution tokens; full ordered gateway chain; reply router; suppression; claims | Approval-compliance invariant holds; **S16 to S21 (S19 without the brief), S24, S25, S45 to S49, S51, S52, S55**; S29 as stretch | XL |
| M5 | `gtm-read` MCP server; prompts and skills as versioned files; research untrusted-fetch handling | Golden thread steps 1 to 8 in replay (S01, S06, S07, S08, S50); S26 with real prompts; S27; S53; one recorded live run | XL |
| M6 | n/a | S22, S23; weekly digest is stretch | M |
| M6b | Uses the M4 minimal UI and the M1b corpus | S31 to S35, S44, S54 | M+ |
| M7 | Regression gates; dashboard views (see decision 14) | Gates enforced; Phase 6 views populated; limitations documented | L |
| M8 / M8a | n/a | S28 (M8); S36 to S43 (M8a) | M8a: **L** |

Other corrections:
- **LLM wrapper:** M2 delivers the interface and recorder; M5 and M6b are its first consumers (the addendum's "M5 delivers the wrapper" is corrected).
- **Section 5 "In MVP (M0 to M7)"** also includes **M6b**.
- **Golden thread step 5** produces two linked proposals (CRM create of account, contact and opportunity at "Qualified", then the intro reply), not one. The opportunity created at step 7 is what the day-45 stall (step 9) acts on.
- **Waiting:** orchestration owns the wait; the gateway returns READY / NOT_READY / BLOCKED ([orchestration.md](orchestration.md) section 13).
- Sizes rose in the review; the **total effort of the plan is larger than the first estimate**.

Additional unresolved decisions:
14. Dashboard scope: full nine views in M7, or four views (approvals, run timeline and needs-attention, evaluation results and regressions, alerts) plus generated static pages for the rest? Recommended: four views, to offset the larger sizes.
15. Recommended deferrals to offset the larger sizes (each needs your approval, none applied): model-judge calibration and drift watch to later; weekly digest and dormancy detail to stretch; domain circuit breaker (S29) to stretch; theme detection as a SQL count-distinct-accounts view instead of clustering.
16. Should the Agent SDK spike for the research node be dropped, with the research step simplified to a fixed-fetch single call?
17. Confirm that the audit hash chain moves from "later" into the MVP (small, and addresses tamper evidence).
