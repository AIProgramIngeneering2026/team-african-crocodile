"""Composition root: the real Tools are registered and startup recovery runs before any request."""

from __future__ import annotations

from helpers import new_job
from jobservice import codes
from jobservice.bootstrap import build_dispatcher, build_registry
from jobservice.domain import JobStatus
from jobservice.infrastructure import InMemoryJobRepository


def test_production_registry_has_the_two_tools():
    assert build_registry().names() == ["convert_unit", "transform_text"]


def test_bootstrap_recovers_unfinished_jobs():
    repo = InMemoryJobRepository()
    running, created, done = new_job(("start",)), new_job(), new_job(("start", "complete"))
    for job in (running, created, done):
        repo.add(job)
    build_dispatcher(repo)
    assert repo.get(running.id).error.code == codes.JOB_INTERRUPTED
    assert repo.get(created.id).error.code == codes.JOB_INTERRUPTED
    assert repo.get(done.id).status is JobStatus.DONE


def test_bootstrap_runs_a_real_job_end_to_end():
    d = build_dispatcher()
    job = d.submit("transform_text", {"text": "hello world", "author_id": "A", "document_id": "D"},
                   idempotency_key="e2e").job
    assert job.status is JobStatus.DONE and job.result["text"] == "Hello World"
