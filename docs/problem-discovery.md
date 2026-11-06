# Problem discovery

## 1. Method and its limits

I ran web searches on 2026-11-05 on four questions: what the Anthropic GTM AI Engineering role emphasises, how much rep time goes to non-selling work, how lead response time affects qualification, and what consulting pipeline benchmarks look like. I could not open primary reports, only search summaries and secondary pages. There were no interviews, no real CRM data, and no access to any company's internal workflows. Consequently:

- Problems in section 3 are **hypotheses grounded in general GTM practice**, not observed facts about a real firm.
- They are meant to be validated against the synthetic baseline and, if possible, with real practitioners (see open questions).

## 2. Evidence base

| # | Claim | Tag | Source and quality |
|---|---|---|---|
| E1 | Anthropic's GTM AI Engineering postings emphasise agents that run GTM work end to end across inbound, outbound, pipeline management and customer engagement; human oversight design; evaluation frameworks in development and production; and MCP servers connecting CRM, communications and data systems | **[F]** | Aggregator copies of the postings ([General Catalyst](https://jobs.generalcatalyst.com/companies/anthropic/jobs/91163623-staff-software-engineer-gtm-ai-engineering), [Built In](https://www.builtinchicago.org/job/ai-engineer-gtm-claudification/10863565)). Wording varies between listings; not Anthropic's own page. Says nothing about internal workflows. |
| E2 | Reps spend roughly 40% of their time selling; the rest goes to admin, data entry, internal meetings and content search | **[F, weak]** | Salesforce Trailhead module states 40% ([link](https://trailhead.salesforce.com/content/learn/modules/introduction-to-agentforce-sales/discover-the-modern-sales-landscape)); the underlying survey was not opened. Other sources put non-selling time at 40 to 60%. |
| E3 | In a field-sales survey, ~21% of rep time went to admin and data entry and ~9% to prospecting research (11% for B2B) | **[F, weak]** | Spotio survey, secondary ([link](https://spotio.com/blog/sales-statistics/)). Field sales, not consulting. |
| E4 | Faster response to web leads is associated with much higher qualification: HBR's 2011 audit of 2,241 firms found large gaps by response time, and only about 37% of firms replied within an hour while ~23% never replied | **[F, dated]** | Oldroyd et al., HBR 2011, via secondary summaries. The famous "21x within 5 minutes" figure is vendor platform data, often mislabelled, and is not used here. Association, not proof of cause. |
| E5 | Professional-services benchmarks: lead to opportunity ~25 to 40%, opportunity to proposal ~60 to 75%, proposal to close ~40 to 55%, lead to close ~6 to 12%; win rate ~28%, cycle ~51 days in one study | **[F, weak]** | Vendor blogs with thin methodology; the 28% figure may stem from one dataset ([Data-Mania](https://www.data-mania.com/blog/it-services-firm-gtm-benchmarks-2026/), [Prospeo](https://prospeo.io/s/consulting-sales-pipeline)). Used only to sanity-check synthetic data ranges. |
| E6 | Win-rate benchmarks mean little without a named denominator (per lead, opportunity, proposal) | **[F, weak]** | Same sources. Design consequence: the eval and dashboard define denominators explicitly. |
| E7 | *(added Phase 3)* A conference talk on GTM engineering frames the discipline as four areas: data, orchestration, agents (persistent account context, with agent-owned vs human-owned fields) and execution (reply routing, suppression, conflict prevention). See [gtm-engineering-framework.md](gtm-engineering-framework.md) | **[F, secondhand]** | Everett Berry, AI Engineer World's Fair 2026, as summarised by the project owner. I have not reviewed the talk itself. Used as design inspiration, not as evidence of effect sizes or of any company's internals. |
| E8 | *(added Phase 3b)* An interview with Clay's first GTM Engineer treats GTM as a product function: feedback from sales/marketing/CS becomes workflows and experiments; maturity stages (early to mature; matching capabilities to stage is my inference); "automate the manual, not the important". See [gtm-product-loop.md](gtm-product-loop.md) | **[F, secondhand]** | A Focal podcast episode (title and guest confirmed by a [listing](https://castbox.fm/episode/Why-GTM-Engineering-is-the-Future-%7C-When-to-Hire-Your-First-GTM-Engineer-%7C-How-to-Treat-GTM-Like-a-Product-%7C-How-Clay-Scaled-from-PLG-to-Enterprise-%7C-Automate-the-Manual%2C-Never-the-Important-with-Yash-Tekriwal%2C-Head-of-Education-at-Clay-id6619998-id882567834)); the content comes from the owner's summary, not a transcript I could read. |

**What the evidence does support:** the non-selling share of rep time is large, speed to respond matters, and enterprise vendors are investing in sales agents. **What it does not support:** any specific time-saving or revenue-uplift figure for Corvane. The impact model in later phases will use explicit assumptions.

## 3. Identified problems

Each problem states the symptom, a hypothesised root cause and the motion it affects. All are **[A]** until validated.

| ID | Problem statement | Motion | Evidence |
|---|---|---|---|
| P-01 | **Slow, inconsistent inbound triage.** Enquiries wait in a shared inbox until a BDR has time; response time varies by workload, which risks losing leads (E4). | Inbound | E4 plus **[A]** |
| P-02 | **Manual research before every judgement.** BDRs open several tabs to understand each company before deciding fit. This effort is repeated for each lead and each meeting (E3). | Inbound, Outbound, Customer | E2, E3 |
| P-03 | **Low-quality lead filtering.** A large share of enquiries are vendor pitches, recruiters or out of scope, consuming expensive qualification time. | Inbound | **[A]** |
| P-04 | **Duplicate and inconsistent CRM records.** The same person or company arrives via several channels and gets entered twice, so reporting and routing degrade. | All | **[A]** |
| P-05 | **Generic or slow outbound.** Personalisation requires research that reps rarely have time for, so outreach is either generic or infrequent. | Outbound | E2, E3 |
| P-06 | **Stalled deals discovered late.** Deals sit without activity until the weekly review or until the customer goes cold; no consistent definition of "stalled". | Pipeline | **[A]** |
| P-07 | **CRM hygiene debt.** Close dates, stages, next steps and values are stale or missing, so forecasts rely on rep memory and pipeline reviews are mostly data repair (E2). | Pipeline | E2 plus **[A]** |
| P-08 | **Pipeline review is manual narrative assembly.** Sales Director collects context per deal by asking people. | Pipeline | **[A]** |
| P-09 | **Meeting preparation is ad hoc.** Context is scattered across CRM, email, previous notes and delivery staff. | Customer | E2 plus **[A]** |
| P-10 | **Slow or lost follow-up and action items.** Notes are typed up late; commitments get missed. | Customer | **[A]** |
| P-11 | **Expansion signals go unnoticed.** Delivery staff hear needs that never reach the AE. | Customer | **[A]** |
| P-12 | **Handoff context loss** between BDR, AE, SA and delivery (see gtm-lifecycle.md section 3). | All | **[A]** |
| P-13 | **No measurement.** The firm cannot say which sources convert, how long deals dwell per stage, or what GTM effort costs. Denominators are undefined (E6). | All | E6 plus **[A]** |
| P-14 | **Stale, unattributed and conflicting account data** *(added Phase 3)*. Firmographics, contacts and signals come from several places with no record of source, age or confidence, so people cannot tell what to trust and automation acts on bad data. | All | E7 plus **[A]** |
| P-15 | **No durable account memory or coordinated execution** *(added Phase 3)*. Context about long-running accounts lives in people's heads, and outreach from different people or tools can collide, ignore suppressions, or go stale between systems. | Pipeline, Customer, Outbound | E7 plus **[A]** |
| P-16 | **Customer feedback is anecdotal and lost** *(added Phase 3b)*. Objections, requests and lost-deal reasons live in individual memories and notes, so the company cannot tell recurring patterns from one loud account, and offering owners rarely hear the pattern. | All | E8 plus **[A]** |
| P-17 | **Improvements and experiments are ad hoc** *(added Phase 3b)*. There is no shared backlog, no record of what was tried, and tests are run without a hypothesis, a control or a realistic view of sample size. | All | E8 plus **[A]** |

## 4. Inefficiency catalogue: where AI fits and where it does not

The decision test: *Is the logic fully specifiable as rules, and is the input structured?* If yes, use plain automation; AI is a liability there (cost, nondeterminism). Use an LLM where inputs are unstructured text and the output is a judgement or a draft. Use an **agent** (multi-step tool use with autonomy over its own steps) only when the sequence of steps depends on what it finds.

| Task | Nature | Best fit | Rationale |
|---|---|---|---|
| Parse form payload, normalise fields | Structured, deterministic | **Traditional automation** (n8n or code) | No judgement |
| Exact and fuzzy duplicate matching | Mostly rules plus similarity | **Automation**, with LLM only for ambiguous pairs | Cheap, testable |
| Spam and vendor-pitch screening | Text classification | **LLM call** (single step) | Unstructured text; structured output |
| Company and person research | Open-ended, variable steps | **Agent** (tool use: search, CRM lookup) | Path depends on findings |
| ICP fit scoring and routing recommendation | Judgement with rubric | **LLM call** with rules for hard constraints | Rubric plus evidence; human can override |
| Stalled-deal detection | Date and activity thresholds | **Automation** (SQL or rules) | Fully specifiable; no AI needed |
| Explaining why a deal is at risk and proposing a next step | Reading notes and emails | **LLM call** over retrieved context | Unstructured input |
| Missing-field and hygiene checks | Rules | **Automation**; LLM only to infer values from notes, as suggestions | Writes go through approval |
| Weekly pipeline digest | Aggregation plus narrative | **Automation computes numbers; LLM writes commentary** | Numbers must never be LLM-generated |
| Meeting brief | Retrieval plus summary | **LLM workflow** | Mostly single pass over retrieved context |
| Transcript to summary, actions, follow-up draft | Unstructured text | **LLM call** | Clear structured output |
| Outreach drafting | Generation from research | **LLM call**, human-approved | Tone and factual-claim risk |
| Expansion detection | Weak signals across sources | **LLM** with low confidence expectations | Data-poor, hard to evaluate |
| Sending messages, pricing, stage to Won, contracts | Commitment | **Human only** | Project principle |

A recurring design implication **[P]**: the majority of the value comes from *deterministic automation plus narrow LLM steps*, with a true agent loop justified for research only. The architecture should reflect that instead of defaulting to "an agent for everything".

## 5. Risks

| ID | Risk | Likelihood / impact **[A]** | Mitigation direction |
|---|---|---|---|
| R-01 | **Hallucinated facts** in research or drafts (invented company details, wrong people) | High / High | Source-linked claims, "unknown" as a valid output, factuality evals, human approval before any send |
| R-02 | **Unapproved external communication or commitment** | Low / Severe | No send capability in agent tools; outbox is draft-only; approval gate enforced in code, not in prompts |
| R-03 | **Wrong disqualification** of a good lead | Medium / High | Disqualify only as a recommendation (except clear spam); sample audit; track false negatives |
| R-04 | **Duplicate or corrupt CRM writes** | Medium / Medium | Idempotency keys, duplicate check before create, write via approved tool only, audit log |
| R-05 | **Prompt injection** from inbound emails, web pages, transcripts | Medium / High | Treat all external text as data; least-privilege tools; no tool that exfiltrates; injection test cases in the eval set |
| R-06 | **Confidential data leakage** across clients | Low / Severe | Scoped retrieval per account, role-based permissions, redaction in logs |
| R-07 | **Poor input data** limits quality (sparse notes, stale CRM) | High / Medium | Report data-quality metrics; evaluate with controlled data-quality variants |
| R-08 | **Cost and latency creep** from agent loops | Medium / Medium | Per-workflow budget caps, model routing, cost tracking per run |
| R-09 | **Automation bias**: reviewers approve without reading | Medium / High | Show evidence beside recommendations; sample audits; measure approve-without-edit rate |
| R-10 | **Approval backlog** makes the system a burden | Medium / Medium | Queue SLAs, batching, escalation, a visible queue-age metric |
| R-11 | **Over-fitting evaluation to synthetic data** | High / Medium | Hold-out scenarios, adversarial cases, documented limitations |
| R-12 | **Regulatory and ethical issues** with outbound (consent, GDPR/CAN-SPAM-type rules) and profiling | Medium / High | Draft-only outbound, source and opt-out checks, no sensitive-attribute inference. Legal review would be needed in a real deployment |
| R-13 | **Vendor and API dependency** (model changes, rate limits) | Medium / Medium | Retries with backoff, model version pinning, regression suite on each change |

## 6. Open questions for validation

1. Is the list of problems recognisable to people working in consulting sales? Could one or two practitioners review it?
2. What is Corvane's realistic inbound volume and spam share? Current assumption is ~120 per month and ~35% non-genuine, both **[A]** and both parameters.
3. Which CRM would a reader expect: HubSpot or Salesforce? (See the assumptions in the summary.)
4. How much should the case study show real LLM calls versus recorded fixtures, given cost limits?
