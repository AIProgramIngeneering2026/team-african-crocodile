from __future__ import annotations

import pytest

from helpers import FakeTool
from jobservice.application import DuplicateTool, Registry


def test_returns_tool_by_operation_name():
    reg = Registry()
    tool = FakeTool("fake")
    reg.register(tool)
    assert reg.get("fake") is tool


@pytest.mark.parametrize("name", ["missing", "", "FAKE", None, 42])
def test_unknown_name_gives_none(name):
    reg = Registry()
    reg.register(FakeTool("fake"))
    assert reg.get(name) is None


def test_duplicate_name_is_rejected_at_startup():
    reg = Registry()
    reg.register(FakeTool("fake"))
    with pytest.raises(DuplicateTool):
        reg.register(FakeTool("fake"))


class NoExecute:
    name = "broken"
    version = "broken/1"

    def validate(self, params):
        return params


class NoName:
    name = " "
    version = "x/1"

    def validate(self, params):
        return params

    def execute(self, params, ctx):
        return None


@pytest.mark.parametrize("tool", [NoExecute(), NoName()])
def test_object_that_breaks_the_contract_is_rejected_at_startup(tool):
    with pytest.raises(ValueError):
        Registry().register(tool)


def test_names_are_sorted():
    reg = Registry()
    for name in ("zeta", "alpha"):
        reg.register(FakeTool(name))
    assert reg.names() == ["alpha", "zeta"]

