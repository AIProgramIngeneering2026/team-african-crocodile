"""DTOs of the HTTP contract: what leaves the service (schemas `Job`, `ErrorResponse`, `Health` in openapi.yaml).

The domain Job is NOT sent as it is: `idempotency_key` and `request_hash` are internal and are never returned.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from jobservice.domain.job import Job


def iso_utc(value: datetime | None) -> str | None:
    """`2026-11-14T14:20:00.123Z` — ISO 8601 in UTC, as the contract says."""
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def plain(value: Any) -> Any:
    """Read-only views (MappingProxyType, tuples) -> plain JSON types."""
    if isinstance(value, Mapping):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def job_to_dto(job: Job) -> dict[str, Any]:
    error = job.error
    return {
        "id": job.id,
        "operation": job.operation,
        "params": plain(job.params),
        "status": job.status.value,
        "result": plain(job.result) if job.result is not None else None,
        "error": (
            {"code": error.code, "message": error.message, "details": plain(error.details)}
            if error is not None
            else None
        ),
        "tool_version": job.tool_version,
        "correlation_id": job.correlation_id,
        "created_at": iso_utc(job.created_at),
        "started_at": iso_utc(job.started_at),
        "finished_at": iso_utc(job.finished_at),
    }


def error_body(code: str, message: str, details: Mapping[str, Any] | None, correlation_id: str) -> dict[str, Any]:
    """The one error format of the service (schema `ErrorResponse`)."""
    return {
        "error": {
            "code": code,
            "message": message,
            "details": plain(details) if details is not None else None,
            "correlation_id": correlation_id,
        }
    }
