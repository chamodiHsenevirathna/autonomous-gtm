# Workflow analysis

AS-IS workflows are **[A]**: a typical manual process for a small consultancy, not an observed one. TO-BE workflows are **[P]**. Pain points reference the problem IDs in [problem-discovery.md](problem-discovery.md). Diagram conventions: rounded boxes are start/end, rectangles are steps, diamonds are decisions, and nodes marked **(H)** are human steps. In TO-BE diagrams, "Approval gate" nodes are mandatory human checkpoints.

## 1. Stakeholder analysis

| Stakeholder | Goals | Concerns about AI | Role in the system | Influence |
|---|---|---|---|---|
| Sales Director / Head of Growth | Predictable pipeline, accurate forecast, control of discounts | Loss of control; wrong numbers in forecasts | Approver for stage, value and escalation; consumer of digests | High |
| Account executives | Close deals, less admin | Spammy outreach harming relationships; being second-guessed | Approve outreach, accept or reject recommendations | High |
| BDRs | Hit meeting targets, clear queue | Being replaced; extra review work | Review qualification, handle edge cases | High |
| Solution architects | Valid scoping, fewer low-fit meetings | Wrong technical claims | Consume briefs; verify technical content | Medium |
| Delivery leads | Realistic commitments, protect capacity | Sales promising unavailable capacity | Consulted on expansion and capacity; never bypassed | Medium |
| RevOps / marketing ops | Clean data, working routing | Agents corrupting CRM; schema drift | Owns CRM schema, routing rules, permissions | High |
| Prospects and customers | Relevant, honest, timely contact | Spam, wrong facts, privacy | Indirectly affected | n/a |
| Legal / finance | No unapproved commitments, compliance | Unauthorised terms, data misuse | Sets policies the gates enforce | Medium |
| Executive sponsor | Measurable return, bounded risk | Cost, reputational incident | Receives metrics | High |
| (Case-study reader) | Credible engineering | Hand-waving, fake results | Evaluates this repository | n/a |

**Design implication [P]:** the highest-influence stakeholders worry about *loss of control* and *data corruption*, not about quality of prose. Approval gates, audit trails and CRM write safety get priority over output polish.

## 2. Motion 1: Inbound

### AS-IS

```mermaid
flowchart TD
    S([Enquiry arrives: form, email, referral]) --> M[Lands in shared inbox or CRM form queue]
    M --> W[Waits for BDR availability]
    W --> R1["(H) BDR reads enquiry"]
    R1 --> D1{"(H) Obvious spam or vendor?"}
    D1 -->|Yes| X([Delete or ignore])
    D1 -->|No| R2["(H) Search CRM for existing contact/account"]
    R2 --> R3["(H) Research company: website, LinkedIn, news"]
    R3 --> D2{"(H) Fit with services, size, timing?"}
    D2 -->|Poor| N([Polite decline or nurture])
    D2 -->|Good| C["(H) Create or update CRM records by hand"]
    C --> RT["(H) Decide owner, message AE on Slack/email"]
    RT --> RP["(H) Write reply, propose call"]
    RP --> E([Call booked or lead lost])
```

Pain points: wait time (P-01), repeated research (P-02), time spent on junk (P-03), duplicates created at "Search CRM" and "Create" (P-04), context dropped at routing (P-12).

### TO-BE

```mermaid
flowchart TD
    S([Enquiry arrives: webhook or email]) --> A1[Normalise payload and validate - automation]
    A1 --> A2[Duplicate check: exact and fuzzy match - automation]
    A2 --> D0{Duplicate found?}
    D0 -->|"Exact"| LNK[Link to existing record, notify owner]
    D0 -->|"Ambiguous"| Q1[["Approval gate: confirm match or create new"]]
    D0 -->|"None"| SP[Spam and vendor screen - LLM classifier]
    SP --> D1{Clear spam?}
    D1 -->|"High confidence"| LOG([Archive with reason, audit logged, sampled for review])
    D1 -->|"No"| RS[Research agent: public sources and CRM history, source-linked brief]
    RS --> QL[Qualification: rules for hard constraints, LLM for fit against ICP rubric]
    QL --> RO[Routing recommendation: owner by territory and service line]
    RO --> DR[Draft reply for human to edit]
    DR --> Q2[["Approval gate: BDR reviews score, evidence, route and draft"]]
    LNK --> Q2
    Q1 --> Q2
    Q2 -->|Approve or edit| WR[Create or update CRM through MCP tool, audit logged]
    Q2 -->|Reject| FB[Record reason as feedback for evaluation]
    WR --> SEND["(H) Human sends reply"]
    SEND --> E([Lead owned, next step set])
```

Automation versus AI: steps 1 to 2 are deterministic; spam screening and fit judgement are single LLM calls; research is the only agentic loop. The agent never sends the reply. A human sends it from their own client, or presses send on an approved draft.

## 3. Motion 2: Outbound

### AS-IS

```mermaid
flowchart TD
    S([Quarterly or ad hoc target list]) --> L["(H) Build list from LinkedIn, events, past clients"]
    L --> R["(H) Skim account: website, news, job posts"]
    R --> D1{"(H) Time to personalise?"}
    D1 -->|No| T["(H) Send templated email"]
    D1 -->|Yes| P["(H) Write custom message"]
    T --> SQ["(H) Manual follow-ups, maybe in a sequencing tool"]
    P --> SQ
    SQ --> RE{Reply?}
    RE -->|Yes| H["(H) Hand to AE or inbound path"]
    RE -->|No| FIN([Fades out, rarely recorded])
```

Pain points: personalisation skipped under time pressure (P-05), little record of what was tried (P-13), reply handling inconsistent (P-12).

### TO-BE

```mermaid
flowchart TD
    S([Approved ICP and target list]) --> DD[Duplicate and do-not-contact check against CRM - automation]
    DD --> RS[Account research agent: dossier with sources, tech and hiring signals, confidence]
    RS --> HY[Hypothesis: which service line, which trigger, which persona]
    HY --> Q1[["Approval gate 1: AE confirms account is worth pursuing"]]
    Q1 -->|Approve| DR[Draft personalised message variants, claims linked to sources]
    Q1 -->|Skip| LOG([Reason recorded])
    DR --> CK[Automated claim check: every factual statement traced to a source]
    CK --> Q2[["Approval gate 2: AE edits and approves each message"]]
    Q2 -->|Approve| OB[Placed in outbox as approved draft]
    OB --> SEND["(H) Human sends, or send step enabled only after approval and within rate limits"]
    SEND --> TR[Log activity in CRM, schedule follow-up reminder]
    TR --> RE{Reply?}
    RE -->|Yes| IN[Route into inbound qualification workflow]
    RE -->|No| FU[Suggest follow-up draft after N days, approval required]
```

Note **[P]**: In the case study, the "send" is a simulated outbox. Even in a production version, sending is a separate, permissioned action that the agents cannot invoke.

## 4. Motion 3: Pipeline management

### AS-IS

```mermaid
flowchart TD
    S([Weekly pipeline review]) --> E["(H) Export CRM report"]
    E --> AS["(H) Ask each AE for status"]
    AS --> CH["(H) Fix stale stages, dates and values live in the meeting"]
    CH --> RK{"(H) Which deals feel at risk?"}
    RK --> A1["(H) Ad hoc nudges to AEs"]
    A1 --> FC["(H) Manual forecast spreadsheet"]
    FC --> E2([Review ends; data decays until next week])
```

Pain points: stalled deals found late (P-06), review time spent on data repair (P-07), narrative assembled by hand (P-08), definitions inconsistent (P-13).

### TO-BE

```mermaid
flowchart TD
    T([Scheduled daily scan, plus CRM change events]) --> R1[Rules engine: no activity N days, close date passed, no next step, single contact, stage dwell above threshold - automation]
    R1 --> R2[Hygiene check: missing or inconsistent fields, duplicates - automation]
    R2 --> D{Any flags?}
    D -->|No| END([Nothing to do])
    D -->|Yes| CX[Retrieve context: notes, emails, meeting history for flagged deals]
    CX --> LL[Risk explanation and next-action recommendation - LLM, evidence cited]
    LL --> Q1[["Approval gate: AE accepts, edits or dismisses"]]
    Q1 -->|Accept data fix| WR[CRM update through MCP tool, audit logged]
    Q1 -->|Accept action| TK[Create task or reminder for the AE]
    Q1 -->|Dismiss| FB[Reason recorded, tunes thresholds]
    WR --> DG
    TK --> DG
    FB --> DG
    DG[Weekly digest: numbers computed by SQL, commentary by LLM] --> SD["(H) Sales Director reviews, with escalation list"]
    SD --> ST[["Approval gate: stage moves to Won/Lost and forecast category changes are human-only"]]
```

Rule of thumb **[P]**: the numbers in the digest are computed by queries, never by the model. The LLM explains and recommends; it does not calculate.

## 5. Motion 4: Customer engagement

### AS-IS

```mermaid
flowchart TD
    S([Customer meeting scheduled]) --> PR["(H) Hunt for context: CRM, inbox, past notes, ask delivery lead"]
    PR --> MT["(H) Meeting; notes by hand or recorded"]
    MT --> FN["(H) Write up notes, often later"]
    FN --> AC["(H) Email follow-up, create tasks by hand"]
    AC --> CRM["(H) Update CRM if remembered"]
    CRM --> EX{"(H) Spot expansion need?"}
    EX -->|"Sometimes, if noticed"| OPP["(H) Raise new opportunity"]
    EX -->|"Often missed"| LOSS([Signal lost])
```

Pain points: heavy preparation (P-09), late and incomplete follow-up (P-10), expansion signals missed (P-11), CRM stale (P-07).

### TO-BE

```mermaid
flowchart TD
    CAL([Calendar event with customer contacts]) --> BR[Brief agent: pulls account history, open actions, stakeholders, delivery notes, recent public news]
    BR --> BO[Meeting brief delivered to AE, no approval needed: read-only, internal]
    BO --> MT["(H) Meeting happens; transcript ingested"]
    MT --> SM[Transcript processor: summary, decisions, action items, questions, risks, with quotes as evidence]
    SM --> FU[Draft follow-up email]
    SM --> CU[Proposed CRM updates: notes, next step, contacts]
    SM --> EX[Expansion and risk signals with evidence and confidence]
    FU --> Q1[["Approval gate: AE edits and sends follow-up"]]
    CU --> Q2[["Approval gate: AE approves CRM changes"]]
    EX --> Q3[["Approval gate: AE and delivery lead decide whether to open an opportunity"]]
    Q2 --> WR[CRM write via MCP, audit logged]
    Q3 -->|Approve| NO[New opportunity in Qualified stage with evidence attached]
```

Meeting briefs are read-only and internal, so they carry no approval gate; everything that writes data or leaves the company is gated.

## 6. How the four motions connect (the "coordinated system")

The purpose is one shared record per account, not four chatbots **[P]**.

```mermaid
flowchart LR
    Shared[("Shared data: accounts, contacts, opportunities, activities, documents")]
    IN[Inbound] -->|creates leads, qualified opportunities| Shared
    OUT[Outbound] -->|activity, replies| Shared
    OUT -->|replies| IN
    Shared -->|opportunities| PL[Pipeline]
    PL -->|flags, tasks, data fixes| Shared
    Shared -->|account history| CE[Customer engagement]
    CE -->|notes, signals, new opportunities| Shared
    CE -->|expansion opportunities| PL
    Shared --> AP[Approval queue and audit log]
    AP -->|approved writes| Shared
    Shared --> MON[Metrics, evaluation, cost tracking]
```

Concrete cross-motion handoffs:

| From | To | What flows | Why it matters |
|---|---|---|---|
| Outbound | Inbound | A reply to outreach enters qualification as a lead with the dossier attached | No re-research; consistent scoring |
| Inbound | Pipeline | Approved qualified lead becomes an opportunity with owner and source | Pipeline monitoring starts on day one |
| Pipeline | Customer | Deal at risk triggers a brief that highlights open issues | Meeting prep uses risk context |
| Customer | Pipeline | Approved expansion signal creates an opportunity | Closes the land-and-expand loop |
| All | Metrics | Every agent run records cost, latency and outcome | Business impact measured per motion |

## 7. Exception scenarios (carried into Phase 3)

| Scenario | Expected behaviour |
|---|---|
| Duplicate with conflicting data | Do not overwrite; raise match-confirmation gate |
| Research finds nothing reliable | Output "insufficient evidence"; route to human; never fabricate |
| Enquiry contains instructions aimed at the model | Treated as data; flagged in the audit log |
| CRM API failure or timeout | Retry with backoff, then park the run and alert; no partial writes |
| Approver never responds | Escalate after SLA; item expires safely without action |
| Approver edits a draft | Final human version is what is stored; diff retained for evaluation |
| Out-of-region or out-of-scope request | Recommend decline or referral; human decides |
| Transcript contains pricing talk | Summarise only; flag as commercial content; never propose terms |
| Same lead arrives twice within minutes | Idempotency key prevents double processing |
| LLM returns invalid structured output | Validate, retry once with the error, then fail safe to human review |

## 8. Phase 3 amendments (diagrams above unchanged)

*Added after incorporating the GTM Engineering talk. The TO-BE workflows above remain the intended business flows; Phase 3 changes how they are realised.*

| TO-BE element above | Phase 3 realisation |
|---|---|
| Inbound "Research agent: public sources and CRM history" | Split into a deterministic **enrichment waterfall** with provenance ([data-model.md](data-model.md) section 6) plus a bounded research agent only for facts the waterfall cannot supply |
| Inbound "Duplicate check" | Three-band entity resolution; merges are proposals ([data-model.md](data-model.md) section 5) |
| Pipeline "Scheduled daily scan" | Per-account **heartbeat** with a change detector ([account-agents.md](account-agents.md) section 5); rules still produce the stall flags |
| Pipeline/Customer "CRM update through MCP tool" | The agent creates a proposal; the **execution gateway** performs the approved write under field-ownership rules |
| Outbound "Human sends, or send step enabled only after approval and within rate limits" | Settled as: send is a human-initiated action performed by the gateway for the exact approved payload; sequences use just-in-time approval ([execution-architecture.md](execution-architecture.md) section 5) |
| Outbound "Reply: route into inbound" | Reply router with automatic suppression and sequence stops ([execution-architecture.md](execution-architecture.md) section 4) |
| Exception "CRM API failure or timeout: retry then park" | Extended with sync-lag waits and bounded polling ([orchestration.md](orchestration.md) section 7) |

New stakeholder consideration **[P]**: RevOps gains responsibility for the field-ownership policy and match/merge decisions, which raises its influence in the system.

## 9. Phase 3b: the learning loop as a fifth, cross-cutting workflow

The four motions are unchanged. A cross-cutting **learning loop** consumes what they produce. It is a set of shared-service workflows, not a fifth agent.

```mermaid
flowchart TD
    M1[Inbound, Outbound, Pipeline, Customer workflows] --> D[Interactions, signals, lost-deal reviews]
    D --> X[Feedback extraction with verified quotes]
    X --> T[Theme refresh: distinct accounts, watch list]
    T --> G11[[G11 theme confirmation]]
    G11 --> B[Backlog item]
    B --> G12[[G12 priority, human-owned]]
    G12 --> S{Solution type}
    S -->|Workflow, rubric or data fix| C[Change via code review and regression suite]
    S -->|Needs testing| E[Experiment: G14 design, G15 launch, per-message approvals]
    S -->|Offering feedback| H[Handoff to service-line or delivery lead]
    C --> ME[Measure]
    E --> ME
    H --> ME
    ME --> G16[[G16 decision]]
    G16 --> B
    HL[Human-led work: debriefs, interviews, discovery calls] --> D
```

| Stakeholder | Role in the loop |
|---|---|
| GTM Engineer (new, central team) | Confirms themes, triages backlog, designs experiments, ships workflow changes |
| Director | Approves high-impact priority and experiment launch |
| AEs and BDRs | Source of feedback; enter lost-deal reasons; run debriefs |
| Service-line and delivery leads | Receive offering-level themes and respond |
| RevOps | Keeps taxonomy and ICP definition consistent |

AS-IS (**[A]**): lost reasons are a free-text CRM field, rarely filled; feedback is discussed in meetings and forgotten; improvement ideas are raised ad hoc; tests are informal. Pain points: P-16, P-17.
