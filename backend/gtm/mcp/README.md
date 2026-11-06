# gtm.mcp

Permissioned tool layer for model-driven calls (docs/mcp-integrations.md). No MCP SDK is installed; this is plain Python.

## API
```python
from gtm.mcp import ToolSession
s = ToolSession(conn, clock, services, profile="account-agent", principal="agent:account-agent", account_id=12, run_id=None)
s.list_tools()            # [{name, server, description, inputSchema}] for the profile
s.call("get_signals", account_id=12) -> dict      # PolicyDenied if denied; every call writes ops.tool_call
```
- Scope is bound at creation. Any account/contact/opportunity/proposal id (also inside `payload`, `target_entity`, `entity`) that does not resolve to the bound account is denied.
- Denied calls are committed immediately (`commit_denials=True`) so the evidence survives a caller rollback.
- Profiles: `research-agent`, `account-agent`, `pipeline-monitor`. `servers=("gtm-read",)` mounts one server only.
- `gtm-read`: get_account_context, search_interactions, get_opportunity, get_signals, get_suppression_status, get_feedback_digest, search_feedback, list_provider_status, search_web_sim, fetch_page_sim (web results are `{"untrusted":..., "source_url":...}`).
- `gtm-propose`: create_proposal, create_draft, update_agent_fields, patch_agent_state (raises `VersionConflict`), request_enrichment (cost cap mandatory), flag_risk.
- Absent (denied and logged): send_email, create_contact, create_account, update_opportunity, merge_entities, delete_*, set_price, book_meeting, enrol_sequence, approve_proposal, execute_proposal, launch_experiment and the other names in `ABSENT_TOOLS`.
- `field_policy.check_direct_write(conn, entity, field, principal)` checks `ops.field_policy`.
- `stdio_server.py`: minimal JSON-RPC 2.0 stdio server (initialize, ping, tools/list, tools/call), one server per process, scope from argv. A small subset of MCP, written without the SDK.

Tests: `cd backend && python -m pytest tests/mcp -q`
