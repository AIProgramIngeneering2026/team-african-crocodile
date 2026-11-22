"""Errors of the application layer. Each one carries a code from `jobservice.codes`.

They are raised BEFORE a Job exists (or when a Job cannot be found), so they never appear in history.
The HTTP layer (Practice 4) maps them to status codes; the core does not know HTTP.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from jobservice import codes


class ApplicationError(Exception):
    code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class MalformedRequest(ApplicationError):
    code = codes.MALFORMED_REQUEST


class IdempotencyKeyRequired(ApplicationError):
    code = codes.IDEMPOTENCY_KEY_REQUIRED

    def __init__(self) -> None:
        super().__init__("Idempotency-Key is required (1–128 visible ASCII characters).")


class IdempotencyKeyReused(ApplicationError):
    code = codes.IDEMPOTENCY_KEY_REUSED

    def __init__(self, existing_job_id: str) -> None:
        super().__init__(
            "This Idempotency-Key was already used with a different request body.",
            {"existing_job_id": existing_job_id},
        )


class UnknownOperation(ApplicationError):
    code = codes.UNKNOWN_OPERATION

    def __init__(self, operation: str, available: Sequence[str]) -> None:
        super().__init__(
            f"Operation '{operation}' is not supported.",
            {"operation": operation, "available_operations": list(available)},
        )
        self.operation = operation


class JobNotFound(ApplicationError):
    code = codes.JOB_NOT_FOUND

    def __init__(self) -> None:
        # The id is deliberately not echoed: the answer must not reveal anything (ADR-0004).
        super().__init__("Job not found.")


class ToolContractViolation(RuntimeError):
    """A Tool broke the Tool contract outside execute() (e.g. validate returned garbage).
    No Job exists at that point, so this is an internal error, not a Job error."""


class DuplicateTool(Exception):
    """Startup configuration error: two Tools registered under one operation name."""
