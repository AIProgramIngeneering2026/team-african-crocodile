"""Dispatcher — the scenario "run a Job" (docs/architecture.md, section 2).

Order of steps for `submit` (same order as POST /jobs in openapi.yaml):
  1. Idempotency key is present and well-formed     -> else IdempotencyKeyRequired
  2. operation is a string, params is an object     -> else MalformedRequest
  3. Key already used: same body -> replay the existing Job (the Tool is NOT run again);
                       other body -> IdempotencyKeyReused
  4. Registry knows the operation                   -> else UnknownOperation
  5. Tool.validate(params)                          -> else ParamsInvalid (all wrong fields)
  6. Job created and stored (created)
  7. Job started (running), Tool.execute, Job finished (done / error) — a crash of the Tool also ends in error.

Steps 1–5 create nothing. The Dispatcher never names a concrete Tool: it gets one from the Registry.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from jobservice import codes
from jobservice.application.errors import (
    IdempotencyKeyRequired,
    IdempotencyKeyReused,
    JobNotFound,
    MalformedRequest,
    ToolContractViolation,
    UnknownOperation,
)
from jobservice.application.ports import DuplicateIdempotencyKey, JobRepository
from jobservice.application.registry import Registry
from jobservice.application.tool import Tool, ToolContext, ToolResult
from jobservice.domain.job import Job, JobError

logger = logging.getLogger(__name__)

Clock = Callable[[], datetime]

DEFAULT_DEADLINE_S = 17.0  # longest Tool budget in tool-contract.md section 4.2
_KEY_PATTERN = re.compile(r"^[\x21-\x7E]{1,128}$")
_TOOL_CRASH_MESSAGE = "The operation failed unexpectedly. Use the correlation id when reporting it."


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class SubmitOutcome:
    job: Job
    replayed: bool  # True: an existing Job was returned for a repeated Idempotency-Key (HTTP 200, not 201)


def check_idempotency_key(key: Any) -> str:
    """Raise IdempotencyKeyRequired unless `key` is 1–128 visible ASCII characters (ADR-0003, decision 1).

    Public so that the HTTP layer can apply the contract's order of checks (key before body parsing)
    with the same rule instead of a copy of it.
    """
    if not isinstance(key, str) or not _KEY_PATTERN.match(key):
        raise IdempotencyKeyRequired()
    return key


def request_hash(operation: str, params: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical JSON of the body AS SENT (before defaults), ADR-0003 decision 2."""
    try:
        canonical = json.dumps(
            {"operation": operation, "params": params},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    except (TypeError, ValueError) as exc:
        raise MalformedRequest("Request body contains values that are not JSON.") from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class Dispatcher:
    def __init__(
        self,
        registry: Registry,
        jobs: JobRepository,
        *,
        clock: Clock | None = None,
        new_id: Callable[[], str] | None = None,
    ) -> None:
        self._registry = registry
        self._jobs = jobs
        self._clock = clock or utc_now
        self._new_id = new_id or (lambda: str(uuid.uuid4()))

    # ---- public API ---------------------------------------------------------------------------------
    def submit(
        self,
        operation: Any,
        params: Any,
        *,
        idempotency_key: Any,
        correlation_id: str | None = None,
    ) -> SubmitOutcome:
        check_idempotency_key(idempotency_key)
        if not isinstance(operation, str) or not operation:
            raise MalformedRequest("Field 'operation' must be a non-empty string.")
        if not isinstance(params, Mapping):
            raise MalformedRequest("Field 'params' must be an object.")
        body_hash = request_hash(operation, params)

        existing = self._jobs.find_by_key(idempotency_key)
        if existing is not None:
            return self._replay(existing, body_hash)

        tool = self._registry.get(operation)
        if tool is None:
            raise UnknownOperation(operation, self._registry.names())

        normalized = tool.validate(params)  # raises ParamsInvalid -> nothing is stored
        if not isinstance(normalized, Mapping):
            raise ToolContractViolation(f"{tool.version}: validate() must return a mapping")

        job = Job(
            job_id=self._new_id(),
            operation=operation,
            params=normalized,
            idempotency_key=idempotency_key,
            request_hash=body_hash,
            tool_version=tool.version,
            correlation_id=correlation_id or uuid.uuid4().hex[:12],
            created_at=self._clock(),
        )
        try:
            self._jobs.add(job)
        except DuplicateIdempotencyKey:
            # A parallel request with the same key won the race between find_by_key and add.
            winner = self._jobs.find_by_key(idempotency_key)
            if winner is None:  # cannot happen with a correct repository
                raise
            return self._replay(winner, body_hash)

        self._run(job, tool)
        return SubmitOutcome(job=job, replayed=False)

    def get(self, job_id: Any) -> Job:
        job = self._jobs.get(job_id) if isinstance(job_id, str) else None
        if job is None:
            raise JobNotFound()
        return job

    def recover_interrupted(self) -> list[str]:
        """Call once at startup, before accepting requests (ADR-0002, decision 3).

        In one process every Job still in `created` or `running` at startup belonged to the
        previous, stopped process: no Tool is working on it any more.
        """
        recovered: list[str] = []
        for job in self._jobs.find_unfinished():
            job.interrupt(self._clock())
            self._jobs.save(job)
            recovered.append(job.id)
            logger.warning(
                "job interrupted by restart",
                extra={"job_id": job.id, "correlation_id": job.correlation_id},
            )
        return recovered

    # ---- internals ----------------------------------------------------------------------------------
    @staticmethod
    def _replay(existing: Job, body_hash: str) -> SubmitOutcome:
        if existing.request_hash != body_hash:
            raise IdempotencyKeyReused(existing.id)
        return SubmitOutcome(job=existing, replayed=True)

    def _run(self, job: Job, tool: Tool) -> None:
        job.start(self._clock())
        self._jobs.save(job)  # `running` is visible to replays and to startup recovery

        ctx = ToolContext(correlation_id=job.correlation_id, deadline_s=DEFAULT_DEADLINE_S)
        try:
            outcome = tool.execute(copy.deepcopy(dict(job.params)), ctx)
        except Exception:  # noqa: BLE001 — any crash of a Tool becomes a Job error
            logger.exception(
                "tool crashed",
                extra={"job_id": job.id, "correlation_id": job.correlation_id, "tool": tool.version},
            )
            job.fail(JobError(codes.TOOL_INTERNAL_ERROR, _TOOL_CRASH_MESSAGE), self._clock())
        else:
            self._finish(job, tool, outcome)
        # BaseException (process stop, KeyboardInterrupt) is deliberately not caught: the Job stays
        # `running` in storage and recover_interrupted() moves it to `error` on the next start.
        self._jobs.save(job)
        logger.info(
            "job finished",
            extra={"job_id": job.id, "correlation_id": job.correlation_id, "status": job.status.value},
        )

    def _finish(self, job: Job, tool: Tool, outcome: Any) -> None:
        now = self._clock()
        if not isinstance(outcome, ToolResult):
            logger.error(
                "tool broke the contract: execute() returned %r",
                type(outcome).__name__,
                extra={"job_id": job.id, "correlation_id": job.correlation_id, "tool": tool.version},
            )
            job.fail(JobError(codes.TOOL_INTERNAL_ERROR, _TOOL_CRASH_MESSAGE), now)
        elif outcome.ok:
            assert outcome.data is not None  # guaranteed by ToolResult
            job.complete(outcome.data, now)
        else:
            assert outcome.error is not None
            err = outcome.error
            details = dict(err.details) if err.details is not None else None
            job.fail(JobError(err.code, err.message, details), now)
