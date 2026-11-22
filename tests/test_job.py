"""Job transition rules: allowed AND forbidden pairs."""

from __future__ import annotations

import itertools

import pytest

from helpers import StepClock, new_job
from jobservice import codes
from jobservice.domain import TRANSITIONS, InvalidJobTransition, Job, JobCommand, JobError, JobStatus

# How to bring a fresh Job into each status.
PATH_TO = {
    JobStatus.CREATED: (),
    JobStatus.RUNNING: ("start",),
    JobStatus.DONE: ("start", "complete"),
    JobStatus.ERROR: ("start", "fail"),
}


def send(job: Job, command: JobCommand) -> None:
    now = StepClock()()
    if command is JobCommand.START:
        job.start(now)
    elif command is JobCommand.COMPLETE:
        job.complete({"value": 1}, now)
    elif command is JobCommand.FAIL:
        job.fail(JobError("X", "x"), now)
    else:
        job.interrupt(now)


def snapshot(job: Job) -> tuple:
    return (job.status, job.result, job.error, job.started_at, job.finished_at)


def test_transition_table_matches_architecture_md():
    assert dict(TRANSITIONS) == {
        (JobCommand.START, JobStatus.CREATED): JobStatus.RUNNING,
        (JobCommand.COMPLETE, JobStatus.RUNNING): JobStatus.DONE,
        (JobCommand.FAIL, JobStatus.RUNNING): JobStatus.ERROR,
        (JobCommand.INTERRUPT, JobStatus.CREATED): JobStatus.ERROR,
        (JobCommand.INTERRUPT, JobStatus.RUNNING): JobStatus.ERROR,
    }


ALL_PAIRS = list(itertools.product(JobCommand, JobStatus))
ALLOWED = [p for p in ALL_PAIRS if p in TRANSITIONS]
FORBIDDEN = [p for p in ALL_PAIRS if p not in TRANSITIONS]


@pytest.mark.parametrize(("command", "status"), ALLOWED, ids=lambda v: v.value)
def test_allowed_transition_moves_the_job(command, status):
    job = new_job(PATH_TO[status])
    send(job, command)
    assert job.status is TRANSITIONS[(command, status)]


@pytest.mark.parametrize(("command", "status"), FORBIDDEN, ids=lambda v: v.value)
def test_forbidden_transition_raises_and_changes_nothing(command, status):
    job = new_job(PATH_TO[status])
    before = snapshot(job)
    with pytest.raises(InvalidJobTransition) as info:
        send(job, command)
    assert snapshot(job) == before
    assert info.value.code == codes.INVALID_JOB_TRANSITION
    assert info.value.command is command and info.value.current is status


def test_final_states_have_no_outgoing_transitions():
    for (_, source) in TRANSITIONS:
        assert not source.is_final


def test_invariants_after_success():
    job = new_job(("start", "complete"))
    assert job.status is JobStatus.DONE
    assert job.result is not None and job.error is None
    assert job.created_at < job.started_at < job.finished_at


def test_invariants_after_failure():
    job = new_job(("start", "fail"))
    assert job.status is JobStatus.ERROR
    assert job.error is not None and job.result is None
    assert job.finished_at is not None


def test_new_job_is_created_without_result_or_timestamps():
    job = new_job()
    assert job.status is JobStatus.CREATED
    assert (job.result, job.error, job.started_at, job.finished_at) == (None, None, None, None)


def test_params_are_copied_and_read_only():
    source = {"x": 1}
    job = new_job(params=source)
    source["x"] = 999  # the caller changes its dict later
    assert job.params["x"] == 1
    with pytest.raises(TypeError):
        job.params["x"] = 2  # type: ignore[index]


def test_result_is_read_only():
    job = new_job(("start", "complete"))
    with pytest.raises(TypeError):
        job.result["ok"] = False  # type: ignore[index]


def test_complete_with_invalid_result_changes_nothing():
    job = new_job(("start",))
    with pytest.raises(TypeError):
        job.complete("not a mapping", StepClock()())  # type: ignore[arg-type]
    assert job.status is JobStatus.RUNNING


def test_interrupt_records_job_interrupted():
    job = new_job(("start",))
    job.interrupt(StepClock()())
    assert job.status is JobStatus.ERROR
    assert job.error.code == codes.JOB_INTERRUPTED
    assert job.error.details == {"interrupted_in": "running"}
