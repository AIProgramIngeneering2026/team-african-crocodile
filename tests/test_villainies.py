"""Villainies Z1 – Z6 from the class exercise («Взлом Job»), applied to OUR Job.

Mapping of the game commands to our core:
    create  -> Dispatcher.submit / Job(...)          start   -> Job.start
    finish  -> Job.complete                          fail    -> Job.fail
    restart -> process stops + Dispatcher.recover_interrupted -> Job.interrupt
    cancel, retry, rerun, delete -> do not exist in our service (ADR-0002, ADR-0003)

Each test first plays the attacking chain on the Job itself, then (where it makes sense) through
the Dispatcher, because a Job rule that the Dispatcher could go around would not protect anything.
"""

from __future__ import annotations

import pytest

from helpers import FakeTool, StepClock, crashing, new_job
from jobservice import codes
from jobservice.application import Dispatcher, Registry, ToolResult
from jobservice.domain import TRANSITIONS, InvalidJobTransition, JobCommand, JobError, JobStatus


class ProcessStopped(BaseException):
    """Simulates the process dying in the middle of Tool.execute (not an Exception: nobody catches it)."""


# ---- Z1 Двойная работа: two Tools working on one Job at the same time ------------------------------
def test_z1_second_start_is_rejected():
    """create, start, start -> отказ: one Job never gets a second running Tool."""
    job = new_job(("start",))
    with pytest.raises(InvalidJobTransition):
        job.start(StepClock()())
    assert job.status is JobStatus.RUNNING


def test_z1_double_click_runs_the_tool_once(dispatcher, fake_tool):
    """Same request twice (same Idempotency-Key): the second one does not start a Tool."""
    first = dispatcher.submit("fake", {"x": 1}, idempotency_key="k1")
    second = dispatcher.submit("fake", {"x": 1}, idempotency_key="k1")
    assert fake_tool.execute_calls == 1
    assert second.replayed and second.job.id == first.job.id


def test_z1_repeat_while_first_is_still_running_does_not_start_another_tool(repo, clock):
    """The first request is still `running` when the repeat arrives: the repeat only reads the Job."""
    seen_by_repeat = {}

    def run_and_repeat(params):
        # While the first Tool is working, the client repeats the request.
        seen_by_repeat["outcome"] = dispatcher.submit("fake", {"x": 1}, idempotency_key="k1")
        return ToolResult.success({"done": True})

    tool = FakeTool(behaviour=run_and_repeat)
    reg = Registry()
    reg.register(tool)
    dispatcher = Dispatcher(reg, repo, clock=clock)

    dispatcher.submit("fake", {"x": 1}, idempotency_key="k1")
    repeat = seen_by_repeat["outcome"]
    assert tool.execute_calls == 1
    assert repeat.replayed and repeat.job.status is JobStatus.RUNNING


# ---- Z2 Вечная работа: restart, and the Job stays `running` forever -------------------------------
def test_z2_restart_moves_running_job_to_error(repo, clock):
    """create, start, restart -> error (JOB_INTERRUPTED), not `running` forever."""
    tool = FakeTool(behaviour=crashing(ProcessStopped()))
    reg = Registry()
    reg.register(tool)
    old_process = Dispatcher(reg, repo, clock=clock)

    with pytest.raises(ProcessStopped):
        old_process.submit("fake", {"x": 1}, idempotency_key="k1")
    (stuck,) = repo.find_unfinished()
    assert stuck.status is JobStatus.RUNNING  # this is exactly the villainy before recovery

    new_process = Dispatcher(reg, repo, clock=clock)  # same storage, new process
    assert new_process.recover_interrupted() == [stuck.id]

    job = new_process.get(stuck.id)
    assert job.status is JobStatus.ERROR
    assert job.error.code == codes.JOB_INTERRUPTED
    assert repo.find_unfinished() == []


def test_z2_restart_also_closes_a_created_job():
    job = new_job()
    job.interrupt(StepClock()())
    assert job.status is JobStatus.ERROR


def test_z2_after_restart_the_repeat_returns_the_interrupted_job(repo, clock):
    """The client repeats with the same key after the restart: it sees the error, the Tool does not run."""
    tool = FakeTool(behaviour=crashing(ProcessStopped()))
    reg = Registry()
    reg.register(tool)
    with pytest.raises(ProcessStopped):
        Dispatcher(reg, repo, clock=clock).submit("fake", {"x": 1}, idempotency_key="k1")

    new_process = Dispatcher(reg, repo, clock=clock)
    new_process.recover_interrupted()
    repeat = new_process.submit("fake", {"x": 1}, idempotency_key="k1")
    assert repeat.replayed and repeat.job.error.code == codes.JOB_INTERRUPTED
    assert tool.execute_calls == 1


# ---- Z3 Отменённое стало готовым ---------------------------------------------------------------------
def test_z3_not_applicable_there_is_no_cancel_or_delete():
    """Z3 needs cancel/delete. Our Job has neither (ADR-0002): no such command exists at all."""
    assert {c.value for c in JobCommand} == {"start", "complete", "fail", "interrupt"}
    assert not any(c.value in {"cancel", "delete"} for (c, _) in TRANSITIONS)


# ---- Z4 Два итога: error, then done without a new client command ----------------------------------
def test_z4_late_success_after_error_is_rejected():
    """create, start, fail, finish -> отказ: error stays error."""
    job = new_job(("start", "fail"))
    with pytest.raises(InvalidJobTransition):
        job.complete({"late": True}, StepClock()())
    assert job.status is JobStatus.ERROR and job.result is None


def test_z4_late_success_after_restart_is_rejected():
    """create, start, restart, finish -> отказ: the old Tool's late answer cannot revive the Job."""
    job = new_job(("start", "interrupt"))
    with pytest.raises(InvalidJobTransition):
        job.complete({"late": True}, StepClock()())
    assert job.status is JobStatus.ERROR and job.error.code == codes.JOB_INTERRUPTED


def test_z4_second_failure_does_not_overwrite_the_first():
    job = new_job(("start", "fail"))
    first_error = job.error
    with pytest.raises(InvalidJobTransition):
        job.interrupt(StepClock()())
    assert job.error is first_error


def test_z4_done_cannot_become_error():
    job = new_job(("start", "complete"))
    with pytest.raises(InvalidJobTransition):
        job.fail(JobError("X", "x"), StepClock()())
    assert job.status is JobStatus.DONE


# ---- Z5 Успех без работы: done without ever being `running` -----------------------------------------
def test_z5_finish_from_created_is_rejected():
    """create, finish -> отказ."""
    job = new_job()
    with pytest.raises(InvalidJobTransition):
        job.complete({"ok": True}, StepClock()())
    assert job.status is JobStatus.CREATED and job.result is None


def test_z5_every_done_job_has_been_running(dispatcher):
    outcome = dispatcher.submit("fake", {"x": 1}, idempotency_key="k1")
    job = outcome.job
    assert job.status is JobStatus.DONE
    assert job.started_at is not None and job.started_at < job.finished_at


# ---- Z6 Повтор успешного: a done Job goes to work again ----------------------------------------------
def test_z6_start_after_done_is_rejected():
    """create, start, finish, start -> отказ."""
    job = new_job(("start", "complete"))
    with pytest.raises(InvalidJobTransition):
        job.start(StepClock()())
    assert job.status is JobStatus.DONE


def test_z6_repeating_a_done_request_does_not_run_the_tool_again(dispatcher, fake_tool):
    first = dispatcher.submit("fake", {"x": 1}, idempotency_key="k1")
    for _ in range(3):
        again = dispatcher.submit("fake", {"x": 1}, idempotency_key="k1")
        assert again.replayed and again.job.id == first.job.id and again.job.status is JobStatus.DONE
    assert fake_tool.execute_calls == 1


def test_z6_running_again_on_purpose_creates_a_new_job_and_keeps_the_old_one(dispatcher, fake_tool):
    first = dispatcher.submit("fake", {"x": 1}, idempotency_key="k1")
    second = dispatcher.submit("fake", {"x": 1}, idempotency_key="k2")
    assert second.job.id != first.job.id and not second.replayed
    assert dispatcher.get(first.job.id).finished_at == first.job.finished_at  # old Job untouched
    assert fake_tool.execute_calls == 2
