"""Minimal MCP-compatible JSON-RPC 2.0 stdio server (newline-delimited JSON) over a ToolSession.

NOT the full protocol and written without the MCP SDK (none installed): it implements `initialize`, `ping`, `tools/list`,
`tools/call` and ignores notifications. One server (gtm-read or gtm-propose) per process; the profile, principal and account
are bound from argv, never from tool arguments.

    python -m gtm.mcp.stdio_server --server gtm-read --profile account-agent --principal agent:account-agent --account 12
"""
from __future__ import annotations
import argparse, json, sys
from typing import Any, IO
from ..contracts.errors import GTMError, PolicyDenied
from .registry import READ, PROPOSE, ToolSession

PROTOCOL_VERSION = "2024-11-05"


def handle(session: ToolSession, server: str, msg: dict) -> dict | None:
    """Process one JSON-RPC message; returns the response or None for notifications."""
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}

    def ok(result: Any) -> dict:
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def err(code: int, message: str, data: Any = None) -> dict:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message, **({"data": data} if data else {})}}

    if mid is None:
        return None
    if method == "initialize":
        return ok({"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}}, "serverInfo": {"name": server, "version": "0.1-minimal"}})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": [{"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"]} for t in session.list_tools(server)]})
    if method == "tools/call":
        try:
            res = session.call(str(params.get("name")), **(params.get("arguments") or {}))
            return ok({"content": [{"type": "text", "text": json.dumps(res, default=str)}], "isError": False})
        except PolicyDenied as e:
            return ok({"content": [{"type": "text", "text": f"denied: {e}"}], "isError": True, "_meta": {"error_class": "policy"}})
        except GTMError as e:
            return ok({"content": [{"type": "text", "text": f"error: {e}"}], "isError": True, "_meta": {"error_class": str(e.error_class)}})
        except TypeError as e:
            return err(-32602, f"invalid params: {e}")
    return err(-32601, f"method not found: {method}")


def serve(session: ToolSession, server: str, inp: IO[str], out: IO[str]) -> None:
    for line in inp:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            resp = handle(session, server, msg) if isinstance(msg, dict) else {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
        except json.JSONDecodeError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        if resp is not None:
            out.write(json.dumps(resp, default=str) + "\n")
            out.flush()


def main(argv: list[str] | None = None) -> None:  # pragma: no cover - wiring only
    from .. import config, db
    from ..clock import SystemClock
    from ..orchestration import Services
    p = argparse.ArgumentParser()
    p.add_argument("--server", choices=[READ, PROPOSE], required=True)
    p.add_argument("--profile", required=True)
    p.add_argument("--principal", required=True)
    p.add_argument("--account", type=int)
    a = p.parse_args(argv)
    settings, clock = config.get_settings(), SystemClock()
    conn = db.connect(settings.database_url)
    session = ToolSession(conn, clock, Services(settings, clock), profile=a.profile, principal=a.principal, account_id=a.account, servers=(a.server,))
    serve(session, a.server, sys.stdin, sys.stdout)
    conn.commit()


if __name__ == "__main__":  # pragma: no cover
    main()
