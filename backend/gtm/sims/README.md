# gtm.sims: simulated external world

FastAPI app factories, in-memory state, time only from the injected `Clock`, deterministic given (world, clock, faults).
`build_sims(world, clock, *, auto_replies=False) -> SimBundle`:
- `.app`: root app mounting providers (`/sim/providers/{a,b,c}`), CRM (`/sim/crm`), outreach (`/sim/outreach`), web (`/sim/web`), control (`/sim/control`).
- `.control`: `inject(FaultSpec)`, `clear()`, `state()`, `script(...)`; also over HTTP (`POST/DELETE /faults`, `GET /state`, `POST /script`).
- `.clients(token_secret=b"sim-token-secret") -> AdapterSet` (TestClients per mount, adapters use mount-relative paths).
- `.script_reply(reply_id, to_email=None, at=None, to_message_id=None)`: delivers the scripted reply when the clock passes `at`.
- `auto_replies=True`: sending to an enquiry's email schedules that enquiry's scripted replies at send time + offset.

Behaviour: providers charge `cost_units` on every call (found or not); coverage, per-field correctness and `as_of` come from a hash of
(seed, provider, entity, field). CRM: HubSpot-like, 201 create / 200 idempotent replay / 409 `{"message","existingId"}` on duplicate contact email,
ids are strings starting at 1001. Outreach: import returns 202 with `visible_at` (5-120 s deterministic per email); contact id is `oc_<crm id>`;
`GET /events?since=` is a pull feed (`contact_visible`, `reply`, `bounce`, `unsubscribe`, `meeting_booked`); bounce/unsubscribe suppress the address (403).
Faults (every `FaultKind`): `latency` (header `X-Sim-Latency-Ms`, no sleeping, clock untouched), `http_429` (+Retry-After, param `retry_after`),
`http_500/503`, `timeout` (504), `partial_data`, `eventual_consistency` (`delay_s` on imports), `duplicate_events`, `out_of_order_events` (next N event
pulls), `drop_sync` (import accepted, contact never visible). `count` limits to the next N relevant requests; `scope` is a substring filter on
path/domain/email; `sim="*"` hits all sims.

Tests: `cd backend && python -m pytest tests/sims -q`
