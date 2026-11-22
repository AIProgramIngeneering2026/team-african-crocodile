"""transform_text — requirements scenario 4."""

from __future__ import annotations

import pytest

from jobservice import codes
from jobservice.application import ParamsInvalid, ToolContext
from jobservice.domain import JobStatus
from jobservice.tools import TextTransformTool
from jobservice.tools.text_transform import MAX_TEXT_LENGTH, title_basic_v1

IDS = {"author_id": "AUTH-12", "document_id": "DOC-345"}


def field_codes(exc: ParamsInvalid) -> dict[str, str]:
    return {e.field: e.code for e in exc.errors}


def test_scenario_4_title_case(real_dispatcher):
    job = real_dispatcher.submit(
        "transform_text",
        {"text": "the quick brown fox jumps over the lazy dog", "profile": "title-basic-v1", **IDS},
        idempotency_key="s4",
    ).job
    assert job.status is JobStatus.DONE
    r = job.result
    assert r["text"] == "The Quick Brown Fox Jumps Over The Lazy Dog"
    assert (r["profile"], r["profile_version"]) == ("title-basic-v1", "1")
    assert (r["author_id"], r["document_id"]) == ("AUTH-12", "DOC-345")
    assert r["transformed_at"].startswith("2026-11-22T")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("HELLO wORLD", "Hello World"),
        ("o'neill", "O'neill"),  # not str.title(): that would give O'Neill
        ("  two\tspaces\n", "  Two\tSpaces\n"),  # whitespace kept exactly
        ("(quoted) 3rd", "(Quoted) 3Rd"),  # first LETTER of the token
        ("123 456", "123 456"),
        ("über straße", "Über Straße"),
    ],
)
def test_title_basic_v1_rules(text, expected):
    assert title_basic_v1(text) == expected


def test_profile_defaults_to_title_basic_v1():
    assert TextTransformTool().validate({"text": "a", **IDS})["profile"] == "title-basic-v1"


@pytest.mark.parametrize(
    ("params", "field", "code"),
    [
        ({"text": ""}, "params.text", codes.TEXT_EMPTY),
        ({"text": "   \n"}, "params.text", codes.TEXT_EMPTY),
        ({"text": "a" * (MAX_TEXT_LENGTH + 1)}, "params.text", codes.TEXT_TOO_LONG),
        ({"text": "bad\x00char"}, "params.text", codes.UNSUPPORTED_CHARACTERS),
        ({"text": 42}, "params.text", codes.FIELD_TYPE),
        ({"profile": "title-fancy-v9"}, "params.profile", codes.PROFILE_NOT_FOUND),
        ({"author_id": None}, "params.author_id", codes.FIELD_REQUIRED),
        ({"document_id": ""}, "params.document_id", codes.FIELD_REQUIRED),
        ({"extra": 1}, "params.extra", codes.UNKNOWN_FIELD),
    ],
)
def test_wrong_field(params, field, code):
    with pytest.raises(ParamsInvalid) as info:
        TextTransformTool().validate({"text": "ok", **IDS, **params})
    assert field_codes(info.value) == {field: code}


def test_text_at_the_limit_is_accepted():
    TextTransformTool().validate({"text": "a" * MAX_TEXT_LENGTH, **IDS})


def test_missing_text_and_ids_are_all_reported():
    with pytest.raises(ParamsInvalid) as info:
        TextTransformTool().validate({})
    assert field_codes(info.value) == {
        "params.text": codes.FIELD_REQUIRED,
        "params.author_id": codes.FIELD_REQUIRED,
        "params.document_id": codes.FIELD_REQUIRED,
    }


def test_unsupported_character_positions_are_reported():
    with pytest.raises(ParamsInvalid) as info:
        TextTransformTool().validate({"text": "ab\x07c\x1b", **IDS})
    assert info.value.errors[0].rejected_value == [2, 4]
