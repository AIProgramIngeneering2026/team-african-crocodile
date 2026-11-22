"""The code speaks the same language as docs/api/openapi.yaml (error codes and Job statuses)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from jobservice import codes
from jobservice.domain import JobStatus

OPENAPI = Path(__file__).resolve().parents[1] / "docs" / "api" / "openapi.yaml"


@pytest.fixture(scope="module")
def openapi_text() -> str:
    if not OPENAPI.exists():
        pytest.skip("docs/api/openapi.yaml not found")
    return OPENAPI.read_text(encoding="utf-8")


def enum_values(text: str, schema: str) -> set[str]:
    """Values listed as `- NAME` lines directly under `<schema>:` ... `enum:`."""
    block = text.split(f"\n    {schema}:\n", 1)[1]
    enum = block.split("enum:", 1)[1]
    values = []
    for line in enum.splitlines()[1:]:
        m = re.match(r"^\s+- ([A-Z_]+)\s*$", line)
        if not m:
            break
        values.append(m.group(1))
    return set(values)


def test_every_code_in_the_core_is_in_openapi(openapi_text):
    documented = enum_values(openapi_text, "ErrorCode") | enum_values(openapi_text, "FieldErrorCode")
    used = {v for k, v in vars(codes).items() if k.isupper()}
    assert used - documented == set()


def test_job_statuses_match_openapi(openapi_text):
    m = re.search(r"JobStatus:\n\s+type: string\n\s+enum: \[([^\]]+)\]", openapi_text)
    assert m is not None
    assert {s.strip() for s in m.group(1).split(",")} == {s.value for s in JobStatus}
