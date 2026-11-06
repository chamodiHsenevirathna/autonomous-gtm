# Use-case prioritisation

All four motions were evaluated before choosing an implementation order. Scores are **[P]**: my judgement against the criteria below, informed by the problem analysis. They are not measured values. The point of the scoring is to make the reasoning inspectable and challengeable, and a reviewer who disagrees can change a score and re-rank.

## 1. Method

Each candidate use case gets a 1 to 5 score on six criteria. For criteria where "high" is bad (complexity, risk, effort) the scale is inverted so that **5 is always favourable**.

| Criterion | Weight | 5 means | 1 means |
|---|---|---|---|
| Business value | 25% | Addresses a high-impact problem for several stakeholders | Marginal or speculative benefit |
| Automation potential | 20% | Most of the work can be done without a human | Mostly judgement or relationships |
| Data availability | 15% | Needed data exists in CRM or can be generated realistically | Needs data that is scarce, private or unavailable for free |
| Technical complexity (ease) | 15% | Single step, well-understood | Multi-system, ambiguous, hard to evaluate |
| Risk (safety) | 15% | Internal, reversible, low consequence | Customer-facing or commitment risk |
| Implementation effort (ease) | 10% | Days | Weeks, many integrations |

Weighted score = sum of (weight x score) / 100. Maximum 5.0. The arithmetic was computed with a script, not by hand.

## 2. Scored candidates

Columns: BV business value, AP automation potential, DA data availability, TC technical ease, RK risk safety, EF effort ease. "Type" is the recommended technique from [problem-discovery.md](problem-discovery.md) section 4.

| Rank | ID | Use case | Motion | Type | BV | AP | DA | TC | RK | EF | Score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | P1 | Stalled-deal detection | Pipeline | Rules | 5 | 5 | 4 | 5 | 5 | 5 | **4.85** |
| 2 | I1 | Intake normalisation and duplicate check | Inbound | Rules + similarity | 3 | 5 | 5 | 5 | 5 | 5 | **4.50** |
| 3 | P3 | CRM hygiene and duplicate checks | Pipeline | Rules + LLM suggestions | 4 | 4 | 5 | 4 | 4 | 4 | **4.15** |
| 3 | C1 | Meeting brief | Customer | LLM workflow | 4 | 4 | 4 | 4 | 5 | 4 | **4.15** |
| 5 | P4 | Weekly pipeline digest | Pipeline | SQL + LLM commentary | 4 | 4 | 4 | 4 | 4 | 4 | **4.00** |
| 6 | I3 | Qualification scoring and routing recommendation | Inbound | LLM + rules | 5 | 4 | 4 | 3 | 3 | 3 | **3.85** |
| 7 | O1 | Target-account research dossier | Outbound | Agent | 4 | 4 | 3 | 3 | 4 | 3 | **3.60** |
| 7 | I4 | Draft enquiry reply (gated) | Inbound | LLM | 3 | 4 | 4 | 4 | 3 | 4 | **3.60** |
| 7 | I2 | Lead enrichment brief | Inbound | Agent | 4 | 4 | 3 | 3 | 4 | 3 | **3.60** |
| 10 | P2 | Deal-risk explanation and next-action recommendation | Pipeline | LLM | 5 | 3 | 3 | 3 | 3 | 3 | **3.50** |
| 11 | C2 | Transcript to summary, actions, follow-up draft | Customer | LLM | 4 | 4 | 3 | 3 | 3 | 3 | **3.45** |
| 12 | O3 | Personalised outreach drafts (gated) | Outbound | LLM, approval | 4 | 4 | 3 | 3 | 2 | 3 | **3.30** |
| 13 | O4 | Autonomous outreach sending | Outbound | n/a | 3 | 5 | 3 | 3 | 1 | 3 | **3.10** |
| 14 | C3 | Expansion-opportunity detection | Customer | LLM | 4 | 3 | 2 | 2 | 3 | 2 | **2.85** |
| 15 | O2 | Buying-signal monitoring | Outbound | Agent + external feeds | 3 | 3 | 2 | 2 | 4 | 2 | **2.75** |
| 16 | C4 | Account health / churn-risk signals | Customer | LLM | 3 | 3 | 2 | 2 | 3 | 2 | **2.60** |

**O4 is excluded regardless of score.** Autonomous sending conflicts with the project's principles. Its score of 3.10 shows the scoring alone would not have caught this, which is why principle-based exclusions sit outside the model.

## 3. Sensitivity check

I re-ranked under three other weightings: equal weights, value-heavy (BV 40%) and safety-heavy (risk 30%).

- The **top two (P1, I1) are first and second under all four schemes**, and P3, C1 and P4 stay in the top six. The top group is robust.
- I3 (qualification) moves between 4th and 7th: value-heavy weighting puts it higher, safety-heavy lower. It is the most contested high-value item.
- O4, C3, O2 and C4 are in the bottom half under every scheme. C4 is last in all four.
- The middle (I2, I4, O1, P2, C2, O3) reorders by a few places; I treat these as roughly equal.

Limitations: the scores are one person's judgement, and a different reviewer could shift individual items by a point. The ordering of the middle group should not be over-interpreted.

## 4. Motion-level assessment

| Motion | Value | Main strength | Main weakness | Verdict |
|---|---|---|---|---|
| Inbound | High | Clear trigger, clear success label (qualified or not), fast feedback | Wrong disqualification risk; reply drafts need gates | **Implement first as the entry point** |
| Pipeline management | High | Much of it is deterministic; clear metrics; internal-facing so low risk | Value depends on CRM quality; needs opportunity data | **Implement second; quick wins** |
| Customer engagement | Medium to high | Briefs are internal and low-risk; transcripts are rich input | Needs transcripts and history; expansion detection is hard to evaluate | **Briefs and follow-ups third; defer expansion/health** |
| Outbound | Medium (high in theory) | Strong demonstration of research agents | Highest risk (external, reputational, compliance); needs data not available free; hard to measure impact without real sending | **Last; dossier and gated drafts only** |

## 5. Recommended implementation sequence

**[P]** Provisional; Phase 3 may adjust it.

| Step | Scope | Use cases | Why here |
|---|---|---|---|
| 0 | Shared foundations | Data model, simulated CRM, MCP CRM server, approval queue, audit log, cost tracking, evaluation harness skeleton, synthetic data generator | Every use case depends on them; the principles (approval, audit, evaluation) must exist before agents do |
| 1 | Inbound | I1, I2, I3, I4 | Creates the leads and opportunities that everything else consumes; first full demonstration of research, qualification and approval |
| 2 | Pipeline | P1, P3, P4, then P2 | Highest scores; mostly deterministic, so reliable early value; reuses the approval and CRM write paths proven in step 1 |
| 3 | Customer engagement | C1, C2 | Reuses account history and the approval queue; closes the loop back to the pipeline |
| 4 | Outbound | O1, O3 (gated) | Highest risk and weakest data; benefits from the research agent built in step 1 |
| Deferred | Expansion detection (C3), signal monitoring (O2), health scoring (C4), autonomous sending (O4: not planned) | n/a | Low score or principle exclusion; revisit if time allows |

Why not build P1 first, given its top score? It is quick and low risk, but a coordinated system needs a lead to flow through it, and inbound is where opportunities originate. P1 only needs opportunity rows, which the synthetic data generator provides from step 0, so it is deliberately the first thing built in step 2 and could be pulled forward as an early demo if wanted.

## 6. What would change this ranking

- Evidence that real inbound volume is small (<20 per month): inbound value falls and pipeline rises.
- Access to real or realistic transcripts: customer engagement scores improve on data availability.
- A cheap, legitimate enrichment source: outbound data score improves.
- Reviewer feedback that BDRs would reject LLM disqualification entirely: I3 becomes recommend-only everywhere (already the default).

## 7. Phase 3 addendum: enabling capabilities (scores above unchanged)

*Added after incorporating the GTM Engineering talk. The 16 scored use cases and their ranking are not revised.*

The talk's framing shows that several highly ranked use cases depend on **enabling capabilities** that were not scored because they are infrastructure, not user-facing use cases. They inherit priority from the use cases they unlock.

| Enabling capability | Unlocks | Why it is not a separate ranked item |
|---|---|---|
| Observations with provenance, waterfall, survivorship, freshness | I2, I3, O1, P3, C1 | Improves *data availability* (DA) scores for all of them. The DA scores assumed adequate data; this capability is how we create it in a controlled way |
| Entity resolution | I1, P3 | Already scored within I1 and P3; now designed explicitly |
| Durable orchestration and sync handling | All | Prerequisite |
| Persistent account agent and heartbeat | P1, P2, P4, C1, C3 | P1 (rules) stays deterministic; P2 and C3 gain a reasoning home. C3 stays deferred because its *evaluation* difficulty, not its architecture, is the obstacle |
| Execution gateway, suppression, claims | I4, O3, C2 | Raises the risk-safety (RK) scores of drafting use cases only if the gateway exists, a dependency, not a rescoring |

Sequence implications are in [implementation-roadmap.md](implementation-roadmap.md) section 4.

## 8. Phase 3b addendum: GTM product-loop use cases (same method; the 16 original scores unchanged)

Scored with the same six criteria and weights as section 1, computed by script. Scores are **[P]**, my judgement. They are not directly comparable evidence of value, because these items serve the GTM team and offering owners rather than the sales funnel.

| Rank in this group | ID | Use case | BV | AP | DA | TC | RK | EF | Score | Where it would sit among the original 16 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | F4 | Lost-deal reason capture (human-entered, AI-suggested tags) | 4 | 4 | 4 | 5 | 5 | 5 | **4.40** | Between I1 (4.50) and P3 (4.15) |
| 2 | F3 | GTM backlog with advisory scoring (human prioritises) | 4 | 3 | 4 | 4 | 5 | 4 | **3.95** | Between P4 (4.00) and I3 (3.85) |
| 3 | F5 | Insight digest and offering-owner handoff | 3 | 4 | 4 | 4 | 5 | 4 | **3.90** | Just above I3 |
| 4 | F1 | Feedback extraction with verbatim evidence | 4 | 4 | 3 | 4 | 4 | 4 | **3.85** | Level with I3 |
| 5 | X2 | Experiment results analysis and recommendation | 4 | 4 | 3 | 3 | 4 | 3 | **3.60** | Level with O1, I4, I2 |
| 6 | F2 | Recurring-theme detection | 4 | 3 | 3 | 3 | 4 | 3 | **3.40** | Between C2 (3.45) and O3 (3.30) |
| 6 | X1 | Experiment hypothesis and design drafting | 3 | 3 | 3 | 4 | 4 | 4 | **3.40** | As above |
| 8 | X3 | Autonomous experiment launch | 3 | 5 | 3 | 2 | 1 | 2 | **2.85** | **Excluded by principle** |

Notes:
- F4 scores high because it is mostly structured, human-entered and low risk; its automation score (4) reflects AI-suggested tags, not AI doing the core work. This matches "automate the manual, not the important".
- F2 scores lower than F1 despite depending on it, because theme quality is harder to evaluate and the data is sparse.
- Experiment items score in the middle because small volumes limit what can be concluded ([experimentation-engine.md](experimentation-engine.md) section 7).
- **Scope decision** ([maturity-and-scope.md](maturity-and-scope.md) section 3): F4, F1, F3 and basic F2 are MVP (milestone M6b); X1 and X2 are MVP-stretch as one simulated experiment (M8a); F5 is later. This adds scope to the original MVP, justified by reuse of already-planned machinery and by F4's score.
- No sensitivity analysis was run for this group.
- Reproducibility note for section 3: the alternative weightings were equal (16.7% each), value-heavy (BV 40, AP 20, DA 10, TC 10, RK 10, EF 10) and safety-heavy (BV 15, AP 15, DA 15, TC 15, RK 30, EF 10). An independent recomputation with renormalised weights put I3 at 5th to 6th rather than 4th to 7th, so treat I3's range as approximate.
