"""The code is checked against docs/api/openapi.yaml (p4.md item 1: "код проверяется по нему").

1. The routes in the code are exactly the operations in the contract.
2. Every error code the HTTP layer can produce is in `ErrorCode`, and its status is documented where it can occur.
3. Every example in the contract is valid against its own schema (the documentation does not lie to readers).
4. A small Schemathesis-style fuzz: random bodies never produce an undocumented status, a non-contract body
   or a 500 (lecture 104, "schemathesis для API" — the same idea without the extra dependency).
"""

from __future__ import annotations

import json
import random

import pytest

from api_client import C_TO_F, TITLE
from jobservice import codes
from jobservice.api import ROUTES, STATUS_BY_CODE
from openapi_contract import openapi


def test_routes_in_code_are_exactly_the_operations_in_openapi():
    assert {(r.method, r.template) for r in ROUTES} == openapi().operations()


def test_every_status_code_of_the_http_layer_maps_a_documented_error_code():
    error_codes = set(openapi().doc["components"]["schemas"]["ErrorCode"]["enum"])
    assert set(STATUS_BY_CODE) <= error_codes
    used = {v for k, v in vars(codes).items() if k.isupper()}
    assert used - error_codes - set(openapi().doc["components"]["schemas"]["FieldErrorCode"]["enum"]) == set()


@pytest.mark.parametrize(
    "code, method, template",
    [
        (codes.MALFORMED_REQUEST, "POST", "/jobs"),
        (codes.IDEMPOTENCY_KEY_REQUIRED, "POST", "/jobs"),
        (codes.IDEMPOTENCY_KEY_REUSED, "POST", "/jobs"),
        (codes.INVALID_JOB_TRANSITION, "POST", "/jobs"),
        (codes.PAYLOAD_TOO_LARGE, "POST", "/jobs"),
        (codes.UNSUPPORTED_MEDIA_TYPE, "POST", "/jobs"),
        (codes.UNKNOWN_OPERATION, "POST", "/jobs"),
        (codes.VALIDATION_ERROR, "POST", "/jobs"),
        (codes.INTERNAL_ERROR, "POST", "/jobs"),
        (codes.STORAGE_UNAVAILABLE, "POST", "/jobs"),
        (codes.JOB_NOT_FOUND, "GET", "/jobs/{job_id}"),
        (codes.INTERNAL_ERROR, "GET", "/jobs/{job_id}"),
        (codes.STORAGE_UNAVAILABLE, "GET", "/jobs/{job_id}"),
    ],
)
def test_status_of_each_error_is_documented_for_its_operation(code, method, template):
    assert STATUS_BY_CODE[code] in openapi().documented_statuses(method, template)


def _examples():
    """(where, schema $ref, value) for every example under a JSON media type in the contract."""
    found = []
    for path, item in openapi().doc["paths"].items():
        for method, op in item.items():
            holders = [("requestBody", op.get("requestBody", {}))]
            holders += [(f"responses/{s}", r) for s, r in op.get("responses", {}).items()]
            for where, holder in holders:
                media = holder.get("content", {}).get("application/json")
                if not media:
                    continue
                values = [media["example"]] if "example" in media else []
                values += [e["value"] for e in media.get("examples", {}).values()]
                for i, value in enumerate(values):
                    found.append((f"{method.upper()} {path} {where} #{i}", media["schema"]["$ref"], value))
    return found


EXAMPLES = _examples()


def test_the_contract_has_examples_to_check():
    assert len(EXAMPLES) >= 15


@pytest.mark.parametrize("where, ref, value", EXAMPLES, ids=[e[0] for e in EXAMPLES])
def test_every_example_in_openapi_matches_its_schema(where, ref, value):
    errors = list(openapi().validator(ref).iter_errors(value))
    assert not errors, f"{where}: {errors[0].message}"


def test_the_checker_rejects_a_body_that_drifted_from_the_contract(api):
    """Lecture 104: a test that only checks the status would not notice `id` renamed to `job_id`."""
    job = api.create("transform_text", TITLE).json
    drifted = {("job_id" if k == "id" else k): v for k, v in job.items()}
    with pytest.raises(AssertionError, match="required property"):
        openapi().check("GET", "/jobs/{job_id}", 200, {"X-Correlation-Id": "c"}, drifted)
    with pytest.raises(AssertionError, match="documented"):
        openapi().check("GET", "/jobs/{job_id}", 201, {"X-Correlation-Id": "c"}, job)
    with pytest.raises(AssertionError, match="Idempotent-Replayed"):
        openapi().check("POST", "/jobs", 200, {"X-Correlation-Id": "c", "Location": "/jobs/x"}, job)


# ---- fuzz --------------------------------------------------------------------------------------------
_ANY = [None, True, False, 0, -1, 1.5, -1e13, 1e300, "", " ", "C", "x" * 300, [], [1], {}, {"a": 1}]


def _random_params(rnd: random.Random) -> dict:
    base = dict(rnd.choice([C_TO_F, TITLE, {}]))
    for _ in range(rnd.randint(0, 4)):
        field = rnd.choice(list(base) + ["value", "precision", "text", "unknown", "from_unit"])
        if rnd.random() < 0.2:
            base.pop(field, None)
        else:
            base[field] = rnd.choice(_ANY)
    return base


def test_fuzz_random_requests_stay_inside_the_contract(api):
    rnd = random.Random(104)  # fixed seed: a failure is reproducible
    seen: set[int] = set()
    for i in range(300):
        operation = rnd.choice(["convert_unit", "transform_text", "get_weather", "", 7, None])
        params = _random_params(rnd) if rnd.random() < 0.9 else rnd.choice(_ANY)
        key = rnd.choice([f"fuzz-{i}", f"fuzz-{i % 5}", None])  # some keys repeat on purpose
        headers = {"Idempotency-Key": key} if key else {}
        r = api.request("POST", "/jobs", raw=json.dumps({"operation": operation, "params": params}).encode(),
                        headers=headers)  # ApiClient validates status, body and headers against openapi.yaml
        assert r.status < 500, r.json
        seen.add(r.status)
    assert {201, 400, 409, 422} <= seen  # the fuzz really reached the interesting answers
