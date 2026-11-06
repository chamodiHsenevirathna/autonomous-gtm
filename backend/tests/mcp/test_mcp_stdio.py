import io, json
from test_mcp_registry import world, mk  # noqa: F401
from gtm.mcp import ToolSession
from gtm.mcp.stdio_server import serve


def run(session, server, msgs):
    out = io.StringIO()
    serve(session, server, io.StringIO("\n".join(json.dumps(m) if isinstance(m, dict) else m for m in msgs) + "\n"), out)
    return [json.loads(l) for l in out.getvalue().splitlines()]


def test_stdio_roundtrip(conn, clock, world):
    s = ToolSession(conn, clock, world.svc, profile="account-agent", principal="agent:account-agent", account_id=world.a, servers=("gtm-read",))
    r = run(s, "gtm-read", [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_signals", "arguments": {"account_id": world.a}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "get_signals", "arguments": {"account_id": world.b}}},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "flag_risk", "arguments": {"account_id": world.a, "risk": "x"}}},
        {"jsonrpc": "2.0", "id": 6, "method": "nope"}, "not json"])
    assert [x["id"] for x in r] == [1, 2, 3, 4, 5, 6, None]
    names = {t["name"] for t in r[1]["result"]["tools"]}
    assert "get_signals" in names and "flag_risk" not in names
    assert r[2]["result"]["isError"] is False
    assert r[3]["result"]["isError"] is True and "denied" in r[3]["result"]["content"][0]["text"]
    assert r[4]["result"]["isError"] is True            # propose server not mounted
    assert r[5]["error"]["code"] == -32601 and r[6]["error"]["code"] == -32700
    assert conn.execute("SELECT count(*) AS n FROM ops.tool_call WHERE NOT permitted").fetchone()["n"] == 2
