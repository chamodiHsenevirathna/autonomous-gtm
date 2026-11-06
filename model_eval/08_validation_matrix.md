# 8. What can and cannot be validated without paid API access

**Real commercial model performance (Claude or any other) remains untested.** Everything below was measured with a deterministic mock, deliberately faulty test doubles, or static checks. Total external API spend for this phase: **$0.00**. No API call was made, no key was read, no paid service used. Live mode is disabled, and a lock file (`ZERO_COST_LOCK.md`) makes the live client refuse real-network use before it touches any key.

| Question | Can we answer it at $0? | How, and how far | Evidence label |
|---|---|---|---|
| Does the workflow (intake, approval, gateway, audit, dashboard) behave as designed? | **Yes** | 416-test suite + 28 scenarios against the real system, reproduced after this phase's code changes | measured on simulation |
| Does lead handling follow the owner's confidence and account-routing policies? | **Mostly (gaps listed)** | 27 unit tests, 8 policy evaluation cases, full regression; gaps (promotional/transactional split, support routing, timing extraction, priority) are documented in `10`, section 2 | measured on simulation; gaps not built |
| Do the safety controls hold if a model misbehaves? | **Yes, by construction** | Agents have no send/merge/decide tools; hard ICP limits only downgrade; approvals are hash-bound; gateway is the only door. Scenarios attack these without a model | machinery check |
| Does the evaluation harness itself work and detect failures? | **Yes** | Seven deliberately bad doubles (injection-compliant, fabricator, sloppy router, over-qualifier, schema breaker x2, inconsistent) are each caught by the expected metric; tests assert it | harness validation (not model quality) |
| Is the live client code correct against the real API? | **Partly** | Fixed offline and tested against `httpx.MockTransport` (no forced tool choice, task prompts, per-model prices, budget and per-request cost caps enforced before sending, refusal/max-tokens classes, recording). The mock transport encodes **my reading of the API docs**; whether the real service accepts each request has never been checked | static / mock-transport only |
| Does a real model follow the rubric, resist injection, ground its claims, stay consistent? | **No** | Needs a real model | untested |
| Is Claude better or worse than the mock? | **No** | Needs paid calls | untested |
| Do the live task prompts work? | **No** | They are written and unit-checked for presence only; effectiveness is unknown | untested |
| Real cost, latency, rate limits, refusals, truncation | **No** | The estimator is informational; token counts are a heuristic | untested; estimate only |
| Is the dataset good at separating weak from strong behaviour? | **Partly** | On dataset v4 the mock fails 6 of 68 cases on the primary criteria (recruiter pitch, phishing, German injection, a billing query it does not hold, off-service qualification, markup noise) and the doubles fail the metrics they target. A local 3B model could add a second data point (`07`), not a Claude one | measured on simulation |
| Labels correct? | **Partly** | Self-review plus a blind pass by an automated reviewer (not a human); v4: 21 ground-truth (simulation-defined), 20 judgement, 14 ambiguous, 13 policy; blind automated-reviewer pass (`09`) and owner policy decisions (`10`) applied; 5 cases remain contested and one is partly open; human review pending | author judgement |
| Business impact (conversion, speed, revenue) | **No, and not even with an API** | Needs real leads, real outcomes and time | not measurable here |

## Mock-model results on dataset v4 (the only model-behaviour numbers in this repo)
68 cases (v4: after the final business-policy decisions), 3 repeats (204 calls), cost $0. Rates are over distinct cases; intervals are 95% Wilson. **Mock results, not Claude results. Measured on 68 synthetic cases whose labels are partly the author's judgement.** Earlier runs (v1 to v3) are kept in `results/` and were produced under earlier labels or code.

| Task | Result |
|---|---|
| triage (n=23) | exact label 0.65; within acceptable set 0.83; injection flagged 4 of 5, 0 false flags; **must-hold cases (spam/phishing, unclear-only, injection) held 7 of 10** (misses: phishing without spam keywords, German-language injection, a billing query the mock calls `genuine`); no genuine enquiry held |
| qualify (n=27) | **routing correct 0.96 (0.82 to 0.99)**; final band correct 1.0; band agreement 0.74 (every world-`medium` enquiry is scored `high`); injection never raised the band; no invented numbers. **9 cases with low-confidence, missing-confidence or unknown mandatory facts: all flagged for verification, none held or disqualified because of them** |
| research (n=9) | 19 claims, all cited supplied pages; lexical support 1.0; injected pages flagged 2 of 2; markup/cookie text leaked into claims in 1 case |
| account routing (n=9) | required action present 9 of 9 under the policy labels; no forbidden action; every action carried evidence |
| structured output | 100% valid first attempt; consistency 1.0 (deterministic mock: checks the harness only) |
| fails on primary criteria | 6 of 68: `T-recruiter-subtle`, `T-inj-german`, `T-phish-verify`, `T-ambig-existing-customer` (policy-driven, new), `Q-off-service`, `R-html-noise` |
| pass rate on reliable labels (n=41) / contestable (n=27) | 0.90 (0.78 to 0.96) / 0.93 (0.77 to 0.98) |

Caveat that matters: injection resistance, claim support and consistency are 1.0 for the mock **by construction**. Those rows say nothing about a real model. The policy-hold rows measure the *production gate fed with mock output*; they do not show how a real model would triage.

## Test-double results (harness validation, dataset v4; `results/doubles_v4/`)
| Double | Failure it simulates | Metric that caught it |
|---|---|---|
| injection_compliant | obeys injected text | triage injection recall 0.0; qualify injection success on 2 cases; injected sentences appear as claims |
| fabricator | invents facts and sources | 8 unsupported claims (v3, per distinct case); citation validity below 1; invented numbers; missing unknowns |
| sloppy_router | drafts/CRM-creates regardless, no evidence | forbidden actions on 7 cases; actions without evidence |
| over_qualifier | everything is high | low-fit held falls; wrongly qualified cases listed |
| schema_breaker_repairable | invalid output, valid on repair | first-attempt validity 0.0, after repair 1.0 |
| schema_breaker_always | never valid | all 130 calls fail, error class recorded |
| inconsistent | flips between runs | triage consistency 0.22 |
