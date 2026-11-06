# Scenarios

One YAML file per scenario (`gtm.contracts.scenario.Scenario`). The DSL is in `gtm/eval/README.md`.
`python -m gtm.eval.runner --validate` lints them; `python -m gtm.eval.coverage` prints the requirements-to-scenarios matrix.

- `scenarios/*.yaml` (29, runnable): S01 S02 S03 S04 S05 S06 S07 S09 S10 S11 S13 S14 S15 S16 S17 S18 S19 S20 S22 S24 S25 S30 S45 S46 S47 S48 S49 S50 S52.
- `scenarios/pending/*.yaml` (7, NOT loaded by the runner; lint-checked only): S08 S12 S21 S23 S26 S53 S56. Each needs something the world or harness
  does not provide yet (gaps below). Move a file up one directory when its gap is closed.
- Not written: S27 (state rebuild, not implemented), S29 (circuit breaker is stretch), S28, S31-S44, S51, S54, S55.

## Reconciliation with the seed-42 world (gtm/world/README.md)

All enquiry and reply ids are now literal world ids:

| Scenario | World ids used |
|---|---|
| S01, S09, S22, S24, S25, S45, S46, S47, S48, S52, S19, S13-S16 | `enq_001` (golden thread); S09 adds `enq_004`; S19 uses `rpl_002` (meeting_booked); S30 uses `rpl_001` |
| S02 exact duplicate | `enq_002`, `enq_003` |
| S03 fuzzy duplicate | `enq_004`, `enq_005` |
| S04 subsidiary | `enq_014` (parent `co_005`), `enq_006` (subsidiary `co_035`) |
| S05 shared mailbox | `enq_001`, `enq_007` (`info@`) |
| S06 triage | all 15 enquiries (`select: all`) |
| S07 injection | `enq_013` |
| S17, S49 unsubscribe | `enq_014` with `rpl_008` (unsubscribe) |
| S18 six reply kinds | enquiries 001, 002, 006, 007, 012, 014 with `rpl_001` interested, `rpl_003` not_now, `rpl_005` ooo, `rpl_006` bounce, `rpl_008` unsubscribe, `rpl_007` referral |
| S20 competing claims | `enq_002`, `enq_003` (same contact) |
| S50 | `enq_011` (genuine, low) |

The runner's computed selectors (`vendor_pitch`, `shared_mailbox`, etc.) still exist but no scenario depends on them.

## Gaps

S06 has 15 labelled enquiries, the criterion needs >= 40. S08 needs an enquiry whose company has an injected page (only `co_015` does, no enquiry uses it).
S12 needs a settable per-run cost cap. S21 needs a "human touch" hook. S23 needs the account agent and a signal-injection hook. S26, S53, S56 need
`world_overrides` that `Runtime.build` ignores (only `world_params` is read). S10 cannot make a provider stale, so it uses faults instead.
S15 cannot make a CRM write apply and then time out. S47 only covers the proposer-is-approver rule on agent proposals (no human-proposed G6 can be created).
S50 uses a student enquiry; the world has no genuine lead that looks like spam. S52 omits the workflow-lint half (no hook).

## Conventions the scenarios assume of the real harness

- `snapshot()` key `messages_sent_to_sim`; `decide()` returns `{"ok": false}` on refusal; bypass refusals write audit `gateway.bypass_denied`.
- Audit `proposal.executed`, `proposal.blocked` (`data.block_class`), `lead.injection_suspected` (S07, not yet confirmed); `last_gateway.reason == "recipient_changed"` (S45).
- `drain` approves G1, G2, G3, G4, G7, G8; the message (G5) is approved separately.
