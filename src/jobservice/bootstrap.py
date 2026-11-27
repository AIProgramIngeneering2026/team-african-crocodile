"""Composition root: the only module that knows every concrete class.

Adding a Tool = write the class + one `registry.register(...)` line here. The Dispatcher does not change.
`get_weather` will be registered in Practice 6 together with OpenWeatherMapAdapter.

Practice 4: the service runs on `SqliteJobRepository` (`build_app`); `InMemoryJobRepository` stays for unit tests
(ADR-0005, ADR-0006). The schema is created only by migrations: `build_app` checks that the database is current
and refuses to start otherwise — it never creates tables itself.
"""

from __future__ import annotations

from pathlib import Path

from jobservice import __version__
from jobservice.api.app import JobServiceApp
from jobservice.application.dispatcher import Clock, Dispatcher
from jobservice.application.ports import JobRepository
from jobservice.application.registry import Registry
from jobservice.infrastructure.memory_job_repository import InMemoryJobRepository
from jobservice.infrastructure.migrator import assert_current
from jobservice.infrastructure.sqlite_job_repository import SqliteJobRepository
from jobservice.tools.text_transform import TextTransformTool
from jobservice.tools.unit_converter import UnitConverterTool


def build_registry() -> Registry:
    registry = Registry()
    registry.register(UnitConverterTool())
    registry.register(TextTransformTool())
    return registry


def build_dispatcher(jobs: JobRepository | None = None, *, clock: Clock | None = None) -> Dispatcher:
    dispatcher = Dispatcher(build_registry(), jobs if jobs is not None else InMemoryJobRepository(), clock=clock)
    dispatcher.recover_interrupted()  # before accepting any request (ADR-0002, decision 3)
    return dispatcher


def build_app(db_path: str | Path, *, clock: Clock | None = None) -> JobServiceApp:
    """The production wiring: migrated SQLite database -> repository -> Dispatcher -> HTTP API."""
    assert_current(db_path)  # raises SchemaNotCurrent: run `python -m jobservice migrate`
    repository = SqliteJobRepository(db_path)
    dispatcher = build_dispatcher(repository, clock=clock)
    return JobServiceApp(dispatcher, repository, version=__version__)
