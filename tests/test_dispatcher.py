"""Dispatcher: normal path, request errors, Tool failures and crashes, idempotency, recovery."""

from __future__ import annotations

import pytest

from helpers import FakeTool, crashing, failing, new_job
from jobservice import codes
from jobservice.application import (
    Dispatcher,
    DuplicateIdempotencyKey,
    IdempotencyKeyRequired,
    IdempotencyKeyReused,
    JobNotFound,
    MalformedRequest,
    ParamsInvalid,
    Registry,
    ToolContractViolation,
    ToolResult,
    UnknownOperation,
)
from jobservice.application.dispatcher import request_hash
from jobservice.domain import JobStatus
from jobservice.infrastructure import InMemoryJobRepository


# ---- normal path -------------------------------------------------------------------------------------
def test_normal_path_created_running_done_and_stored(dispatcher, repo, fake_tool):
    outcome = dispatcher.submit("fake", {"x": 1}, idempotency_key="k1", correlation_id="corr-42")
    job = outcome.job
    assert not outcome.replayed
    assert job.status is JobStatus.DONE
    assert job.result == {"echo": {"x": 1}}
    assert job.tool_version == "fake/1" and job.correlation_id == "corr-42"
    stored = repo.get(job.id)
    assert stored.status is JobStatus.DONE and stored.result == job.result
    assert fake_tool.seen_contexts[0].correlation_id == "corr-42"


def test_get_returns_stored_job(dispatcher):
    job = dispatcher.submit("fake", {"x": 1}, idempotency_key="k1").job
    assert dispatcher.get(job.id).id == job.id


@pytest.mark.parametrize("job_id", ["no-such-id", "", None, 123])
def test_get_unknown_job(dispatcher, job_id):
    with pytest.raises(JobNotFound) as info:
        dispatcher.get(job_id)
    assert info.value.code == codes.JOB_NOT_FOUND


# ---- errors before a Job exists: nothing is stored ------------------------------------------------
def test_unknown_operation(dispatcher, repo):
    with pytest.raises(UnknownOperation) as info:
        dispatcher.submit("convert_currency", {}, idempotency_key="k1")
    err = info.value
    assert err.code == codes.UNKNOWN_OPERATION
    assert err.details == {"operation": "convert_currency", "available_operations": ["fake"]}
    assert len(repo) == 0


def test_invalid_params_name_the_field_and_store_nothing(dispatcher, repo, fake_tool):
    with pytest.raises(ParamsInvalid) as info:
        dispatcher.submit("fake", {"bad": "?"}, idempotency_key="k1")
    assert info.value.code == codes.VALIDATION_ERROR
    assert info.value.details["fields"][0]["field"] == "params.bad"
    assert len(repo) == 0 and fake_tool.execute_calls == 0


def test_rejected_request_does_not_burn_the_key(dispatcher):
    with pytest.raises(ParamsInvalid):
        dispatcher.submit("fake", {"bad": "?"}, idempotency_key="k1")
    assert dispatcher.submit("fake", {"x": 1}, idempotency_key="k1").job.status is JobStatus.DONE


@pytest.mark.parametrize("key", [None, "", "has space", "x" * 129, "ключ", 5])
def test_missing_or_invalid_idempotency_key(dispatcher, key):
    with pytest.raises(IdempotencyKeyRequired):
        dispatcher.submit("fake", {"x": 1}, idempotency_key=key)


@pytest.mark.parametrize(("operation", "params"), [(None, {}), ("", {}), ("fake", []), ("fake", "x"), ("fake", {"x": object()})])
def test_malformed_envelope(dispatcher, operation, params):
    with pytest.raises(MalformedRequest):
        dispatcher.submit(operation, params, idempotency_key="k1")


# ---- the Tool's answer and crash become Job transitions ---------------------------------------------
def make(tool: FakeTool, repo, clock) -> Dispatcher:
    reg = Registry()
    reg.register(tool)
    return Dispatcher(reg, repo, clock=clock)


def test_tool_failure_becomes_job_error_and_is_kept(repo, clock):
    d = make(FakeTool(behaviour=failing("SOMETHING_FAILED")), repo, clock)
    job = d.submit("fake", {"x": 1}, idempotency_key="k1").job
    assert job.status is JobStatus.ERROR
    assert (job.error.code, job.error.details) == ("SOMETHING_FAILED", {"why": "test"})
    assert repo.get(job.id).status is JobStatus.ERROR


def test_tool_crash_becomes_job_error_without_internal_details(repo, clock):
    d = make(FakeTool(behaviour=crashing(RuntimeError("secret stack detail"))), repo, clock)
    job = d.submit("fake", {"x": 1}, idempotency_key="k1").job
    assert job.status is JobStatus.ERROR
    assert job.error.code == codes.TOOL_INTERNAL_ERROR
    assert "secret" not in job.error.message
    assert repo.get(job.id).status is JobStatus.ERROR


@pytest.mark.parametrize("garbage", [None, {"value": 1}, "done", 42])
def test_tool_returning_garbage_becomes_job_error(repo, clock, garbage):
    d = make(FakeTool(behaviour=lambda p: garbage), repo, clock)
    job = d.submit("fake", {"x": 1}, idempotency_key="k1").job
    assert job.status is JobStatus.ERROR and job.error.code == codes.TOOL_INTERNAL_ERROR


def test_tool_cannot_change_the_stored_params(repo, clock):
    def mutate(params):
        params["x"] = "changed by tool"
        return ToolResult.success({})

    d = make(FakeTool(behaviour=mutate), repo, clock)
    job = d.submit("fake", {"x": 1}, idempotency_key="k1").job
    assert job.params == {"x": 1} and repo.get(job.id).params == {"x": 1}


def test_validate_returning_garbage_is_an_internal_error_and_stores_nothing(repo, clock):
    tool = FakeTool()
    tool.validate = lambda params: None  # type: ignore[method-assign]
    with pytest.raises(ToolContractViolation):
        make(tool, repo, clock).submit("fake", {"x": 1}, idempotency_key="k1")
    assert len(repo) == 0


def test_new_tool_needs_no_dispatcher_change(repo, clock):
    """OCP: a brand-new Tool works after one register() call."""
    reg = Registry()
    reg.register(FakeTool("reverse_text", behaviour=lambda p: ToolResult.success({"text": p["t"][::-1]})))
    job = Dispatcher(reg, repo, clock=clock).submit("reverse_text", {"t": "abc"}, idempotency_key="k1").job
    assert job.result == {"text": "cba"}


# ---- idempotency (ADR-0003) --------------------------------------------------------------------------
def test_same_key_different_body_is_rejected(dispatcher, repo):
    first = dispatcher.submit("fake", {"x": 1}, idempotency_key="k1").job
    with pytest.raises(IdempotencyKeyReused) as info:
        dispatcher.submit("fake", {"x": 2}, idempotency_key="k1")
    assert info.value.details == {"existing_job_id": first.id}
    assert len(repo) == 1


def test_hash_ignores_key_order_but_not_values():
    assert request_hash("op", {"a": 1, "b": 2}) == request_hash("op", {"b": 2, "a": 1})
    assert request_hash("op", {"a": 1}) != request_hash("op", {"a": 2})
    assert request_hash("op", {"a": 1}) != request_hash("other", {"a": 1})


class RacingRepository(InMemoryJobRepository):
    """Another request inserts the same key between our find_by_key and add."""

    def __init__(self, rival):
        super().__init__()
        self._rival = rival
        self._raced = False

    def find_by_key(self, key):
        found = super().find_by_key(key)
        if found is None and not self._raced:
            self._raced = True
            super().add(self._rival)
            return None
        return found


def test_parallel_insert_with_same_key_returns_the_winner(clock):
    rival = new_job(("start", "complete"), idempotency_key="k1", request_hash=request_hash("fake", {"x": 1}))
    repo = RacingRepository(rival)
    tool = FakeTool()
    d = make(tool, repo, clock)
    outcome = d.submit("fake", {"x": 1}, idempotency_key="k1")
    assert outcome.replayed and outcome.job.id == rival.id
    assert tool.execute_calls == 0 and len(repo) == 1


def test_repository_enforces_unique_key():
    repo = InMemoryJobRepository()
    repo.add(new_job(idempotency_key="same"))
    with pytest.raises(DuplicateIdempotencyKey):
        repo.add(new_job(idempotency_key="same"))

