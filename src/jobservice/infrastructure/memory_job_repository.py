"""In-memory implementation of JobRepository (Practice 3; replaced by SQL in Practice 4).

Behaves like a database where it matters for the core:
  * stores COPIES — changing a Job object after `save` does not change what is stored;
  * `add` enforces a unique idempotency key (like a UNIQUE constraint);
  * one lock makes every method atomic.
"""

from __future__ import annotations

import copy
import threading

from jobservice.application.ports import DuplicateIdempotencyKey
from jobservice.domain.job import Job


class InMemoryJobRepository:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._by_key: dict[str, str] = {}
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

    def save(self, job: Job) -> None:
        with self._lock:
            if job.id not in self._jobs:
                raise LookupError(f"Job {job.id} was never added")
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

    def __len__(self) -> int:
        with self._lock:
            return len(self._jobs)
