# Zero-cost lock

The owner has set a permanent $0 / no-paid-API restriction for the model-evaluation phase (2026-11-06).
While this file exists: `LiveClient` refuses any real-network use before reading any API key, and `model_eval.guard_live` refuses live mode.
Only the owner may remove it, by explicitly changing the restriction. Tests assert that it exists.
