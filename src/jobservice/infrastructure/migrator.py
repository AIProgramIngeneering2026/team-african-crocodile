"""Schema migrations: numbered SQL files + a version table (Practice 4, ADR-0006).

* Files live in `infrastructure/migrations/` and are named `NNNN_short_name.sql`; numbers start at 1 with no gaps.
* Table `schema_migrations` remembers which versions were applied, when, and the SHA-256 of each file.
* Every pending migration runs in its own transaction together with its row in `schema_migrations`:
  a failing migration leaves the schema exactly as it was (SQLite DDL is transactional).
* An applied migration is a contract (lecture 104): if its file was edited later, `migrate` refuses to run.
  Change the schema with a NEW file instead.
* The service never creates tables at startup. It only checks that the schema is current
  (`assert_current`) and refuses to start otherwise: run `python -m jobservice migrate` first.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from urllib.parse import quote
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_FILE_NAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")

_VERSION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    checksum    TEXT NOT NULL,
    applied_at  TEXT NOT NULL
)
"""


class MigrationError(RuntimeError):
    """The migrations cannot be applied safely (edited file, gap in numbers, database newer than the code)."""


class SchemaNotCurrent(RuntimeError):
    """The database schema is older than the code: run `python -m jobservice migrate`."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def load_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    found: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        m = _FILE_NAME.match(path.name)
        if not m:
            raise MigrationError(f"bad migration file name {path.name!r}: expected NNNN_name.sql")
        found.append(Migration(int(m.group(1)), m.group(2), path.read_text(encoding="utf-8")))
    for expected, migration in enumerate(found, start=1):
        if migration.version != expected:
            raise MigrationError(f"migration numbers must be 1..N without gaps; found {migration.version} at {expected}")
    return found


def connect(db_path: str | Path, *, create: bool = False) -> sqlite3.Connection:
    """Autocommit connection: transactions are opened explicitly with BEGIN."""
    path = Path(db_path).resolve()
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    mode = "rwc" if create else "rw"  # without `create` a missing file is an error, not a new empty database
    uri = f"file:{quote(str(path))}?mode={mode}"  # quote: paths may contain spaces
    conn = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=5.0, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _applied(conn: sqlite3.Connection) -> dict[int, tuple[str, str]]:
    conn.execute(_VERSION_TABLE)
    rows = conn.execute("SELECT version, name, checksum FROM schema_migrations ORDER BY version").fetchall()
    return {version: (name, checksum) for version, name, checksum in rows}


def _check_history(applied: dict[int, tuple[str, str]], known: list[Migration]) -> None:
    by_version = {m.version: m for m in known}
    for version, (name, checksum) in applied.items():
        migration = by_version.get(version)
        if migration is None:
            raise MigrationError(
                f"database has migration {version:04d}_{name}, which this code does not know (database is newer)"
            )
        if migration.checksum != checksum:
            raise MigrationError(
                f"migration {version:04d}_{migration.name}.sql was changed after it was applied; "
                "write a new migration instead of editing an applied one"
            )


def pending(db_path: str | Path, directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    known = load_migrations(directory)
    if not Path(db_path).exists():
        return known
    conn = connect(db_path)
    try:
        applied = _applied(conn)
    finally:
        conn.close()
    _check_history(applied, known)
    return [m for m in known if m.version not in applied]


def current_version(db_path: str | Path) -> int:
    if not Path(db_path).exists():
        return 0
    conn = connect(db_path)
    try:
        return max(_applied(conn), default=0)
    finally:
        conn.close()


def migrate(db_path: str | Path, directory: Path = MIGRATIONS_DIR) -> list[int]:
    """Apply every pending migration in order. Returns the versions applied now (empty if up to date)."""
    known = load_migrations(directory)
    conn = connect(db_path, create=True)
    try:
        conn.execute("PRAGMA journal_mode = WAL")  # readers do not wait for the writer; stored in the file
        applied_now: list[int] = []
        applied = _applied(conn)
        _check_history(applied, known)
        for migration in known:
            if migration.version in applied:
                continue
            _apply(conn, migration)
            applied_now.append(migration.version)
        return applied_now
    finally:
        conn.close()


def _apply(conn: sqlite3.Connection, migration: Migration) -> None:
    # executescript() cannot take parameters; every value below is checked or generated by us:
    # version is an int, name matched [a-z0-9_]+, checksum is hex, applied_at is an ISO timestamp.
    applied_at = datetime.now(timezone.utc).isoformat()
    record = (
        "INSERT INTO schema_migrations (version, name, checksum, applied_at) "
        f"VALUES ({migration.version:d}, '{migration.name}', '{migration.checksum}', '{applied_at}');"
    )
    try:
        conn.executescript(f"BEGIN IMMEDIATE;\n{migration.sql}\n;\n{record}\nCOMMIT;")
    except sqlite3.Error as exc:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise MigrationError(f"migration {migration.version:04d}_{migration.name} failed: {exc}") from exc


def assert_current(db_path: str | Path, directory: Path = MIGRATIONS_DIR) -> None:
    """Called by the service at startup. It never changes the schema itself."""
    if not Path(db_path).exists():
        raise SchemaNotCurrent(f"database {db_path} does not exist: run `python -m jobservice migrate` first")
    todo = pending(db_path, directory)
    if todo:
        names = ", ".join(f"{m.version:04d}_{m.name}" for m in todo)
        raise SchemaNotCurrent(f"database {db_path} needs migrations {names}: run `python -m jobservice migrate`")
