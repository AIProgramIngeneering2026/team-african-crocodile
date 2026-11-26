"""Job — the unit of work and its lifecycle (docs/architecture.md, section 3).

The transition rule lives HERE and only here. Callers never assign a status; they send a command
(`start`, `complete`, `fail`, `interrupt`) and the Job either moves or raises `InvalidJobTransition`.
A refused command leaves the Job exactly as it was.

Transition table (command | from | to):

    start      created  -> running
    complete   running  -> done
    fail       running  -> error
    interrupt  created  -> error      (service restarted before the Job was started)
    interrupt  running  -> error      (service restarted while the Tool was working)

Everything else is forbidden. `done` and `error` are final: no command leaves them.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from jobservice import codes


class JobStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"

    @property
    def is_final(self) -> bool:
        return self in (JobStatus.DONE, JobStatus.ERROR)


class JobCommand(str, Enum):
    START = "start"
    COMPLETE = "complete"
    FAIL = "fail"
    INTERRUPT = "interrupt"


TRANSITIONS: Mapping[tuple[JobCommand, JobStatus], JobStatus] = MappingProxyType(
    {
        (JobCommand.START, JobStatus.CREATED): JobStatus.RUNNING,
        (JobCommand.COMPLETE, JobStatus.RUNNING): JobStatus.DONE,
        (JobCommand.FAIL, JobStatus.RUNNING): JobStatus.ERROR,
        (JobCommand.INTERRUPT, JobStatus.CREATED): JobStatus.ERROR,
        (JobCommand.INTERRUPT, JobStatus.RUNNING): JobStatus.ERROR,
    }
)


class InvalidJobTransition(Exception):
    """A command that the transition table does not allow from the current state."""

    code = codes.INVALID_JOB_TRANSITION

    def __init__(self, job_id: str, command: JobCommand, current: JobStatus) -> None:
        self.job_id = job_id
        self.command = command
        self.current = current
        super().__init__(f"Job {job_id}: command '{command.value}' is not allowed in state '{current.value}'.")


@dataclass(frozen=True)
class JobError:
    """What went wrong with a Job. Same shape as `Error` in openapi.yaml."""

    code: str
    message: str
    details: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.code or not isinstance(self.code, str):
            raise ValueError("JobError.code must be a non-empty string")
        if not isinstance(self.message, str):
            raise ValueError("JobError.message must be a string")


class Job:
    """One requested operation and everything that happened to it.

    Invariants (architecture.md, section 3):
      1. status == done   <=> result is not None and error is None
      2. status == error  <=> error is not None and result is None
      3. finished_at is set <=> status is final
      4. operation, params, idempotency_key, request_hash, tool_version never change
      5. a final Job never changes again
    """

    def __init__(
        self,
        *,
        job_id: str,
        operation: str,
        params: Mapping[str, Any],
        idempotency_key: str,
        request_hash: str,
        tool_version: str,
        correlation_id: str,
        created_at: datetime,
    ) -> None:
        if not job_id:
            raise ValueError("job_id is required")
        if not operation:
            raise ValueError("operation is required")
        self._id = job_id
        self._operation = operation
        self._params: dict[str, Any] = copy.deepcopy(dict(params))  # own copy: caller cannot change it later
        self._idempotency_key = idempotency_key
        self._request_hash = request_hash
        self._tool_version = tool_version
        self._correlation_id = correlation_id
        self._status = JobStatus.CREATED
        self._result: dict[str, Any] | None = None
        self._error: JobError | None = None
        self._created_at = created_at
        self._started_at: datetime | None = None
        self._finished_at: datetime | None = None

    # ---- rehydration ------------------------------------------------------------------------------
    @classmethod
    def restore(
        cls,
        *,
        job_id: str,
        operation: str,
        params: Mapping[str, Any],
        idempotency_key: str,
        request_hash: str,
        tool_version: str,
        correlation_id: str,
        status: JobStatus | str,
        result: Mapping[str, Any] | None,
        error: JobError | None,
        created_at: datetime,
        started_at: datetime | None,
        finished_at: datetime | None,
    ) -> "Job":
        """Rebuild a Job that was stored earlier (used only by repositories).

        Restoring is not a transition: it brings back a state that the commands above already produced.
        The invariants are checked again, so a damaged row cannot become a Job that breaks them.
        """
        job = cls(
            job_id=job_id,
            operation=operation,
            params=params,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            tool_version=tool_version,
            correlation_id=correlation_id,
            created_at=created_at,
        )
        status = JobStatus(status)
        if (status is JobStatus.DONE) != (result is not None):
            raise ValueError(f"stored Job {job_id}: result must be set exactly when status is done")
        if (status is JobStatus.ERROR) != (error is not None):
            raise ValueError(f"stored Job {job_id}: error must be set exactly when status is error")
        if status.is_final != (finished_at is not None):
            raise ValueError(f"stored Job {job_id}: finished_at must be set exactly when the Job is final")
        if status is JobStatus.CREATED and started_at is not None:
            raise ValueError(f"stored Job {job_id}: a created Job has no started_at")
        if status is JobStatus.RUNNING and started_at is None:
            raise ValueError(f"stored Job {job_id}: a running Job needs started_at")
        if error is not None and not isinstance(error, JobError):
            raise TypeError("error must be a JobError")
        job._status = status
        job._result = None if result is None else copy.deepcopy(dict(result))
        job._error = error
        job._started_at = started_at
        job._finished_at = finished_at
        return job

    # ---- read-only view ---------------------------------------------------------------------------
    @property
    def id(self) -> str:
        return self._id

    @property
    def operation(self) -> str:
        return self._operation

    @property
    def params(self) -> Mapping[str, Any]:
        return MappingProxyType(self._params)

    @property
    def idempotency_key(self) -> str:
        return self._idempotency_key

    @property
    def request_hash(self) -> str:
        return self._request_hash

    @property
    def tool_version(self) -> str:
        return self._tool_version

    @property
    def correlation_id(self) -> str:
        return self._correlation_id

    @property
    def status(self) -> JobStatus:
        return self._status

    @property
    def result(self) -> Mapping[str, Any] | None:
        return None if self._result is None else MappingProxyType(self._result)

    @property
    def error(self) -> JobError | None:
        return self._error

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def started_at(self) -> datetime | None:
        return self._started_at

    @property
    def finished_at(self) -> datetime | None:
        return self._finished_at

    @property
    def is_final(self) -> bool:
        return self._status.is_final

    # ---- commands ---------------------------------------------------------------------------------
    def start(self, now: datetime) -> None:
        target = self._target(JobCommand.START)
        self._status = target
        self._started_at = now

    def complete(self, result: Mapping[str, Any], now: datetime) -> None:
        target = self._target(JobCommand.COMPLETE)  # check the transition first ...
        if not isinstance(result, Mapping):  # ... then the argument; only then change anything
            raise TypeError("result must be a mapping")
        self._result = copy.deepcopy(dict(result))
        self._status = target
        self._finished_at = now

    def fail(self, error: JobError, now: datetime) -> None:
        target = self._target(JobCommand.FAIL)
        self._set_error(target, error, now)

    def interrupt(self, now: datetime, message: str | None = None) -> None:
        """Startup recovery: the process that was executing this Job is gone (ADR-0002, decision 3)."""
        target = self._target(JobCommand.INTERRUPT)
        error = JobError(
            code=codes.JOB_INTERRUPTED,
            message=message
            or "The service restarted before the job finished. Send the request again with a new Idempotency-Key.",
            details={"interrupted_in": self._status.value},
        )
        self._set_error(target, error, now)

    # ---- internals --------------------------------------------------------------------------------
    def _target(self, command: JobCommand) -> JobStatus:
        target = TRANSITIONS.get((command, self._status))
        if target is None:
            raise InvalidJobTransition(self._id, command, self._status)
        return target

    def _set_error(self, target: JobStatus, error: JobError, now: datetime) -> None:
        if not isinstance(error, JobError):
            raise TypeError("error must be a JobError")
        self._error = error
        self._status = target
        self._finished_at = now

    def __repr__(self) -> str:
        return f"Job(id={self._id!r}, operation={self._operation!r}, status={self._status.value!r})"
