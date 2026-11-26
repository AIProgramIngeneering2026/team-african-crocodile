"""In-memory implementation of JobRepository — for unit tests only (ADR-0005, ADR-0006).

Behaves like the SQL repository where it matters for the core:
  * stores COPIES — changing a Job object after `save` does not change what is stored;
  * `add` enforces a unique idempotency key (like a UNIQUE constraint);
  * `add`/`save` write the Job and its history record together, under one lock (like one transaction);
  * `save` refuses to overwrite a final Job with another state (JobStateConflict), like the SQL version.
The same behaviour is checked for both implementations by tests/test_repository_contract.py.
"""

from __future__ import annotations

import copy
import threading

from jobservice.application.ports import DuplicateIdempotencyKey, HistoryRecord, JobStateConflict
from jobservice.domain.job import Job


def _event_time(job: Job):
    return job.finished_at or job.started_at or job.created_at


class InMemoryJobRepository:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._by_key: dict[str, str] = {}
        self._history: dict[str, list[HistoryRecord]] = {}
        self._lock = threading.Lock()

    def add(self, job: Job) -> None:
        with self._lock:
            if job.id in self._jobs:
                raise ValueError(f"Job {job.id} already exists")
            existing_id = self._by_key.get(job.idempotency_key)
            if existing_id is not None:
                raise DuplicateIdempotencyKey(job.idempotency_key, existing_id)
            self._jobs[job.id] = copy.deepcopy(job)
            self._by_key[job.idempotency_key] = job.id
            self._history[job.id] = [self._record(job, None)]

    def save(self, job: Job) -> None:
        with self._lock:
            stored = self._jobs.get(job.id)
            if stored is None:
                raise LookupError(f"Job {job.id} was never added")
            if stored.is_final and stored.status is not job.status:
                raise JobStateConflict(job.id, stored.status.value, job.status.value)
            if stored.status is not job.status:
                self._history[job.id].append(self._record(job, stored.status.value))
            self._jobs[job.id] = copy.deepcopy(job)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return copy.deepcopy(job) if job is not None else None

    def find_by_key(self, idempotency_key: str) -> Job | None:
        with self._lock:
            job_id = self._by_key.get(idempotency_key)
            return copy.deepcopy(self._jobs[job_id]) if job_id is not None else None

    def find_unfinished(self) -> list[Job]:
        with self._lock:
            return [copy.deepcopy(j) for j in self._jobs.values() if not j.is_final]

    def history(self, job_id: str) -> list[HistoryRecord]:
        with self._lock:
            return list(self._history.get(job_id, []))

    def ping(self) -> None:
        return None

    def __len__(self) -> int:
        with self._lock:
            return len(self._jobs)

    @staticmethod
    def _record(job: Job, from_status: str | None) -> HistoryRecord:
        return HistoryRecord(
            job_id=job.id,
            from_status=from_status,
            to_status=job.status.value,
            at=_event_time(job),
            error_code=job.error.code if job.error is not None else None,
        )
