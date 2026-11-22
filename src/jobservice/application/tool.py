"""The Tool contract (docs/tool-contract.md, section 1).

The Dispatcher talks to every operation only through `Tool`. Two validation stages:
  * `validate(params)` — form of parameters. Raises `ParamsInvalid` listing ALL wrong fields.
    Must be pure: no I/O, no network. Nothing is stored when it fails.
  * `execute(params, ctx)` — meaning and execution. Expected failures are RETURNED as
    `ToolResult.failure(ToolError(...))`; the Job then ends in `error` and stays in history.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from jobservice import codes
from jobservice.application.errors import ApplicationError


@dataclass(frozen=True)
class FieldError:
    field: str  # JSON path in the request, e.g. "params.precision"
    code: str  # a FieldErrorCode from openapi.yaml
    message: str
    rejected_value: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "code": self.code,
            "message": self.message,
            "rejected_value": self.rejected_value,
        }


class ParamsInvalid(ApplicationError):
    """Stage 1: wrong parameters. -> 422 VALIDATION_ERROR, no Job is created."""

    code = codes.VALIDATION_ERROR

    def __init__(self, errors: Sequence[FieldError]) -> None:
        if not errors:
            raise ValueError("ParamsInvalid needs at least one FieldError")
        self.errors: list[FieldError] = list(errors)
        n = len(self.errors)
        message = "1 parameter is invalid." if n == 1 else f"{n} parameters are invalid."
        super().__init__(message, {"fields": [e.to_dict() for e in self.errors]})


@dataclass(frozen=True)
class ToolError:
    """Stage 2: a failure that becomes part of the Job history (Job.status = error)."""

    code: str
    message: str
    details: Mapping[str, Any] | None = None
    retryable: bool = False


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    data: Mapping[str, Any] | None = None
    error: ToolError | None = None

    def __post_init__(self) -> None:
        if self.ok and (not isinstance(self.data, Mapping) or self.error is not None):
            raise ValueError("a successful ToolResult needs a mapping in data and no error")
        if not self.ok and (not isinstance(self.error, ToolError) or self.data is not None):
            raise ValueError("a failed ToolResult needs a ToolError and no data")

    @staticmethod
    def success(data: Mapping[str, Any]) -> "ToolResult":
        return ToolResult(ok=True, data=data)

    @staticmethod
    def failure(error: ToolError) -> "ToolResult":
        return ToolResult(ok=False, error=error)


@dataclass(frozen=True)
class ToolContext:
    correlation_id: str
    deadline_s: float


@runtime_checkable
class Tool(Protocol):
    name: str  # operation name = Registry key, e.g. "convert_unit"
    version: str  # saved in Job.tool_version, e.g. "convert_unit/1"

    def validate(self, params: Mapping[str, Any]) -> Mapping[str, Any]:
        """Return normalised params or raise ParamsInvalid."""
        ...

    def execute(self, params: Mapping[str, Any], ctx: ToolContext) -> ToolResult:
        """Run the operation. Expected failures are returned, never raised."""
        ...
