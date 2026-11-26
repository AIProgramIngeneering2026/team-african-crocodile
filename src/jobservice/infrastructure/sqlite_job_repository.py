"""SQLite implementation of JobRepository (Practice 4, ADR-0006).

* The schema comes only from migrations (`migrator.py`); this class never creates tables.
* One short connection per call: safe with a threaded HTTP server, nothing is shared between threads.
  No transaction is ever open while a Tool runs — the Dispatcher calls `save` before and after `execute`.
* `add` = INSERT jobs + INSERT job_history in ONE transaction; `save` = UPDATE jobs + INSERT job_history
  in ONE transaction. Either both rows change or none (lecture 104, "потерянное обновление").
* The UNIQUE constraint on `idempotency_key` decides a race of two requests with one key (ADR-0003, decision 5).
* Driver errors never leave this module raw: "database not reachable" -> StorageUnavailable (503);
  the SQL text and file paths go to the log only.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Mapping

from jobservice.application.ports import DuplicateIdempotencyKey, HistoryRecord, JobStateConflict, StorageUnavailable
from jobservice.domain.job import Job, JobError, JobStatus
from jobservice.infrastructure.migrator import connect

logger = logging.getLogger(__name__)

_FINAL = (JobStatus.DONE.value, JobStatus.ERROR.value)
_JOB_COLUMNS = (
    "id, operation, params_json, idempotency_key, request_hash, tool_version, correlation_id, status, "
    "result_json, error_code, error_message, error_details_json, created_at, started_at, finished_at"
)


def _dump(value: Mapping[str, Any] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _load(text: str | None) -> Any:
    return None if text is None else json.loads(text)


def _ts(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _dt(text: str | None) -> datetime | None:
    return None if text is None else datetime.fromisoformat(text)


class SqliteJobRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)

    # ---- connections and transactions -------------------------------------------------------------
    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        try:
            conn = connect(self._path)
        except sqlite3.Error as exc:
            logger.error("cannot open database: %s", exc)
            raise StorageUnavailable("database is not available") from exc
        try:
            yield conn
        except sqlite3.OperationalError as exc:  # locked, disk I/O, missing table ...
            logger.error("database operation failed: %s", exc)
            raise StorageUnavailable("database is not available") from exc
        finally:
            conn.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")  # take the write lock now: no upgrade deadlock later
            try:
                yield conn
            except BaseException:
                if conn.in_transaction:  # SQLite may have rolled back already (e.g. after a constraint abort)
                    conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")

    # ---- JobRepository ----------------------------------------------------------------------------
    def add(self, job: Job) -> None:
        try:
            with self._transaction() as conn:
                conn.execute(
                    f"INSERT INTO jobs ({_JOB_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        job.id,
                        job.operation,
                        _dump(dict(job.params)),
                        job.idempotency_key,
                        job.request_hash,
                        job.tool_version,
                        job.correlation_id,
                        *self._mutable_values(job),
                        _ts(job.created_at),
                        _ts(job.started_at),
                        _ts(job.finished_at),
                    ),
                )
                self._insert_history(conn, job, None)
        except sqlite3.IntegrityError as exc:
            owner = self._job_id_for_key(job.idempotency_key)
            if owner is not None:
                raise DuplicateIdempotencyKey(job.idempotency_key, owner) from exc
            if self.get(job.id) is not None:
                raise ValueError(f"Job {job.id} already exists") from exc
            raise

    def save(self, job: Job) -> None:
        with self._transaction() as conn:
            row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job.id,)).fetchone()
            if row is None:
                raise LookupError(f"Job {job.id} was never added")
            stored = row[0]
            if stored in _FINAL and stored != job.status.value:
                raise JobStateConflict(job.id, stored, job.status.value)
            conn.execute(
                "UPDATE jobs SET status = ?, result_json = ?, error_code = ?, error_message = ?, "
                "error_details_json = ?, started_at = ?, finished_at = ? WHERE id = ?",
                (*self._mutable_values(job), _ts(job.started_at), _ts(job.finished_at), job.id),
            )
            if stored != job.status.value:
                self._insert_history(conn, job, stored)

    def get(self, job_id: str) -> Job | None:
        with self._connection() as conn:
            row = conn.execute(f"SELECT {_JOB_COLUMNS} FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return None if row is None else self._to_job(row)

    def find_by_key(self, idempotency_key: str) -> Job | None:
        with self._connection() as conn:
            row = conn.execute(
                f"SELECT {_JOB_COLUMNS} FROM jobs WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
        return None if row is None else self._to_job(row)

    def find_unfinished(self) -> list[Job]:
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT {_JOB_COLUMNS} FROM jobs WHERE status IN ('created', 'running') ORDER BY created_at"
            ).fetchall()
        return [self._to_job(r) for r in rows]

    # ---- diagnostics and health -------------------------------------------------------------------
    def history(self, job_id: str) -> list[HistoryRecord]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT job_id, from_status, to_status, at, error_code FROM job_history WHERE job_id = ? ORDER BY id",
                (job_id,),
            ).fetchall()
        return [HistoryRecord(r[0], r[1], r[2], datetime.fromisoformat(r[3]), r[4]) for r in rows]

    def ping(self) -> None:
        with self._connection() as conn:
            conn.execute("SELECT 1 FROM jobs LIMIT 1").fetchall()

    def __len__(self) -> int:
        with self._connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    # ---- internals --------------------------------------------------------------------------------
    def _insert_history(self, conn: sqlite3.Connection, job: Job, from_status: str | None) -> None:
        at = job.finished_at or job.started_at or job.created_at
        conn.execute(
            "INSERT INTO job_history (job_id, from_status, to_status, error_code, at) VALUES (?, ?, ?, ?, ?)",
            (job.id, from_status, job.status.value, job.error.code if job.error else None, _ts(at)),
        )

    def _job_id_for_key(self, key: str) -> str | None:
        with self._connection() as conn:
            row = conn.execute("SELECT id FROM jobs WHERE idempotency_key = ?", (key,)).fetchone()
        return None if row is None else row[0]

    @staticmethod
    def _mutable_values(job: Job) -> tuple[Any, ...]:
        err = job.error
        return (
            job.status.value,
            _dump(dict(job.result)) if job.result is not None else None,
            err.code if err else None,
            err.message if err else None,
            _dump(dict(err.details)) if err and err.details is not None else None,
        )

    @staticmethod
    def _to_job(row: tuple[Any, ...]) -> Job:
        (job_id, operation, params_json, key, req_hash, tool_version, corr, status,
         result_json, err_code, err_message, err_details_json, created, started, finished) = row
        error = JobError(err_code, err_message, _load(err_details_json)) if err_code is not None else None
        return Job.restore(
            job_id=job_id,
            operation=operation,
            params=_load(params_json),
            idempotency_key=key,
            request_hash=req_hash,
            tool_version=tool_version,
            correlation_id=corr,
            status=status,
            result=_load(result_json),
            error=error,
            created_at=_dt(created),
            started_at=_dt(started),
            finished_at=_dt(finished),
        )
