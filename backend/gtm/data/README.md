# gtm.data: waterfall enrichment, survivorship, entity resolution, soft merge

All functions use the caller's transaction (they never commit). Time comes from the injected `Clock`. Data written by providers is labelled `SIM`.

## waterfall
- `fetch_provider(conn, clock, client, provider_name, entity_type, entity_id, fields, *, run_id=None, parent_resolver=None) -> {provider, found, observation_ids, cost_units, partial}`.
  One provider call, immutable `gtm.observation` rows (`observed_at` = provider `as_of`, `confidence` = source prior for the field). `RetryableError`/`PermanentError` propagate unchanged (no retries here).
  Provider `parent_id` is stored as `parent_domain` via `parent_resolver(ref) -> domain`; without a resolver it is kept as `parent_ref`.
- `enrich_entity(conn, clock, providers, *, entity_type, entity_id, fields, cost_cap, mode="sequential"|"parallel", run_id=None, min_confidence=0.75, parent_resolver=None, resolve=True) -> EnrichmentResult`.
  First-party and existing non-expired observations that meet the bar are used first (status `existing`). `sequential` asks providers one by one, ordered by cost / mean field reliability, and only for unmet fields.
  `parallel` asks every capable provider for every unmet field (no early stop). Both stop at `cost_cap` (remaining fields stay `unknown`, nothing is fabricated). A `RetryableError` records a failure + gap and the run continues.
  Writes `gtm.enrichment_request` (`providers_tried` has `name:failed` entries) and an audit event. `EnrichmentResult(request_id, status, fields, cost, providers_tried, gaps, failures, resolved)`.
- `record_first_party(conn, clock, entity_type, entity_id)`.

## survivorship (docs 7.1-7.3)
- `record_observation(...)`, `resolve_fields(conn, clock, entity_type, entity_id, fields=None) -> {field: {value, confidence, freshness_state, conflict_flag, winning_observation_id, needs_human_review}}`, `get_resolved(conn, entity_type, entity_id)` (adds `sources[]` for provenance).
- Human value wins unless expired and contradicted by two independent sources (then the machine value is used, `conflict_flag` and `needs_human_review` are set: the caller proposes). Otherwise score = prior x freshness factor, independent sources combine 1-(1-c1)(1-c2); runner-up within 15% sets `conflict_flag` and caps confidence at 0.5.
  Freshness: fresh <= TTL/2, stale <= TTL (factor 1 -> 0.5), expired > TTL (excluded from scoring; shown with low confidence if nothing else exists). `TTL_DAYS` holds the table. Superseded observations are kept (`superseded_by`).

## entity resolution
- `resolve_account(conn, clock, *, name, domain=None) -> MatchDecision`, `resolve_contact(conn, clock, *, email, full_name, company_name=None)`: read-only. Bands `same` (exact email; or exact domain + name similarity >= 0.9), `possible` (score 0.6-0.9 or conflicting strong keys), `distinct`. Role mailboxes (info@, sales@ ...) never match people; free-mail domains are never account keys.
- `ensure_account(...) -> (id, decision)`, `ensure_contact(...) -> (id, decision)`: same = link (alias domain + `entity_match` row, existing id returned); possible = new row + pending `entity_match` (never auto-merged); distinct = new row.
- `propose_match(conn, clock, decision, new_id)` creates the G1 proposal (returns None if a human already decided the pair). `scan_duplicates(conn, clock, "account")` lists undecided duplicate pairs.
- `attach_parent(conn, clock, account_id, parent_domain)` / `attach_parent_from_resolved(...)`: `account_relationship` + `parent_account_id` + `hierarchy_role`; cycles refused.

## merge
- `soft_merge(conn, clock, etype, loser_id, survivor_id, ...) -> merge_log id` and `undo_merge(conn, clock, merge_log_id)` (moved row ids are logged in the audit event `merge.executed`).
- Gateway executors: `MergeExecutor` (adapter `db.merge`, proposal type `merge`, payload `{entity_type, loser_id, survivor_id}`), `MatchConfirmationExecutor` (adapter `db.match_confirmation`, type `match_confirmation`; approval = `same`).
  Register: `gateway.register_executor("merge", MergeExecutor())`, `gateway.register_executor("match_confirmation", MatchConfirmationExecutor())`.
  A rejected match proposal means "distinct": call `record_match_rejection(conn, clock, proposal_id)` to store the negative match. `propose_merge(...)` creates the G2 proposal.

Tests: `cd backend && GTM_TEST_DATABASE_URL=postgresql://gtm:gtm_local_dev_only@127.0.0.1:5433/gtm_test_a python -m pytest tests/data -q -s` (the `-s` shows the printed measurements, labelled SIMULATED WORLD).
