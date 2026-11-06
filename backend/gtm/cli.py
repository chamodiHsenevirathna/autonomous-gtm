"""python -m gtm.cli {serve,reset-db,eval}"""
from __future__ import annotations
import argparse, sys
from . import db
from .config import get_settings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m gtm.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="serve the dashboard API on the demo database")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    sub.add_parser("reset-db", help="create/migrate the demo database and empty it (reference data re-seeded)")
    e = sub.add_parser("eval", help="run the evaluation scenario suite (test database only)", add_help=False)
    a, rest = ap.parse_known_args(argv)
    url = get_settings().database_url
    if a.cmd == "serve":
        import uvicorn
        from .api import create_app
        uvicorn.run(create_app(url), host=a.host, port=a.port)
        return 0
    if a.cmd == "reset-db":
        from . import seed
        db.ensure_database(url)
        db.migrate(url)
        c = db.connect(url)
        db.truncate_all(c)
        seed.seed_reference(c)
        c.close()
        print(f"demo database reset: {url.rsplit('@', 1)[-1]}")
        return 0
    from .eval import runner
    return runner.main(rest)


if __name__ == "__main__":
    sys.exit(main())
