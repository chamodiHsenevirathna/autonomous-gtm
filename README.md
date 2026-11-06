# Autonomous GTM

A go-to-market automation system for a **fictional** technology consultancy ("Corvane Digital"): inbound lead qualification, account
intelligence, human approval and controlled execution. Software agents prepare the work; a person approves every action that
touches the outside world.

> **Scope.** All data is synthetic, and the CRM, outreach tool, data providers and customer replies are simulators. The model is a
> deterministic mock, so real language-model performance is untested; no live model call has been made. No business outcome
> (conversion, revenue, productivity) was measured. There is no production CRM integration, and this is a demonstration, not a
> production system. See [Limitations](#limitations).

Python 3.12, FastAPI, PostgreSQL 16, React + TypeScript | 416 backend tests | 28 end-to-end scenarios | 10 system invariants

New here? Read the [five-minute executive summary](docs/case-study.md#executive-summary-five-minute-read).

## The problem

Go-to-market work is a chain of handoffs: an enquiry arrives, someone identifies the company, checks fit, writes to the prospect,
updates the CRM and later reads the reply. Automating it with agents is easy to demo and hard to trust: agents can send the wrong
message, overwrite data a person owns, act on a stale approval or repeat claims they cannot support.

## The solution

A system where agents propose and people decide, with the controls built into the structure rather than into prompts:

- **Qualification and routing** of inbound enquiries against an ICP rubric. Spam, unclear-intent and injection-suspected messages are held for human review.
- **Entity resolution and enrichment** across several providers, with source, confidence and freshness kept per field.
- **Evidence-linked research:** every claim cites a source or is marked unknown; untrusted text is treated as data.
- **Account agent** with persistent state that proposes next actions (create CRM account, send intro reply, follow up).
- **Just-in-time approval** of the exact payload, bound to a SHA-256 hash; approvals are single-use and expire.
- **Execution gateway** as the only route to anything outside the system; adapter clients require a gateway-signed token.
- **Append-only, hash-chained audit log** with a verification endpoint.
- **Evaluation harness:** a scenario runner, metrics against planted ground truth, and invariants checked after every scenario.
- **Dashboard** for leads, accounts, approvals, runs, audit, evaluation and demo control.

![Overview dashboard](portfolio/screenshots/01-overview.png)

## Architecture

![Architecture overview](portfolio/diagrams/architecture.svg)

Agents can only propose. A proposal waits for a human decision, and the execution gateway is the single path to the outside world.
Orchestration state, events and audit share one PostgreSQL database, so a step, its event and its audit record commit together.

![Golden thread](portfolio/diagrams/golden-thread.svg)

The demo's "golden thread": enquiry, entity resolution, enrichment, research, qualification, account-agent proposal, human approval,
gateway execution, scripted customer reply, updated account intelligence.

| Layer | Where | What |
|---|---|---|
| Contracts and schema | `backend/gtm/contracts/`, `backend/migrations/` | Pydantic contracts, PostgreSQL schema, approval-hash specification |
| Data | `backend/gtm/data/` | Waterfall enrichment, survivorship, entity resolution, soft merge with undo |
| Orchestration | `backend/gtm/orchestration/` | Outbox events, dispatcher, durable graph runner, leases with fencing, scheduler |
| Model access | `backend/gtm/llm/` | Wrapper with `mock`, `replay` and a guarded `live` mode (never run; see Limitations) |
| Agents and workflows | `backend/gtm/agents/`, `pipeline/`, `feedback/` | Intake, account agent, execute, ingest, pipeline monitor, feedback capture |
| Tool layer | `backend/gtm/mcp/` | Permissioned read and propose tool registry with run-bound scope |
| Approval and execution | `backend/gtm/approvals/`, `gateway/` | Human gates, single-use approvals, the gateway, reply router, suppression |
| Simulated world | `backend/gtm/world/`, `sims/`, `adapters/` | Seeded ground truth; provider, CRM, outreach and web simulators with fault injection |
| Evaluation | `backend/gtm/eval/`, `backend/scenarios/` | Invariants, metrics, scenario runner, baselines |
| API and UI | `backend/gtm/api/`, `frontend/` | FastAPI dashboard API; React UI with a mock mode |

**Safety by construction.** Agents have no tool that sends, creates CRM records, merges entities, edits human-owned fields or decides
a proposal. The approval hash covers the proposal id, type, full payload and screen-policy version; for messages the gateway
recomputes it from the currently resolved recipient at execution. Suppression is re-read under lock just before sending. The audit log
is protected by a database trigger and a hash chain. The token check is an in-process control in a single-process demo; see Limitations.

## Technology

| Choice | Why |
|---|---|
| Python 3.12, FastAPI, psycopg 3 | One language for API, agents, data and evaluation; simple deterministic tests |
| PostgreSQL 16 only | One transactional store for state, outbox events, job queue (`SKIP LOCKED`) and audit |
| In-house durable graph runner | Small, specific requirements; single-store transactions matter more than framework features (revisit criteria in [`docs/technology-decisions.md`](docs/technology-decisions.md)) |
| Mock, replay and live model modes behind one interface | Deterministic tests and replay; live use stays behind explicit guards |
| Simulated, HubSpot-shaped CRM and providers | No real system is touched; results can be checked against planted truth, with fault injection |
| React 18, TypeScript, Vite, Playwright, Vitest | The full story is visible in a browser, including a mock mode with no backend |

Decision records: [`DECISIONS.md`](DECISIONS.md) and [`docs/technology-decisions.md`](docs/technology-decisions.md).

## Demo

A scripted 105-second run of the real UI against the real backend: [`golden-thread.mp4`](portfolio/demo/golden-thread.mp4) (or the [GIF](portfolio/demo/golden-thread.gif)). The step-by-step script is [`portfolio/DEMO_SCRIPT.md`](portfolio/DEMO_SCRIPT.md); more screenshots are in [`portfolio/screenshots/`](portfolio/screenshots/MANIFEST.md).

![Approval of a CRM proposal](portfolio/screenshots/05-approval-crm.png)

1. **Demo control:** *Submit scripted enquiry*.
2. **Leads** and **Accounts:** per-field provenance (source, confidence, freshness), AI-written fields and agent state.
3. **Approvals:** open the CRM proposal, read the payload and hash, approve. The intro reply stays blocked until the CRM write executes, then shows *parked: sync pending*.
4. **Demo control:** *Advance +1 hour*; the parked reply is sent. Then *Deliver scripted customer reply*; account intelligence updates and a follow-up is proposed.
5. **Audit:** *Verify chain*. Then **Evaluation:** *Re-run evaluation* (can take up to a minute).

Try editing the reply to include a price: the content screen blocks it.

## Setup

**Prerequisites:** Python 3.12, Node 20+, Docker (PostgreSQL runs in a container). No API keys or accounts are needed.

```bash
# 1. Database: PostgreSQL 16 in Docker on 127.0.0.1:5433
./scripts/db_up.sh

# 2. Backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e "backend[dev]"
python -m gtm.cli serve        # API + simulators on http://127.0.0.1:8765 (resets the demo database)

# 3. Frontend (second terminal)
cd frontend && npm install
VITE_API_MODE=http npm run dev   # UI on http://localhost:5173, proxied to the backend on 8765
# or: npm run dev                # mock mode: the same story with in-browser fixtures, no backend needed
```

Other commands: `python -m gtm.cli reset-db` (empty the demo database), `python -m gtm.cli eval` (scenario suite, test database only).

## Tests and evaluation

```bash
source .venv/bin/activate && cd backend
python -m pytest tests -q                                   # backend tests (needs the Docker PostgreSQL)
python -m gtm.eval.runner --harness gtm.harness:Harness     # end-to-end scenarios against the real system
python -m gtm.eval.coverage                                 # requirements-to-scenarios matrix
cd ../frontend && npm test                                  # UI unit tests (Vitest)
# Browser tests (optional): stop any running `serve` first. Playwright starts its own backend on 8765 (it resets the demo database)
# and needs the browser once: npx playwright install chromium. Mock-only: npx playwright test --project=mock
```

| Check | Result |
|---|---|
| Backend tests | 416 passed |
| End-to-end scenarios (real system, simulated world) | 28 of 28 pass against the frozen baseline; 8 more are designed but not yet runnable |
| Requirements with a runnable scenario | 41 of 151 |
| Model-evaluation dataset (v4) | 68 synthetic cases; the mock model routes 26 of 27 qualification cases correctly |

These are technical results on a simulation, not evidence of commercial effectiveness. The mock model's perfect scores on injection
resistance, claim support and consistency hold by construction. The model-evaluation harness, its datasets and its limits are described
in [`model_eval/`](model_eval/README.md); history and failures are in [`TEST_RESULTS.md`](TEST_RESULTS.md).

## Limitations

- **Synthetic and simulated:** providers, CRM, outreach tool and replies are simulators; replies are scripted.
- **Mock model:** results say nothing about real model quality. No live model call has been made, and a zero-cost lock keeps live mode disabled ([`model_eval/ZERO_COST_LOCK.md`](model_eval/ZERO_COST_LOCK.md)).
- **No measured impact:** conversion, revenue and sales productivity were not measured.
- **No production CRM integration;** the simulated CRM is HubSpot-shaped and a real adapter is deferred.
- **Control scope:** the adapter-token check is in-process with a demo signing secret; the simulated services do not verify tokens.
- **Single-process demo,** one fixed reviewer, no authentication; the UI was verified in Chromium only.
- **Known policy gaps** (promotional vs transactional messages, support routing, "not now" timing, meeting priority, a verification queue) are listed in [`model_eval/10_business_policy.md`](model_eval/10_business_policy.md).
- Deferred by design: experimentation engine, automated feedback-pattern discovery, drift monitoring, outbound workflows.

## Documentation

| Document | Contents |
|---|---|
| [`docs/case-study.md`](docs/case-study.md) | Executive summary, then problem, design, demo, evaluation and limitations |
| [`docs/`](docs/README.md) | Design documents: requirements, architecture, data model, oversight, evaluation strategy |
| [`model_eval/`](model_eval/README.md) | Zero-cost model-evaluation work: datasets, harness results, what can and cannot be validated |
| [`DECISIONS.md`](DECISIONS.md), [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md), [`TEST_RESULTS.md`](TEST_RESULTS.md) | Decisions, build status, test history |
| [`portfolio/`](portfolio/) | Screenshots, diagrams, demo recording and script |

The project does not implement any real company's internal systems. Two industry sources informed the design and are cited only as far as
their summaries support.

## Licence

Released under the [MIT Licence](LICENSE).
