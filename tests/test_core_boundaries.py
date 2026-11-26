"""Checklist item 5: the core does not depend on a web framework or a database driver,
and the Dispatcher does not know any concrete Tool. Checked on the source code (imports), not by hand."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "jobservice"

FORBIDDEN_TOP_LEVEL = {
    # web frameworks / HTTP servers
    "fastapi", "starlette", "flask", "django", "aiohttp", "uvicorn",
    # database drivers / ORMs
    "sqlite3", "sqlalchemy", "psycopg", "psycopg2", "asyncpg", "pymysql", "mysql", "alembic",
    # HTTP clients (only the future OpenWeatherMap adapter may use one)
    "requests", "httpx", "urllib3",
}


def imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


DATABASE = {"sqlite3", "sqlalchemy", "psycopg", "psycopg2", "asyncpg", "pymysql", "mysql", "alembic"}

# The core: domain, application, tools and codes.py. Still no web framework and no database here.
CORE_FILES = sorted(
    p for layer in ("domain", "application", "tools") for p in (SRC / layer).rglob("*.py")
) + [SRC / "codes.py"]
ALL_FILES = sorted(SRC.rglob("*.py"))


@pytest.mark.parametrize("path", CORE_FILES, ids=lambda p: str(p.relative_to(SRC)))
def test_core_has_no_framework_or_database_imports(path):
    bad = {m for m in imports_of(path) if m.split(".")[0] in FORBIDDEN_TOP_LEVEL}
    assert not bad, f"{path.name} imports {bad}"


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: str(p.relative_to(SRC)))
def test_database_only_in_infrastructure(path):
    rel = path.relative_to(SRC)
    top = {m.split(".")[0] for m in imports_of(path)}
    if rel.parts[0] != "infrastructure":
        assert not (top & DATABASE), f"{rel} talks to the database: {top & DATABASE}"


def test_domain_imports_nothing_from_other_layers():
    for path in (SRC / "domain").rglob("*.py"):
        own = {m for m in imports_of(path) if m.startswith("jobservice")}
        assert own <= {"jobservice", "jobservice.domain", "jobservice.domain.job"}, (path.name, own)


@pytest.mark.parametrize("path", sorted((SRC / "application").rglob("*.py")), ids=lambda p: p.name)
def test_application_does_not_know_tools_or_infrastructure(path):
    own = {m for m in imports_of(path) if m.startswith("jobservice")}
    assert not any(m.startswith(("jobservice.tools", "jobservice.infrastructure", "jobservice.bootstrap")) for m in own)


def test_dispatcher_source_names_no_concrete_tool():
    text = (SRC / "application" / "dispatcher.py").read_text(encoding="utf-8")
    for concrete in ("UnitConverterTool", "TextTransformTool", "convert_unit", "transform_text", "get_weather"):
        assert concrete not in text
