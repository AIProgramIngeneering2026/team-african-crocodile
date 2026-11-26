"""Storage port of the application (Repository pattern, lecture 103).

The methods describe what the Dispatcher needs, not generic CRUD:
  * `add` must behave like a unique constraint on the idempotency key (ADR-0003, decision 5);
  * `find_unfinished` exists for startup recovery (ADR-0002, decision 3);
  * `add` and `save` write the Job row AND its history record atomically (ADR-0006): both or neither.

Implementations:
  * `infrastructure.memory_job_repository.InMemoryJobRepository` — unit tests only;
  * `infrastructure.sqlite_job_repository.SqliteJobRepository` — the service (Practice 4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Sequence

from jobservice import codes
from jobservice.domain.job import Job


class DuplicateIdempotencyKey(Exception):
    def __init__(self, key: str, existing_job_id: str) -> None:
        super().__init__(f"Idempotency key already belongs to job {existing_job_id}")
        self.key = key
        self.existing_job_id = existing_job_id


class StorageUnavailable(Exception):
    """The storage cannot be reached right now (locked, disk error, file missing). -> 503, retry is safe."""

    code = codes.STORAGE_UNAVAILABLE


class JobStateConflict(Exception):
    """`save` was asked to overwrite a Job that is already final in storage with a different state.

    The domain forbids leaving a final state, so this can only be a lost update (two writers on one Job).
    The stored Job is not changed. -> 409 INVALID_JOB_TRANSITION.
    """

    code = codes.INVALID_JOB_TRANSITION

    def __init__(self, job_id: str, stored: str, attempted: str) -> None:
        super().__init__(f"Job {job_id} is already '{stored}' in storage; refusing to store '{attempted}'.")
        self.job_id = job_id
        self.stored = stored
        self.attempted = attempted


@dataclass(frozen=True)
class HistoryRecord:
    """One transition of a Job, written in the same transaction as the Job itself."""

    job_id: str
    from_status: str | None  # None for the record that creates the Job
    to_status: str
    at: datetime
    error_code: str | None = None


class JobRepository(Protocol):
    def add(self, job: Job) -> None:
        """Store a NEW Job and its first history record. Raises DuplicateIdempotencyKey if its key is taken."""
        ...

    def save(self, job: Job) -> None:
        """Store the current state of an EXISTING Job; if the status changed, also a history record."""
        ...

    def get(self, job_id: str) -> Job | None: ...

    def find_by_key(self, idempotency_key: str) -> Job | None: ...

    def find_unfinished(self) -> Sequence[Job]:
        """Jobs in `created` or `running`."""
        ...


class StorageProbe(Protocol):
    """Used by the health check only."""

    def ping(self) -> None:
        """Return if the storage answers; raise StorageUnavailable otherwise."""
        ...
