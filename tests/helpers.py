"""Shared test helpers: a controllable clock and fake Tools.

Fake Tools prove two things at once: the Dispatcher works with ANY Tool behind the contract,
and a new Tool is added without touching the Dispatcher (only `registry.register`).
"""

from __future__ import annotations

import itertools
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from jobservice import codes
from jobservice.application import (
    FieldError,
    ParamsInvalid,
    ToolContext,
    ToolError,
    ToolResult,
)
from jobservice.domain import Job, JobError


class StepClock:
    """Every call returns a moment one second later than the previous one."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        self._now += timedelta(seconds=1)
        return self._now


class FakeTool:
    """Configurable Tool. `behaviour(params)` returns a ToolResult, raises, or returns garbage."""

    def __init__(self, name: str = "fake", behaviour: Callable[[Mapping[str, Any]], Any] | None = None) -> None:
        self.name = name
        self.version = f"{name}/1"
        self.behaviour = behaviour or (lambda p: ToolResult.success({"echo": dict(p)}))
        self.validate_calls = 0
        self.execute_calls = 0
        self.seen_contexts: list[ToolContext] = []

    def validate(self, params: Mapping[str, Any]) -> Mapping[str, Any]:
        self.validate_calls += 1
        if "bad" in params:
            raise ParamsInvalid([FieldError("params.bad", codes.FIELD_TYPE, "bad field", params["bad"])])
        return dict(params)

    def execute(self, params: Mapping[str, Any], ctx: ToolContext) -> ToolResult:
        self.execute_calls += 1
        self.seen_contexts.append(ctx)
        return self.behaviour(params)


def failing(code: str = "SOMETHING_FAILED") -> Callable[[Mapping[str, Any]], ToolResult]:
    return lambda p: ToolResult.failure(ToolError(code, "it failed", {"why": "test"}))


def crashing(exc: BaseException) -> Callable[[Mapping[str, Any]], Any]:
    def run(params: Mapping[str, Any]) -> Any:
        raise exc

    return run


_ids = itertools.count(1)


def new_job(status_path: tuple[str, ...] = (), **overrides: Any) -> Job:
    """A Job moved along `status_path` ('start', 'complete', 'fail', 'interrupt')."""
    clock = StepClock()
    job = Job(
        job_id=overrides.get("job_id", f"job-{next(_ids)}"),
        operation=overrides.get("operation", "fake"),
        params=overrides.get("params", {"x": 1}),
        idempotency_key=overrides.get("idempotency_key", f"key-{next(_ids)}"),
        request_hash=overrides.get("request_hash", "h"),
        tool_version="fake/1",
        correlation_id="corr-1",
        created_at=clock(),
    )
    for step in status_path:
        if step == "start":
            job.start(clock())
        elif step == "complete":
            job.complete({"ok": True}, clock())
        elif step == "fail":
            job.fail(JobError("SOMETHING_FAILED", "it failed"), clock())
        elif step == "interrupt":
            job.interrupt(clock())
        else:  # pragma: no cover
            raise ValueError(step)
    return job




class CountingTool:
    """Wraps a real Tool and counts `execute` calls — proves that a replay does not run the work again."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.name = inner.name
        self.version = inner.version
        self.execute_calls = 0

    def validate(self, params: Mapping[str, Any]) -> Mapping[str, Any]:
        return self.inner.validate(params)

    def execute(self, params: Mapping[str, Any], ctx: ToolContext) -> ToolResult:
        self.execute_calls += 1
        return self.inner.execute(params, ctx)


@contextmanager
def raw_db(path):
    """Direct SQL for tests. `with sqlite3.connect(...)` only commits — it does NOT close; this does both."""
    conn = sqlite3.connect(path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()
