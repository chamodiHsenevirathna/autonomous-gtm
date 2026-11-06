# gtm.feedback

- `save_lost_deal_review(conn, clock, *, opportunity_id, primary_reason, secondary_reasons, competitor, debrief_held, notes, captured_by, ai_suggested_tags=None)`: human-only; reasons from `LOST_REASONS`; AI tags stored separately and labelled in `ai_suggested_tags`; one review per opportunity; emits `lost_deal_review.saved`.
- `extract_feedback(conn, clock, llm, *, interaction_id=None, lost_deal_review_id=None, run_id=None)`: LLM task `feedback_extract` (text under `input["untrusted"]`); code rejects any quote that is not a verbatim substring of the source (counted as `rejected_hallucinated`) and instruction-like quotes (`rejected_injection`); stores `suggested` items with offsets and a segment snapshot; emits `feedback.captured`. Idempotent per source. Source text for interactions is `subject\nbody`; offsets refer to it.
- `mock_feedback_extract` / `register_mocks()` (called on import): deterministic keyword rules, MOD / mode=mock.
- `feedback_summary(conn)`: per-topic distinct-account counts (mentions shown alongside). No themes, backlog or experiments (deferred).
- `build_graphs()`: graph `feedback_extract` (triggers `lost_deal_review.saved`, `interaction.stored`).

Tests: `cd backend && python -m pytest tests/feedback -q`
