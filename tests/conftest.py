"""Fixtures. Helper classes live in tests/helpers.py; the HTTP client in tests/api_client.py.

`repo` is parametrised: every test that uses it (Dispatcher, Tools, villainies) runs twice — against
InMemoryJobRepository and against SqliteJobRepository on a freshly migrated database (ADR-0005, decision 5).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from api_client import ApiClient
from helpers import CountingTool, FakeTool, StepClock
from jobservice import __version__
from jobservice.api import JobServiceApp
from jobservice.application import Dispatcher, Registry
from jobservice.infrastructure import InMemoryJobRepository, SqliteJobRepository
from jobservice.infrastructure.migrator import migrate
from jobservice.tools import TextTransformTool, UnitConverterTool


@pytest.fixture
def clock() -> StepClock:
    return StepClock()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """A database file after all migrations, as `python -m jobservice migrate` leaves it."""
    path = tmp_path / "jobs.db"
    migrate(path)
    return path


@pytest.fixture(params=["memory", "sqlite"])
def repo(request: pytest.FixtureRequest, tmp_path: Path):
    if request.param == "memory":
        return InMemoryJobRepository()
    path = tmp_path / "repo.db"
    migrate(path)
    return SqliteJobRepository(path)


@pytest.fixture
def fake_tool() -> FakeTool:
    return FakeTool()


@pytest.fixture
def registry(fake_tool: FakeTool) -> Registry:
    reg = Registry()
    reg.register(fake_tool)
    return reg


@pytest.fixture
def dispatcher(registry: Registry, repo, clock: StepClock) -> Dispatcher:
    return Dispatcher(registry, repo, clock=clock)


@pytest.fixture
def real_dispatcher(repo, clock: StepClock) -> Dispatcher:
    """Dispatcher with the two real Tools, as in bootstrap, with a deterministic experiment id."""
    reg = Registry()
    reg.register(UnitConverterTool(new_id=lambda: "generated"))
    reg.register(TextTransformTool(clock=clock))
    return Dispatcher(reg, repo, clock=clock)


# ---- HTTP API over SQLite ---------------------------------------------------------------------------
@pytest.fixture
def counting_tools() -> dict[str, CountingTool]:
    """The real Tools wrapped so that tests can see how many times `execute` ran."""
    return {
        "convert_unit": CountingTool(UnitConverterTool()),
        "transform_text": CountingTool(TextTransformTool()),
    }


@pytest.fixture
def sql_repo(db_path: Path) -> SqliteJobRepository:
    return SqliteJobRepository(db_path)


@pytest.fixture
def app(sql_repo: SqliteJobRepository, counting_tools: dict[str, CountingTool]) -> JobServiceApp:
    reg = Registry()
    for tool in counting_tools.values():
        reg.register(tool)
    dispatcher = Dispatcher(reg, sql_repo)
    dispatcher.recover_interrupted()
    return JobServiceApp(dispatcher, sql_repo, version=__version__)


@pytest.fixture
def api(app: JobServiceApp) -> ApiClient:
    return ApiClient(app)
