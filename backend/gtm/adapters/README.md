# gtm.adapters: typed clients for the simulated systems

`ProviderClient(name, http)`: `company(domain=, name=, fields=)`, `person(email=, fields=)` -> `ProviderResponse`.
`CrmClient(http, verifier)`: `create/update` (side effects, adapter `crm.write`), `get`, `search(object_type, {prop: value})`.
`OutreachClient(http, verifier)`: `import_contact` (`outreach.import`), `send` (`outreach.send`), `lookup(external_key=|email=)` (None until visible), `events(since)`.
`WebClient(http)`: `search(q)`, `page(url)`. `AdapterSet(providers, crm, outreach, web)` bundles them.

Side-effecting methods take keyword-only `token: ExecutionToken` and `idempotency_key`, and optionally `payload_hash` (checked against the token).
`TokenVerifier.verify` runs BEFORE any HTTP call; failure raises `PolicyDenied`. HTTP errors go through `classify_http`: `RetryableError` (429/5xx/408/transport,
`retry_after` from the Retry-After header) or `PermanentError`; 409 raises `ConflictError(PermanentError)` with `.existing_id`; outreach send 422 (contact not yet
visible) raises `NotReady`. Adapters never retry. `http` is any `httpx.Client` (tests pass starlette TestClients, a real deployment passes `httpx.Client(base_url=...)`).

Tests: `cd backend && python -m pytest tests/adapters -q`
