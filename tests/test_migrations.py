"""Migrations (p4.md items 2 and 6): applied to an empty database, versioned, safe to repeat, never edited."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from helpers import raw_db

from jobservice.bootstrap import build_app
from jobservice.infrastructure.migrator import (
    MIGRATIONS_DIR,
    MigrationError,
    SchemaNotCurrent,
    assert_current,
    current_version,
    load_migrations,
    migrate,
    pending,
)


def tables_and_indexes(db: Path) -> set[str]:
    with raw_db(db) as conn:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}


@pytest.fixture
def mig_dir(tmp_path: Path) -> Path:
    """A private copy of the real migrations that a test may change."""
    target = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS_DIR, target)
    return target


def test_migrations_are_numbered_without_gaps():
    assert [m.version for m in load_migrations()] == list(range(1, len(load_migrations()) + 1))


def test_migrations_apply_to_an_empty_database(tmp_path):
    db = tmp_path / "empty.db"
    assert current_version(db) == 0 and [m.version for m in pending(db)] == [1, 2]
    assert migrate(db) == [1, 2]
    assert current_version(db) == 2 and pending(db) == []
    assert {"jobs", "job_history", "schema_migrations", "ix_jobs_unfinished", "ix_job_history_job_id"} <= tables_and_indexes(db)
    with raw_db(db) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert_current(db)  # does not raise


def test_migrate_twice_changes_nothing(db_path):
    before = tables_and_indexes(db_path)
    assert migrate(db_path) == []
    assert tables_and_indexes(db_path) == before


def test_service_refuses_to_start_on_a_missing_or_old_schema(tmp_path, mig_dir):
    with pytest.raises(SchemaNotCurrent):
        build_app(tmp_path / "never-migrated.db")
    assert not (tmp_path / "never-migrated.db").exists()  # the service does not create tables itself

    (mig_dir / "0002_create_job_history.sql").unlink()
    old = tmp_path / "old.db"
    migrate(old, mig_dir)  # only 0001
    with pytest.raises(SchemaNotCurrent, match="0002_create_job_history"):
        build_app(old)


def test_editing_an_applied_migration_is_refused(tmp_path, mig_dir):
    db = tmp_path / "x.db"
    migrate(db, mig_dir)
    first = mig_dir / "0001_create_jobs.sql"
    first.write_text(first.read_text() + "\n-- tweak\n")
    with pytest.raises(MigrationError, match="changed after it was applied"):
        migrate(db, mig_dir)


def test_database_newer_than_the_code_is_refused(tmp_path, mig_dir):
    db = tmp_path / "x.db"
    migrate(db, mig_dir)
    (mig_dir / "0002_create_job_history.sql").unlink()
    with pytest.raises(MigrationError, match="newer"):
        migrate(db, mig_dir)


def test_a_failing_migration_changes_nothing(tmp_path, mig_dir):
    db = tmp_path / "x.db"
    migrate(db, mig_dir)
    (mig_dir / "0003_broken.sql").write_text(
        "ALTER TABLE jobs ADD COLUMN note TEXT;\nCREATE TABLE half_done (id INTEGER);\nTHIS IS NOT SQL;\n"
    )
    before = tables_and_indexes(db)
    with pytest.raises(MigrationError, match="0003_broken"):
        migrate(db, mig_dir)
    assert current_version(db) == 2 and tables_and_indexes(db) == before
    with raw_db(db) as conn:
        assert "note" not in {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}


def test_gap_in_numbers_is_refused(tmp_path, mig_dir):
    (mig_dir / "0005_skip.sql").write_text("SELECT 1;")
    with pytest.raises(MigrationError, match="without gaps"):
        migrate(tmp_path / "x.db", mig_dir)


def test_0002_backfills_history_for_jobs_written_before_it(tmp_path, mig_dir):
    """A data-aware migration: Jobs created under schema 1 get a history record when schema 2 arrives."""
    only_first = tmp_path / "first"
    only_first.mkdir()
    shutil.copy(mig_dir / "0001_create_jobs.sql", only_first)
    db = tmp_path / "x.db"
    migrate(db, only_first)
    with raw_db(db) as conn:
        conn.execute(
            "INSERT INTO jobs (id, operation, params_json, idempotency_key, request_hash, tool_version, correlation_id,"
            " status, result_json, created_at, started_at, finished_at) VALUES"
            " ('j1', 'transform_text', '{}', 'k1', 'h', 'transform_text/1', 'c', 'done', '{}', 't0', 't1', 't2')"
        )
    assert migrate(db, mig_dir) == [2]
    with raw_db(db) as conn:
        assert conn.execute("SELECT job_id, from_status, to_status, at FROM job_history").fetchall() == [
            ("j1", None, "done", "t2")
        ]


@pytest.mark.parametrize(
    "status, result, error_code, finished",
    [
        ("done", None, None, "t"),        # done without result
        ("error", None, None, "t"),       # error without error
        ("done", "{}", None, None),       # final without finished_at
        ("running", None, None, None),    # running without started_at
        ("paid", None, None, None),       # unknown status
    ],
)
def test_database_itself_refuses_a_job_that_breaks_the_invariants(db_path, status, result, error_code, finished):
    """Second line of defence (Н41/Н46): even a buggy UPDATE cannot store an impossible Job."""
    with raw_db(db_path) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO jobs (id, operation, params_json, idempotency_key, request_hash, tool_version,"
            " correlation_id, status, result_json, error_code, error_message, created_at, finished_at)"
            " VALUES ('j', 'op', '{}', 'k', 'h', 'v', 'c', ?, ?, ?, ?, 't0', ?)",
            (status, result, error_code, error_code, finished),
        )
