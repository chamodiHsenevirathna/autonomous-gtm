"""Per-account lease with a fencing token. Writers re-check the token before committing; a zombie is rejected."""
from __future__ import annotations
from datetime import timedelta
from psycopg import Connection
from ..clock import Clock
from ..contracts.errors import ErrorClass, GTMError


class LeaseLost(GTMError):
    """Another holder took the account lease (stale fencing token). Treated as NOT_READY: the run re-queues."""
    error_class = ErrorClass.NOT_READY


def acquire(conn: Connection, clock: Clock, account_id: int, run_id: int, ttl: float) -> int | None:
    """Return the fencing token, or None when a live holder owns it. Re-entrant for the same run."""
    now = clock.now()
    exp = now + timedelta(seconds=ttl)
    conn.execute("INSERT INTO ops.account_lease(account_id, holder_run_id, fencing_token, expires_at, renewed_at) "
                 "VALUES (%s,NULL,0,%s,%s) ON CONFLICT DO NOTHING", (account_id, now, now))
    r = conn.execute("SELECT * FROM ops.account_lease WHERE account_id=%s FOR UPDATE", (account_id,)).fetchone()
    if r["holder_run_id"] == run_id and r["expires_at"] > now:
        conn.execute("UPDATE ops.account_lease SET expires_at=%s, renewed_at=%s WHERE account_id=%s", (exp, now, account_id))
        return r["fencing_token"]
    if r["holder_run_id"] is None or r["expires_at"] <= now:
        tok = r["fencing_token"] + 1
        conn.execute("UPDATE ops.account_lease SET holder_run_id=%s, fencing_token=%s, expires_at=%s, renewed_at=%s WHERE account_id=%s",
                     (run_id, tok, exp, now, account_id))
        return tok
    return None


def check(conn: Connection, clock: Clock, account_id: int, run_id: int, token: int, ttl: float) -> None:
    """Raise LeaseLost unless (run, token) is still the holder; otherwise extend the lease."""
    now = clock.now()
    r = conn.execute("SELECT * FROM ops.account_lease WHERE account_id=%s FOR UPDATE", (account_id,)).fetchone()
    if not r or r["fencing_token"] != token or r["holder_run_id"] != run_id:
        raise LeaseLost(f"stale fencing token {token} for account {account_id}")
    conn.execute("UPDATE ops.account_lease SET expires_at=%s, renewed_at=%s WHERE account_id=%s",
                 (now + timedelta(seconds=ttl), now, account_id))


def release(conn: Connection, clock: Clock, account_id: int, run_id: int, token: int) -> None:
    conn.execute("UPDATE ops.account_lease SET holder_run_id=NULL, expires_at=%s WHERE account_id=%s AND holder_run_id=%s AND fencing_token=%s",
                 (clock.now(), account_id, run_id, token))
