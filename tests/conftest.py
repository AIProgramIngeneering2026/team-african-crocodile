"""Fixtures. Helper classes live in tests/helpers.py."""

from __future__ import annotations

import pytest

from helpers import FakeTool, StepClock
from jobservice.application import Dispatcher, Registry
from jobservice.infrastructure import InMemoryJobRepository


@pytest.fixture
def clock() -> StepClock:
    return StepClock()


@pytest.fixture
def repo() -> InMemoryJobRepository:
    return InMemoryJobRepository()


@pytest.fixture
def fake_tool() -> FakeTool:
    return FakeTool()


@pytest.fixture
def registry(fake_tool: FakeTool) -> Registry:
    reg = Registry()
    reg.register(fake_tool)
    return reg


@pytest.fixture
def dispatcher(registry: Registry, repo: InMemoryJobRepository, clock: StepClock) -> Dispatcher:
    return Dispatcher(registry, repo, clock=clock)


@pytest.fixture
def real_dispatcher(repo: InMemoryJobRepository, clock: StepClock) -> Dispatcher:
    """Dispatcher with the two real Tools, as in bootstrap, with a deterministic experiment id."""
    from jobservice.tools import TextTransformTool, UnitConverterTool  # only the Tool tests need them

    reg = Registry()
    reg.register(UnitConverterTool(new_id=lambda: "generated"))
    reg.register(TextTransformTool(clock=clock))
    return Dispatcher(reg, repo, clock=clock)
