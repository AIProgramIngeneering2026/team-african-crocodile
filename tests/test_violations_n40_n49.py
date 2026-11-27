"""Н40–Н49 from the CTF (tasks/p4_ctf/README.md), translated to OUR service (p4.md item 7).

JobShop sold orders and took payments; we run computations as Jobs. Each test names the violation, states
our version of it and plays the attack against the real HTTP app on SQLite. Not applicable items keep a test
too when there is something checkable behind the reason (e.g. "there is no such endpoint").
The table in the report (teams/african-crocodile/p4.md) links here.
"""

from __future__ import annotations

import uuid

import pytest

from api_client import C_TO_F, KM_TO_MI, TITLE
from jobservice import codes


# ---- Н40 Чужой Job ----------------------------------------------------------------------------------------
def test_n40_ids_are_unguessable_and_a_foreign_or_missing_id_reveals_nothing(api):
    """No ownership in v1 (ADR-0004): protection = random UUIDv4 ids, no listing, identical 404."""
    ids = [api.create("transform_text", TITLE).json["id"] for _ in range(3)]
    assert all(uuid.UUID(i).version == 4 for i in ids)  # not 1, 2, 3 … — cannot walk to a neighbour
    missing = api.get(str(uuid.uuid4())).json["error"]
    malformed = api.get("1").json["error"]
    assert (missing["code"], missing["message"]) == (malformed["code"], malformed["message"]) == (
        codes.JOB_NOT_FOUND, "Job not found."
    )
    assert api.request("GET", "/jobs").status == 405  # no "list all Jobs"


# ---- Н41 Сам себе статус -------------------------------------------------------------------------------
@pytest.mark.parametrize("method", ["PATCH", "PUT", "DELETE"])
def test_n41_there_is_no_way_to_write_status_or_result_from_outside(api, method):
    job_id = api.create("convert_unit", C_TO_F).json["id"]
    r = api.request(method, f"/jobs/{job_id}", json_body={"status": "done", "result": {"value": 1}})
    assert r.status == 405 and r.json["error"]["code"] == codes.METHOD_NOT_ALLOWED
    assert api.get(job_id).json["result"]["value"] == 77.0


def test_n41_status_or_result_in_the_create_body_is_refused(api, sql_repo):
    smuggled_top = {"operation": "convert_unit", "params": C_TO_F, "status": "done", "result": {"value": 1}}
    r = api.request("POST", "/jobs", json_body=smuggled_top, headers={"Idempotency-Key": "n41-a"})
    assert r.status == 400 and r.json["error"]["details"] == {"unknown_fields": ["result", "status"]}

    r = api.create("convert_unit", {**C_TO_F, "status": "done"}, key="n41-b")
    assert r.status == 422 and r.json["error"]["details"]["fields"][0]["code"] == codes.UNKNOWN_FIELD
    assert len(sql_repo) == 0  # transitions stay in domain/job.py; the database CHECKs are the second line


# ---- Н42 Пароль исполнителя -----------------------------------------------------------------------------
def test_n42_not_applicable_but_no_internal_secret_leaves_the_service(api):
    """We have no users, passwords or reset tokens (ADR-0004). The nearest thing to a secret we keep —
    the client's Idempotency-Key and the request hash — never appears in any response."""
    created = api.create("transform_text", TITLE, key="my-private-key")
    for r in (created, api.get(created.json["id"]), api.create("transform_text", TITLE, key="my-private-key")):
        assert b"my-private-key" not in r.raw and b"request_hash" not in r.raw and b"idempotency" not in r.raw


# ---- Н43 Весь каталог разом ------------------------------------------------------------------------------
def test_n43_no_bulk_read_and_no_huge_request(api):
    assert api.request("GET", "/jobs").status == 405
    assert api.request("GET", "/jobs?limit=100000").status == 405
    assert api.request("GET", "/jobs/").status == 404  # empty id is not "all ids"
    huge = api.create("transform_text", {**TITLE, "text": "a" * 70_000})
    assert huge.status == 413
    long_text = api.create("transform_text", {**TITLE, "text": "a " * 5_001})
    assert long_text.status == 422 and long_text.json["error"]["details"]["fields"][0]["code"] == codes.TEXT_TOO_LONG


# ---- Н44 Служебный возврат -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "method, path",
    [
        ("POST", "/admin/recover"),
        ("POST", "/jobs/recover"),
        ("POST", "/jobs/00000000-0000-4000-8000-000000000000/retry"),
        ("POST", "/jobs/00000000-0000-4000-8000-000000000000/cancel"),
        ("GET", "/v1/jobs/00000000-0000-4000-8000-000000000000"),  # no forgotten old version
        ("GET", "/debug"),
        ("GET", "/openapi.yaml"),
    ],
)
def test_n44_no_service_operation_is_reachable_over_http(api, method, path):
    """Restart recovery is a service operation; it runs only inside the process at startup, never by request."""
    r = api.request(method, path, json_body={})
    assert r.status in (404, 405) and r.json["error"]["code"] in (codes.ROUTE_NOT_FOUND, codes.METHOD_NOT_ALLOWED)


# ---- Н45 Минус товар ----------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "params, field, code",
    [
        ({**KM_TO_MI, "value": -5}, "params.value", codes.VALUE_MUST_BE_POSITIVE),   # negative length
        ({**KM_TO_MI, "value": 0}, "params.value", codes.VALUE_MUST_BE_POSITIVE),
        ({**C_TO_F, "precision": -1}, "params.precision", codes.INVALID_PRECISION),
        ({**C_TO_F, "precision": 9}, "params.precision", codes.INVALID_PRECISION),
        ({**C_TO_F, "uncertainty": -0.1}, "params.uncertainty", codes.NEGATIVE_UNCERTAINTY),
        ({**C_TO_F, "value": 1e13}, "params.value", codes.VALUE_OUT_OF_RANGE),
        ({**C_TO_F, "value": True}, "params.value", codes.FIELD_TYPE),               # bool is not a number
        ({**C_TO_F, "value": "25"}, "params.value", codes.FIELD_TYPE),
        ({**C_TO_F, "precision": 2.5}, "params.precision", codes.FIELD_TYPE),
    ],
)
def test_n45_values_the_contract_forbids_are_rejected_before_a_job_exists(api, sql_repo, params, field, code):
    r = api.create("convert_unit", params)
    assert r.status == 422
    assert {(f["field"], f["code"]) for f in r.json["error"]["details"]["fields"]} >= {(field, code)}
    assert len(sql_repo) == 0


# ---- Н46 Оплата без денег -----------------------------------------------------------------------------
def test_n46_a_job_is_never_done_without_its_result(api, sql_repo):
    """Our version: `status: done` while the result is not stored. The state, the result and the history
    are written in one transaction (tests/test_storage.py::test_state_change_is_rolled_back_...), and the
    database refuses such a row (tests/test_migrations.py::test_database_itself_refuses_...)."""
    for params in (C_TO_F, KM_TO_MI):
        job = api.get(api.create("convert_unit", params).json["id"]).json
        assert job["status"] == "done" and job["result"] is not None and job["finished_at"] is not None
        assert [h.to_status for h in sql_repo.history(job["id"])] == ["created", "running", "done"]


# ---- Н47 Двойной клик ----------------------------------------------------------------------------------
def test_n47_double_click_creates_one_job(api, sql_repo):
    first = api.create("convert_unit", C_TO_F, key="click")
    second = api.create("convert_unit", C_TO_F, key="click")
    assert (first.status, second.status) == (201, 200)
    assert second.header("Idempotent-Replayed") == "true" and second.json["id"] == first.json["id"]
    assert len(sql_repo) == 1
    # Without a key there is no "second Job by accident": the request is refused.
    assert api.create("convert_unit", C_TO_F, key=None).status == 400 and len(sql_repo) == 1


# ---- Н48 Двойное списание -----------------------------------------------------------------------------
def test_n48_repeating_the_request_does_not_run_the_work_again(api, sql_repo, counting_tools):
    """Our 'charge' = Tool.execute (in Practice 6 it is a paid OpenWeatherMap call). Lost response -> retry."""
    first = api.create("transform_text", TITLE, key="lost-response")
    for _ in range(3):
        assert api.create("transform_text", TITLE, key="lost-response").json == first.json
    assert counting_tools["transform_text"].execute_calls == 1
    assert len(sql_repo.history(first.json["id"])) == 3  # created, running, done — no extra transitions


# ---- Н49 Старый ключ, новое тело ---------------------------------------------------------------------
def test_n49_same_key_with_another_body_is_an_error(api, sql_repo, counting_tools):
    first = api.create("convert_unit", C_TO_F, key="reused")
    other = api.create("convert_unit", {**C_TO_F, "value": 30}, key="reused")
    assert other.status == 409 and other.json["error"]["code"] == codes.IDEMPOTENCY_KEY_REUSED
    assert other.json["error"]["details"] == {"existing_job_id": first.json["id"]}
    other_op = api.create("transform_text", TITLE, key="reused")
    assert other_op.status == 409
    assert len(sql_repo) == 1 and counting_tools["convert_unit"].execute_calls == 1


def test_n49_an_explicit_default_is_a_different_body(api):
    """ADR-0003 decision 2: the hash is over the body AS SENT, so adding `precision: 3` is a change."""
    base = {k: v for k, v in KM_TO_MI.items() if k != "precision"}
    api.create("convert_unit", base, key="defaults")
    assert api.create("convert_unit", {**base, "precision": 3}, key="defaults").status == 409


def test_n49_a_rejected_request_does_not_burn_the_key(api):
    """ADR-0003 decision 6: 4xx before a Job exists stores no key — the client may fix the body."""
    assert api.create("convert_unit", {**C_TO_F, "precision": 9}, key="fix-me").status == 422
    assert api.create("convert_unit", C_TO_F, key="fix-me").status == 201
