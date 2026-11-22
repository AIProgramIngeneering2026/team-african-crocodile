"""Storage port of the application (Repository pattern, lecture 103).

The methods describe what the Dispatcher needs, not generic CRUD:
  * `add` must behave like a unique constraint on the idempotency key (ADR-0003, decision 5);
  * `find_unfinished` exists for startup recovery (ADR-0002, decision 3).

Practice 3: `infrastructure.memory_job_repository.InMemoryJobRepository`.
Practice 4: an SQL implementation of the same protocol.
"""

from __future__ import annotations

from typing import Protocol, Sequence

from jobservice.domain.job import Job


class DuplicateIdempotencyKey(Exception):
    def __init__(self, key: str, existing_job_id: str) -> None:
        super().__init__(f"Idempotency key already belongs to job {existing_job_id}")
        self.key = key
        self.existing_job_id = existing_job_id


class JobRepository(Protocol):
    def add(self, job: Job) -> None:
        """Store a NEW Job. Raises DuplicateIdempotencyKey if its key is already taken."""
        ...

    def save(self, job: Job) -> None:
        """Store the current state of an EXISTING Job."""
        ...

    def get(self, job_id: str) -> Job | None: ...

    def find_by_key(self, idempotency_key: str) -> Job | None: ...

    def find_unfinished(self) -> Sequence[Job]:
        """Jobs in `created` or `running`."""
        ...
