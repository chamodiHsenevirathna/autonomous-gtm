"""Database access and migrations (plain SQL files in backend/migrations)."""
from __future__ import annotations
import pathlib
from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "migrations"
SEARCH_PATH = "gtm,ops,public"


def connect(url: str, *, autocommit: bool = False) -> psycopg.Connection:
    conn = psycopg.connect(url, row_factory=dict_row, autocommit=autocommit,
                           options=f"-c search_path={SEARCH_PATH}")
    return conn


@contextmanager
def transaction(conn: psycopg.Connection):
    """Commit on success, roll back on error."""
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def migrate(url: str) -> list[str]:
    """Apply unapplied migrations in filename order. Returns the names applied."""
    applied: list[str] = []
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS ops")
        conn.execute("CREATE TABLE IF NOT EXISTS ops.schema_migration (name text PRIMARY KEY, applied_at timestamptz DEFAULT now())")
        done = {r[0] for r in conn.execute("SELECT name FROM ops.schema_migration")}
        for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if f.name in done:
                continue
            conn.execute(f.read_text())
            conn.execute("INSERT INTO ops.schema_migration(name) VALUES (%s)", (f.name,))
            applied.append(f.name)
    return applied


def ensure_database(url: str) -> None:
    """Create the database named in url if missing (connects to the 'postgres' maintenance db)."""
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    info = conninfo_to_dict(url)
    name = info["dbname"]
    admin = make_conninfo(url, dbname="postgres")
    with psycopg.connect(admin, autocommit=True) as c:
        if not c.execute("SELECT 1 FROM pg_database WHERE datname=%s", (name,)).fetchone():
            c.execute(f'CREATE DATABASE "{name}"')


def truncate_all(conn: psycopg.Connection) -> None:
    """Test helper: empty every table in gtm/ops except the migration ledger. Audit rows included (test DB only)."""
    rows = conn.execute(
        "SELECT schemaname||'.'||tablename AS t FROM pg_tables WHERE schemaname IN ('gtm','ops') AND tablename <> 'schema_migration'"
    ).fetchall()
    if rows:
        conn.execute("ALTER TABLE ops.audit_event DISABLE TRIGGER USER")
        conn.execute("TRUNCATE " + ", ".join(r["t"] for r in rows) + " RESTART IDENTITY CASCADE")
        conn.execute("ALTER TABLE ops.audit_event ENABLE TRIGGER USER")
    conn.commit()
