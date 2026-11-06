# Five-minute demo script

For a live walkthrough or a screen share. Everything shown is **synthetic data with a deterministic mock model**; the amber banner at the top of every screen says so, and you should say it in the first ten seconds. A scripted 105-second recording of the same flow is in [`demo/`](demo/README.md) (mp4, gif, webm); screenshots are in [`screenshots/`](screenshots/MANIFEST.md).

## Before you start (2 minutes, off camera)
```bash
./scripts/db_up.sh                                          # PostgreSQL 16 in Docker on 127.0.0.1:5433
source .venv/bin/activate && cd backend && python -m gtm.cli serve     # API + simulators on http://127.0.0.1:8765 (resets the demo database)
cd frontend && VITE_API_MODE=http npm run dev               # UI on the port Vite prints (usually 5173)
```
Fallback if the backend will not start: `npm run dev` without `VITE_API_MODE` runs the UI on in-browser fixtures (mock mode): the same story, no backend. Say that it is a fixture mode if you use it. Open **Demo control** in a window at least 1440 px wide (narrower windows wrap the banner). Reset first so the Overview shows 0 leads.

## 0:00 to 0:45. The business problem
**Show:** Overview (`screenshots/01-overview.png` after the run; before it, the empty state).
**Say:** "Lead handling is mostly moving information around: find the company, enrich it, research it, decide if it fits, write a reply. The decisions that matter are what to send, what to promise and what to change in the CRM. The question I wanted to answer is how to automate the first and make it structurally unable to do the second. This is a simulation for a fictional consultancy: simulated data providers, CRM and email, and a deterministic mock where a language model would sit. No real message is ever sent."
**Point at:** the banner ("SYNTHETIC DATA / SIMULATED MODEL"), the line "Agents propose; humans approve; a gateway executes; everything is audited."

## 0:45 to 1:30. An inbound enquiry
**Do:** Demo control, then "Submit scripted enquiry".
**Say:** "A prospect at a fictional logistics firm writes in about a data engineering pilot. The system triages it, resolves the company and contact, and runs it through a workflow."
**Show:** Leads (`03-leads.png`): Marta Lindqvist, fit high (0.90), qualified. Mention the triage came from the mock, not a model.

## 1:30 to 2:15. Enrichment, research and qualification
**Show:** Accounts, Brightwater Logistics (`04-account-intelligence.png`, top table).
**Say:** "Each field shows where it came from, how confident the source is and how old it is. Three simulated providers disagree in accuracy, and survivorship picks values with freshness rules. The lavender rows (tagged "AI-written") are written by the account agent and can never overwrite a human-owned field such as the account owner. Low-confidence values appear as risks instead of silently deciding anything."
**Be candid if asked:** the qualification score comes from a rule-based mock; this demo shows the plumbing and the evidence trail, not model quality.

## 2:15 to 3:15. Human approval
**Show:** Approvals, proposal #1 "Crm write" (`05-approval-crm.png`).
**Say:** "The agent does not create the CRM record. It proposes it. The reviewer sees the exact payload and its SHA-256 hash. Approve it."
**Do:** Approve. Show the gateway checks: "13 canonical checks; a CRM write passes the ones that apply and skips the message-only ones."
**Then:** open the dependent reply (#2 "Message"; it was waiting on the CRM write and is now pending). Edit it to include a price ("EUR 20,000") and submit: the commercial-content screen refuses it (`06-approval-edit-blocked.png`). Replace the price with a harmless sentence such as "Thursday morning works well for us." and approve: the edited text gets a new hash and a diff (`12-approval-edit-diff.png`).

## 3:15 to 4:00. Controlled execution
**Say:** "When the gateway runs, it recomputes the hash from the recipient as it is now, re-checks suppression under a lock, and only then asks the adapter to send; the adapter client refuses any call without a gateway-signed token (an in-process control in this demo; say so if asked). The simulated outreach tool is eventually consistent, so the send is parked as `sync_pending`."
**Do:** Demo control, "Advance +1 hour" (the other options are +1 day, +3 days and +7 days). The parked send executes. Then "Deliver scripted customer reply".
**If asked about bypass:** scenarios attack the gateway with no token, a forged token, a wrong hash, a replay and a direct adapter call; each must be denied.

## 4:00 to 4:30. Account intelligence and audit
**Show:** the account page again (`04-account-intelligence.png`, lower half): stakeholders, commitments, next actions, "Account agent state v3". Then Audit and "Verify chain" (`08-audit-verify.png`): "Chain OK, N rows checked" (36 in the recorded run; the number changes if you deviate from the script).
**Say:** "The agent's state updated from the reply, and it proposed a follow-up, which again waits for a human. The audit log is append-only, enforced by a database trigger, and hash-chained; the verify button recomputes the chain. There is a test that tampers with a row and expects verification to fail."
**Candid note if you notice it:** a few labels are rough (for example "Last decision confidence 0.00", internal action names like `recommend_task`).

## 4:30 to 5:00. Evaluation results
**Show:** Evaluation (`09-evaluation.png`), "Re-run evaluation" (about 30 seconds to a minute; the page shows no progress bar). Diagram: `diagrams/evaluation-results.svg`.
**Say:** "28 of 28 end-to-end scenarios pass and ten invariants are checked after each, for example no execution without a matching, consumed approval. A separate model-evaluation layer scores the mock on 68 synthetic cases and I tested the harness with deliberately faulty stand-ins. These are technical results on simulated data: real commercial model performance is untested, no live model call was ever made, and nothing about conversion or revenue has been measured."
**Close:** "What I would do next is a budgeted comparison with a real model and a few gaps I documented, such as separating promotional opt-outs from service messages."

