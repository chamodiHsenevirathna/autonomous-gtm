# Autonomous GTM: documentation index

An independent portfolio case study on using AI agents, workflow automation and integrations across the go-to-market (GTM) lifecycle of a **fictional** technology consulting company ("Corvane Digital", a placeholder name).

This is not an implementation for Anthropic or any real company. Nothing here describes the internal systems or workflows of Anthropic, Verdentra or any other organisation.

## Status

| Phase | Scope | Status |
|---|---|---|
| 1 | Discovery and research | **Complete** |
| 2 | Business and workflow analysis | **Complete** |
| 3 | Solution architecture | **Complete.** Reviewed against the requirements before implementation; extended with the GTM Engineering talk and the GTM-as-product interview (both known from summaries only) |
| 4 | Implementation | **Complete** on a simulated environment (see the root README) |
| 5 | Evaluation | **Complete** for the simulated system and mock model; real model performance untested |
| 6 | Demonstration dashboard | **Complete** (screenshots, diagrams and a recording in `portfolio/`) |

## Evidence policy

Every claim in these documents carries one of three tags. Reviewers should be able to see at a glance what is known, what is guessed and what is proposed.

| Tag | Meaning |
|---|---|
| **[F]** | Fact from a cited external source. The source's quality is stated; many are vendor blogs and are treated as indicative only. |
| **[A]** | Assumption about the fictional company or about GTM practice in general. Not verified. These become configurable parameters in the synthetic data and the ROI model. |
| **[P]** | Proposal or design opinion. This is my recommendation and is open to challenge. |

Where a number is quoted without a tag, it is a deliberate placeholder and is labelled as such.

## Document map

| Document | Phase | Content |
|---|---|---|
| [business-context.md](business-context.md) | 1 | Fictional company, services, buyers, sales model, systems landscape, scope |
| [gtm-lifecycle.md](gtm-lifecycle.md) | 1 | GTM lifecycle for a consultancy, handoffs, human decision points |
| [problem-discovery.md](problem-discovery.md) | 1 | Evidence base, inefficiencies, problem statements, AI vs plain automation, risks |
| [workflow-analysis.md](workflow-analysis.md) | 2 | Stakeholders, AS-IS and TO-BE Mermaid diagrams for all four motions |
| [use-case-prioritisation.md](use-case-prioritisation.md) | 2 | Scoring model, ranked use cases, sensitivity check, implementation sequence |
| [requirements.md](requirements.md) | 2 | Functional and non-functional requirements |
| [gtm-engineering-framework.md](gtm-engineering-framework.md) | 3 | **New.** The talk's four areas, mapping to our work, where we differ, MVP vs later |
| [solution-architecture.md](solution-architecture.md) | 3 | **Modified.** Seven shared layers, diagrams, golden thread, decisions AD-01 to AD-15 |
| [data-model.md](data-model.md) | 3 | **Modified.** Entities, ER diagram, entity resolution, waterfall, survivorship, field ownership |
| [orchestration.md](orchestration.md) | 3 | **New.** Graph nodes, semantics, retries, idempotency, CRM-to-outreach sync |
| [account-agents.md](account-agents.md) | 3 | **New.** Persistent account agents as event-driven virtual agents |
| [execution-architecture.md](execution-architecture.md) | 3 | **New.** Gateway, reply routing, suppression, claims, reputation controls |
| [technology-decisions.md](technology-decisions.md) | 3 | **New.** Option comparisons and recommended stack |
| [agent-specifications.md](agent-specifications.md) | 3 | **Modified.** Fourteen units with specs |
| [mcp-integrations.md](mcp-integrations.md) | 3 | **Modified.** Two risk-split MCP servers, permission profiles |
| [human-oversight.md](human-oversight.md) | 3 | **Modified.** Autonomy levels, gate catalogue, proposal lifecycle |
| [evaluation-strategy.md](evaluation-strategy.md) | 3/5 | **Modified.** Layers, metrics, 56 scenarios, provenance taxonomy, regression gates |
| [implementation-roadmap.md](implementation-roadmap.md) | 3/4 | **Modified.** Golden thread, milestones M0 to M8, risks, open decisions; addendum adds M6b and M8a |
| [gtm-product-loop.md](gtm-product-loop.md) | 3b | **New.** GTM as product function: feedback loop, feedback intelligence, backlog, org model |
| [experimentation-engine.md](experimentation-engine.md) | 3b | **New.** Governed experiments, statistics at small scale, examples |
| [maturity-and-scope.md](maturity-and-scope.md) | 3b | **New.** Maturity model, master MVP/later/out-of-scope table, human-led work |

## Key sources

Search-based research was done on 2026-11-05. Most statistics found came from secondary or vendor sources, and I could not open the primary reports. Treat them as order-of-magnitude indicators.

- Anthropic GTM AI Engineering postings, as reproduced by job aggregators (not Anthropic's own careers page): [General Catalyst listing](https://jobs.generalcatalyst.com/companies/anthropic/jobs/91163623-staff-software-engineer-gtm-ai-engineering), [Built In listing](https://www.builtinchicago.org/job/ai-engineer-gtm-claudification/10863565)
- Salesforce Trailhead, "Discover the Modern Sales Landscape" (40% of rep time spent selling): [link](https://trailhead.salesforce.com/content/learn/modules/introduction-to-agentforce-sales/discover-the-modern-sales-landscape)
- Spotio, "150+ Sales Statistics" (field-sales time-use survey, secondary): [link](https://spotio.com/blog/sales-statistics/)
- Oldroyd, McElheran, Elkington, "The Short Life of Online Sales Leads", Harvard Business Review, 2011 (lead response time). I did not open the original; I relied on secondary summaries.
- Data-Mania, "IT Services Firm GTM Benchmarks 2026" (vendor blog): [link](https://www.data-mania.com/blog/it-services-firm-gtm-benchmarks-2026/)
- Prospeo, "Consulting Sales Pipeline" (vendor blog): [link](https://prospeo.io/s/consulting-sales-pipeline)

- Everett Berry, "GTM Engineering: The Technical Bits", AI Engineer World's Fair 2026. A [speaker page](https://ai.engineer/speakers/everett-berry) confirms the appearance. **Talk content in these docs comes from the project owner's written summary only**; I have not watched or read the talk. We learn from its engineering principles and do not claim to describe Clay's internal architecture.
- Focal podcast episode "...Automate the Manual, Never the Important" with Yash Tekriwal (spelled "Techal" in the brief), Clay's first GTM Engineer and Head of Education, listed 2025-12-11: [Castbox listing](https://castbox.fm/episode/Why-GTM-Engineering-is-the-Future-%7C-When-to-Hire-Your-First-GTM-Engineer-%7C-How-to-Treat-GTM-Like-a-Product-%7C-How-Clay-Scaled-from-PLG-to-Enterprise-%7C-Automate-the-Manual%2C-Never-the-Important-with-Yash-Tekriwal%2C-Head-of-Education-at-Clay-id6619998-id882567834). **No transcript reached me**; interview content comes from the owner's summary only.

## Change log

| Date | Change |
|---|---|
| 2026-11-05 | Phases 1 and 2: discovery and workflow analysis (14 files) |
| 2026-11-06 | Phase 3: incorporated the GTM Engineering talk. New: gtm-engineering-framework, orchestration, account-agents, execution-architecture, technology-decisions. Rewritten stubs: solution-architecture, data-model, agent-specifications, mcp-integrations, human-oversight, evaluation-strategy, implementation-roadmap. Appended (existing content preserved): problem-discovery, workflow-analysis, requirements, use-case-prioritisation, this README |
| 2026-11-06 | Phase 3b: incorporated the GTM-as-product interview (as summarised). New: gtm-product-loop, experimentation-engine, maturity-and-scope. Appended (existing content preserved): solution-architecture, data-model, orchestration, account-agents, execution-architecture, human-oversight, evaluation-strategy, agent-specifications, mcp-integrations, technology-decisions, implementation-roadmap, requirements, use-case-prioritisation, problem-discovery, business-context, workflow-analysis, gtm-engineering-framework |
| 2026-11-06 | Phase 3c: design review findings integrated. Amended (sections appended, plus targeted corrections): data-model, orchestration, execution-architecture, human-oversight, mcp-integrations, evaluation-strategy, requirements, implementation-roadmap, solution-architecture, account-agents, gtm-engineering-framework, gtm-product-loop, maturity-and-scope, experimentation-engine, use-case-prioritisation, problem-discovery |

