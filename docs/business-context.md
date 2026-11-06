# Business context

Everything about Corvane Digital is **[A]** (invented for this case study). The figures are plausible placeholders chosen to make the scenarios realistic. They are parameters, not findings, and the synthetic data generator and ROI model will read them from one config file.

## 1. The company

**Corvane Digital** is a fictional mid-sized technology consultancy (~250 staff, offices in three regions, **[A]** ~USD 40M revenue) selling project-based and retainer engagements.

### Service lines

| Line | Typical engagement | Typical size **[A]** | Typical buyer |
|---|---|---|---|
| AI and agent development | Use-case discovery, prototype, production build, LLM evaluation | $60k to $400k | CTO, Head of Data/AI, Head of Operations |
| Cloud engineering | Landing zones, migrations, FinOps, platform engineering | $80k to $600k | CTO, VP Engineering, Head of Infrastructure |
| Data engineering | Lakehouse, pipelines, governance, BI enablement | $70k to $500k | CDO, Head of Data |
| Application modernisation | Legacy re-platforming, API enablement | $100k to $800k | CIO, VP Engineering |
| Technology consulting | Roadmaps, architecture reviews, vendor selection | $20k to $120k | CIO, COO, CFO |

### Commercial model **[A]**

- Mostly fixed-scope projects after a paid or unpaid discovery phase, plus time-and-materials and managed-service retainers.
- Sales cycle 45 to 120 days, longer for modernisation. The first deal with a logo is often a small consulting or discovery engagement ("land"), followed by a build ("expand").
- Revenue comes from **new logos** and **existing-customer expansion**. For consultancies, repeat work typically makes up a large share, but I have no sourced figure, so the model treats the split as a parameter (default 60% existing, 40% new).
- Delivery capacity is the binding constraint. Sales cannot promise start dates or staffing without delivery. This is why pricing and commitments stay with humans.

## 2. GTM organisation **[A]**

| Role | Headcount | GTM responsibility |
|---|---|---|
| Head of Growth / Sales Director | 1 | Targets, forecast, pipeline reviews, approves discounts |
| Business development reps (BDR) | 2 | Inbound triage, outbound prospecting |
| Account executives / engagement partners | 5 | Own opportunities and key accounts |
| Solution architects (shared with delivery) | 4 | Technical discovery, estimates, proposals |
| Delivery leads | 3 | Capacity, staffing, feasibility, customer health |
| Revenue operations / marketing ops | 1 | CRM admin, routing rules, reporting |
| Legal/finance (on demand) | n/a | Contract terms, pricing sign-off |

The small headcount is deliberate: in lean teams like this, manual research, copy-pasting between systems and inconsistent CRM updates take a large share of each person's week **[A]**.

## 3. Systems landscape **[A]**

| Capability | Likely real-world system | Case-study stand-in |
|---|---|---|
| CRM | HubSpot or Salesforce | Simulated CRM (Postgres plus REST) with a HubSpot-compatible shape; optional HubSpot free CRM adapter |
| Web forms and inbox | Website forms, shared mailbox | Webhook payloads, synthetic emails |
| Meeting recordings and transcripts | Zoom, Teams, Gong-style tools | Synthetic transcripts |
| Calendar | Google/Microsoft calendar | Synthetic events |
| Proposals and docs | Google Docs, PowerPoint | Out of scope |
| Enrichment | LinkedIn, Apollo, Clearbit-style tools (paid) | Synthetic firmographic dataset; optional public-web lookups |
| Delivery and capacity | Resource management tool | Out of scope; treated as a human check |
| Communication | Email, Slack | Draft-only outbox plus approval queue |

Free or low-cost principle: no paid enrichment or sending services are assumed. Where real data would be needed, a synthetic dataset stands in, and the limitation is documented in the evaluation.

## 4. Why a consultancy is a distinct GTM problem

These are structural observations about consulting sales **[A]**, not sourced findings:

1. **Low volume, high value.** Dozens of deals, not thousands. One wrongly handled lead is expensive, so precision matters more than throughput.
2. **Bespoke scoping.** Deals depend on a technical conversation, so the deal record is unstructured: notes, emails, transcripts.
3. **Relationship-led.** Trust and referrals matter, so tone mistakes and over-automation carry reputational risk.
4. **Capacity-constrained.** A "yes" must be checked against delivery availability.
5. **Land and expand.** Customer engagement is a revenue motion, not only a service motion.
6. **Sparse, messy data.** Small teams have thin CRM discipline, which limits what AI can reliably infer.

## 5. Scope of the case study

**In scope:** the four GTM motions (inbound, outbound, pipeline management, customer engagement) as a coordinated system over shared customer and opportunity data, with human oversight, evaluation and monitoring.

**Out of scope:** marketing campaigns and content, contracting and billing, delivery and staffing, real third-party integrations that require paid accounts, and any real customer data.

## 6. Success measures (proposed)

Defined here so Phases 3 to 6 are judged against them. Targets are **[P]** and will be set against measured baselines on the synthetic data, not assumed.

| Dimension | Metric |
|---|---|
| Speed | Median time from enquiry to qualified-and-routed |
| Quality | Qualification agreement with a labelled ground-truth set; research factuality score |
| Safety | Approval-gate compliance (target 100%), zero unapproved external sends |
| Data | Duplicate-creation rate, CRM write success rate, field completeness |
| Pipeline | Stalled-deal detection recall and precision; time-to-flag |
| Efficiency | Rep minutes saved per workflow (estimated from task timings, labelled as an estimate) |
| Cost | LLM cost per completed workflow |
| Reliability | End-to-end workflow success rate, retry rate, p95 latency |

Business impact figures will be modelled from stated assumptions and clearly labelled as modelled, not measured.

## 7. Phase 3b amendment: GTM engineering function and maturity **[A]**

Additions to the fictional company; nothing above changes.
- **GTM Engineering function:** 1 to 2 people (the owners of this system), one of whom may be the existing RevOps person part-time. This is a **centralised team** serving Sales, Delivery, Marketing and RevOps.
- **Maturity:** the GTM organisation (~12 people) is at a **growing** stage ([maturity-and-scope.md](maturity-and-scope.md)). Enterprise structures (embedded engineers, governance boards, self-service platforms) are deliberately absent.
- **"Product" analogue:** Corvane sells services, not software, so customer-feedback themes are routed to service-line leads, delivery leads and marketing.
- **Volumes used for experiment feasibility:** ~200 outbound contacts per month and ~120 inbound enquiries per month, both assumptions and both configuration parameters.
