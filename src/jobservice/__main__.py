"""Command line: `python -m jobservice {migrate|status|serve}`.

    python -m jobservice migrate   apply pending migrations (creates the database file if needed)
    python -m jobservice status    show the schema version and pending migrations
    python -m jobservice serve     start the HTTP API (refuses to start if migrations are pending)

`--db PATH` overrides JOBSERVICE_DB for any command; `--host` / `--port` for `serve`.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace

from jobservice.infrastructure.migrator import MigrationError, SchemaNotCurrent, current_version, migrate, pending
from jobservice.server import Settings, serve


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jobservice", description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["migrate", "status", "serve"])
    parser.add_argument("--db", help="SQLite file (default: $JOBSERVICE_DB or var/jobservice.db)")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    overrides = {k: v for k, v in {"db_path": args.db, "host": args.host, "port": args.port}.items() if v is not None}
    settings = replace(settings, **overrides)

    try:
        if args.command == "migrate":
            applied = migrate(settings.db_path)
            if applied:
                print(f"{settings.db_path}: applied {', '.join(f'{v:04d}' for v in applied)}")
            else:
                print(f"{settings.db_path}: schema is up to date (version {current_version(settings.db_path)})")
        elif args.command == "status":
            todo = pending(settings.db_path)
            print(f"{settings.db_path}: version {current_version(settings.db_path)}, "
                  f"pending: {', '.join(f'{m.version:04d}_{m.name}' for m in todo) or 'none'}")
        else:
            serve(settings)
    except (MigrationError, SchemaNotCurrent) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
