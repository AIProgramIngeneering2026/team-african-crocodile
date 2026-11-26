"""Storage (p4.md items 2, 4, 5).

* Repository contract — the same behaviour from InMemoryJobRepository and SqliteJobRepository (`repo` runs both).
* One transaction — a Job's state and its history record are written together or not at all.
* Restart — Jobs, results and idempotency keys live in the database, not in the process.
* A real race of threads with one Idempotency-Key on SQLite — one Job, the Tool runs once.
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from pathlib import Path

import pytest

from api_client import TITLE, ApiClient
from helpers import raw_db, CountingTool, FakeTool, StepClock, new_job
from jobservice import __version__, codes
from jobservice.api import JobServiceApp
from jobservice.application import Dispatcher, Registry, ToolResult
from jobservice.application.ports import DuplicateIdempotencyKey, JobStateConflict, StorageUnavailable
from jobservice.bootstrap import build_app
from jobservice.domain import JobStatus
from jobservice.infrastructure import SqliteJobRepository
from jobservice.tools import TextTransformTool


# ---- Repository contract (both implementations) --------------------------------------------------------
def snapshot(job):
    return (job.id, job.operation, dict(job.params), job.idempotency_key, job.request_hash, job.tool_version,
            job.correlation_id, job.status, None if job.result is None else dict(job.result),
            job.error, job.created_at, job.started_at, job.finished_at)


@pytest.mark.parametrize("path", [(), ("start",), ("start", "complete"), ("start", "fail"), ("interrupt",)])
def test_round_trip_keeps_every_field(repo, path):
    job = new_job(path, params={"x": 1, "nested": {"y": [1, 2]}, "text": "Ünïcødé"})
    repo.add(job)
    assert snapshot(repo.get(job.id)) == snapshot(job)
    assert snapshot(repo.find_by_key(job.idempotency_key)) == snapshot(job)


def test_stored_job_is_a_copy(repo):
    job = new_job()
    repo.add(job)
    job.start(StepClock()())
    assert repo.get(job.id).status is JobStatus.CREATED  # not saved yet -> not stored


def test_unique_idempotency_key(repo):
    first = new_job(idempotency_key="same")
    repo.add(first)
    with pytest.raises(DuplicateIdempotencyKey) as info:
        repo.add(new_job(idempotency_key="same"))
    assert info.value.existing_job_id == first.id and len(repo) == 1


def test_unknown_lookups_and_saving_an_unknown_job(repo):
    assert repo.get("nope") is None and repo.find_by_key("nope") is None
    with pytest.raises(LookupError):
        repo.save(new_job())


def test_history_records_every_transition(repo):
    clock = StepClock()
    job = new_job()
    repo.add(job)
    job.start(clock())
    repo.save(job)
    repo.save(job)  # saving without a change of status writes no history
    job.complete({"ok": True}, clock())
    repo.save(job)
    assert [(h.from_status, h.to_status) for h in repo.history(job.id)] == [
        (None, "created"), ("created", "running"), ("running", "done")
    ]


def test_a_final_job_cannot_be_overwritten_by_a_stale_copy(repo):
    """Lost update: two copies of one running Job; one finishes it, the other tries to fail it."""
    clock = StepClock()
    job = new_job(("start",))
    repo.add(job)
    copy_a, copy_b = repo.get(job.id), repo.get(job.id)
    copy_a.complete({"ok": True}, clock())
    repo.save(copy_a)
    copy_b.interrupt(clock())
    with pytest.raises(JobStateConflict):
        repo.save(copy_b)
    stored = repo.get(job.id)
    assert stored.status is JobStatus.DONE and stored.result == {"ok": True}


def test_find_unfinished(repo):
    jobs = [new_job(), new_job(("start",)), new_job(("start", "complete")), new_job(("start", "fail"))]
    for j in jobs:
        repo.add(j)
    assert {j.id for j in repo.find_unfinished()} == {jobs[0].id, jobs[1].id}


# ---- One transaction: state + result + history ----------------------------------------------------------
def install_failing_history(db: Path, to_status: str) -> None:
    """The history INSERT fails (like a disk error between two INSERTs, lecture 104)."""
    with raw_db(db) as conn:
        conn.execute(
            f"CREATE TRIGGER fail_history BEFORE INSERT ON job_history WHEN NEW.to_status = '{to_status}' "
            "BEGIN SELECT RAISE(ABORT, 'history write failed'); END"
        )


def test_state_change_is_rolled_back_when_history_cannot_be_written(db_path, sql_repo):
    clock = StepClock()
    job = new_job(("start",))
    sql_repo.add(job)
    install_failing_history(db_path, "done")
    job.complete({"answer": 42}, clock())
    with pytest.raises(sqlite3.IntegrityError):
        sql_repo.save(job)
    stored = sql_repo.get(job.id)
    assert stored.status is JobStatus.RUNNING and stored.result is None and stored.finished_at is None
    assert [h.to_status for h in sql_repo.history(job.id)] == ["running"]  # add() wrote its own record


def test_job_creation_is_rolled_back_when_history_cannot_be_written(db_path, sql_repo):
    install_failing_history(db_path, "created")
    job = new_job()
    with pytest.raises(sqlite3.IntegrityError):
        sql_repo.add(job)
    assert sql_repo.get(job.id) is None and sql_repo.find_by_key(job.idempotency_key) is None


def test_through_the_api_a_failed_final_write_never_shows_done_without_history(db_path, sql_repo):
    """End to end: the final write fails -> 500 to the client, Job stays `running` (not half-`done`);
    the next start of the service closes it as JOB_INTERRUPTED (ADR-0002, decision 3)."""
    install_failing_history(db_path, "done")
    api = ApiClient(build_app(db_path))
    r = api.create("transform_text", TITLE, key="k-tx")
    assert r.status == 500 and r.json["error"]["code"] == codes.INTERNAL_ERROR
    (stuck,) = sql_repo.find_unfinished()
    assert stuck.status is JobStatus.RUNNING and stuck.result is None

    with raw_db(db_path) as conn:
        conn.execute("DROP TRIGGER fail_history")
    restarted = ApiClient(build_app(db_path))
    job = restarted.get(stuck.id).json
    assert job["status"] == "error" and job["error"]["code"] == codes.JOB_INTERRUPTED
    assert [h.to_status for h in sql_repo.history(stuck.id)] == ["created", "running", "error"]


# ---- Restart: everything lives in the database -----------------------------------------------------------
def test_job_result_and_key_survive_a_restart(db_path):
    first_process = ApiClient(build_app(db_path))
    created = first_process.create("transform_text", TITLE, key="survives").json

    second_process = ApiClient(build_app(db_path))  # new objects, same file: nothing kept in memory
    assert second_process.get(created["id"]).json == created
    replay = second_process.create("transform_text", TITLE, key="survives")
    assert replay.status == 200 and replay.json["id"] == created["id"]
    changed = second_process.create("transform_text", {**TITLE, "text": "other"}, key="survives")
    assert changed.status == 409 and changed.json["error"]["code"] == codes.IDEMPOTENCY_KEY_REUSED


def test_restart_closes_jobs_that_were_running(db_path, sql_repo):
    running = new_job(("start",), operation="transform_text", job_id=str(uuid.uuid4()))
    sql_repo.add(running)
    api = ApiClient(build_app(db_path))  # startup recovery runs before the first request
    job = api.get(running.id).json
    assert job["status"] == "error" and job["error"]["code"] == codes.JOB_INTERRUPTED
    assert job["error"]["details"] == {"interrupted_in": "running"}


# ---- Concurrency on a real database ----------------------------------------------------------------------
def test_parallel_requests_with_one_key_create_one_job_and_run_the_tool_once(db_path):
    """Card K1 / Н47 with real threads: they race between find_by_key and INSERT; UNIQUE decides."""
    gate = threading.Barrier(8)
    tool = CountingTool(TextTransformTool())
    reg = Registry()
    reg.register(tool)
    repo = SqliteJobRepository(db_path)
    app = ApiClient(JobServiceApp(Dispatcher(reg, repo), repo, version=__version__))
    results = []

    def client():
        gate.wait()
        results.append(app.create("transform_text", TITLE, key="same-click"))

    threads = [threading.Thread(target=client) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(r.status for r in results) == [200] * 7 + [201]
    assert len({r.json["id"] for r in results}) == 1
    assert len(repo) == 1 and tool.execute_calls == 1


def test_parallel_different_keys_all_succeed(db_path):
    repo = SqliteJobRepository(db_path)
    reg = Registry()
    reg.register(FakeTool(behaviour=lambda p: ToolResult.success({"ok": True})))
    dispatcher = Dispatcher(reg, repo)
    errors = []

    def work(i):
        try:
            dispatcher.submit("fake", {"i": i}, idempotency_key=f"k{i}")
        except Exception as exc:  # pragma: no cover - would be a locking bug
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [] and len(repo) == 20 and repo.find_unfinished() == []


def test_missing_database_file_is_storage_unavailable(tmp_path):
    repo = SqliteJobRepository(tmp_path / "missing.db")
    with pytest.raises(StorageUnavailable):
        repo.get("x")
    with pytest.raises(StorageUnavailable):
        repo.ping()
    assert not (tmp_path / "missing.db").exists()
