"""Composition root: the only module that knows every concrete class.

Adding a Tool = write the class + one `registry.register(...)` line here. The Dispatcher does not change.
`get_weather` will be registered in Practice 6 together with OpenWeatherMapAdapter.
"""

from __future__ import annotations

from jobservice.application.dispatcher import Clock, Dispatcher
from jobservice.application.ports import JobRepository
from jobservice.application.registry import Registry
from jobservice.infrastructure.memory_job_repository import InMemoryJobRepository
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
