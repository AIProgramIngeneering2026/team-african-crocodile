"""HTTP API: the normal path and the errors (p4.md item 6). Every response is also checked against openapi.yaml
by the client (tests/api_client.py), so these tests fail on a wrong body, not only on a wrong status."""

from __future__ import annotations

import pytest

from api_client import C_TO_F, KM_TO_MI, M_TO_KG, TITLE, ApiClient
from jobservice import codes
from jobservice.api import JobServiceApp
from jobservice.application import Dispatcher, Registry
from jobservice.application.ports import StorageUnavailable


# ---- Normal path: create Job -> read its state -> read its result -------------------------------------
def test_normal_path_create_then_get_state_and_result(api):
    created = api.create("convert_unit", C_TO_F, key="scenario-1")
    assert created.status == 201
    job = created.json
    assert created.header("Location") == f"/jobs/{job['id']}"
    assert job["status"] == "done" and job["error"] is None

    fetched = api.get(job["id"])
    assert fetched.status == 200
    assert fetched.json["status"] == "done"
    assert fetched.json["result"]["display"] == "77.00 ± 0.18 °F"
    assert fetched.json == job  # what we read later is exactly what was answered (stored, not recomputed)


@pytest.mark.parametrize(
    "operation, params, expected",
    [
        ("convert_unit", KM_TO_MI, {"value": 7.671, "unit": "mi"}),
        ("transform_text", TITLE, {"text": "The Quick Brown Fox Jumps Over The Lazy Dog"}),
    ],
)
def test_other_scenarios_through_http(api, operation, params, expected):
    job = api.create(operation, params).json
    assert job["status"] == "done"
    for key, value in expected.items():
        assert job["result"][key] == value


def test_domain_failure_is_201_with_job_error_and_kept(api):
    """Scenario 6: HTTP status describes the request, Job.status describes the work."""
    r = api.create("convert_unit", M_TO_KG)
    assert r.status == 201
    assert r.json["status"] == "error" and r.json["result"] is None
    assert r.json["error"]["code"] == codes.INCOMPATIBLE_DIMENSIONS
    assert api.get(r.json["id"]).json["error"]["code"] == codes.INCOMPATIBLE_DIMENSIONS


def test_internal_fields_are_never_returned(api):
    job = api.create("transform_text", TITLE, key="secret-key-123").json
    text = str(job)
    assert "idempotency_key" not in job and "request_hash" not in job
    assert "secret-key-123" not in text


# ---- Errors: one body format, the right status -------------------------------------------------------
def assert_error(response, status: int, code: str):
    assert response.status == status, response.json
    body = response.json
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details", "correlation_id"}
    assert body["error"]["code"] == code
    assert body["error"]["correlation_id"] == response.header("X-Correlation-Id")
    return body["error"]


def test_unknown_operation_422(api, sql_repo):
    err = assert_error(api.create("convert_currency", {"amount": 1}), 422, codes.UNKNOWN_OPERATION)
    assert err["details"] == {"operation": "convert_currency", "available_operations": ["convert_unit", "transform_text"]}
    assert len(sql_repo) == 0


def test_invalid_params_422_lists_every_wrong_field(api, sql_repo):
    err = assert_error(
        api.create("convert_unit", {"from_unit": "C", "to_unit": "F", "precision": 9, "colour": "red"}),
        422, codes.VALIDATION_ERROR,
    )
    fields = {(f["field"], f["code"]) for f in err["details"]["fields"]}
    assert fields == {
        ("params.value", codes.FIELD_REQUIRED),
        ("params.precision", codes.INVALID_PRECISION),
        ("params.colour", codes.UNKNOWN_FIELD),
    }
    assert len(sql_repo) == 0  # stage-1 errors create no Job


def test_job_not_found_404_same_for_unknown_and_malformed_id(api):
    a = assert_error(api.get("00000000-0000-4000-8000-000000000000"), 404, codes.JOB_NOT_FOUND)
    b = assert_error(api.get("abc' OR '1'='1"), 404, codes.JOB_NOT_FOUND)
    assert a["message"] == b["message"] and a["details"] is b["details"] is None


def test_missing_idempotency_key_400(api, sql_repo):
    assert_error(api.create("convert_unit", C_TO_F, key=None), 400, codes.IDEMPOTENCY_KEY_REQUIRED)
    assert_error(api.create("convert_unit", C_TO_F, key="has space"), 400, codes.IDEMPOTENCY_KEY_REQUIRED)
    assert_error(api.create("convert_unit", C_TO_F, key="x" * 129), 400, codes.IDEMPOTENCY_KEY_REQUIRED)
    assert len(sql_repo) == 0


@pytest.mark.parametrize(
    "raw, why",
    [
        (b"{not json", "invalid JSON"),
        (b"[1, 2]", "not an object"),
        (b'{"operation": "convert_unit"}', "params missing"),
        (b'{"operation": 5, "params": {}}', "operation not a string"),
        (b'{"operation": "convert_unit", "params": []}', "params not an object"),
        (b'{"operation": "convert_unit", "params": {}, "status": "done"}', "extra top-level field"),
        (b'{"operation": "convert_unit", "params": {"value": 1, "value": 2}}', "duplicate field"),
        (b'{"operation": "convert_unit", "params": {"value": NaN}}', "NaN"),
        (b"\xff\xfe", "not UTF-8"),
        (b"[" * 50_000, "nested too deeply"),
    ],
)
def test_malformed_body_400(api, sql_repo, raw, why):
    assert_error(api.request("POST", "/jobs", raw=raw, headers={"Idempotency-Key": "k"}), 400, codes.MALFORMED_REQUEST)
    assert len(sql_repo) == 0


def test_wrong_content_type_415(api):
    r = api.request("POST", "/jobs", raw=b"operation=convert_unit", headers={"Idempotency-Key": "k"},
                    content_type="application/x-www-form-urlencoded")
    assert_error(r, 415, codes.UNSUPPORTED_MEDIA_TYPE)


def test_body_over_64_kib_413_before_reading(api):
    big = b'{"operation":"transform_text","params":{"text":"' + b"a" * 70_000 + b'"}}'
    assert_error(api.request("POST", "/jobs", raw=big, headers={"Idempotency-Key": "k"}), 413, codes.PAYLOAD_TOO_LARGE)


def test_order_of_checks_follows_the_contract(api):
    """openapi.yaml POST /jobs: 415 before 413 before 400-key before 400-body."""
    big = b"x" * 70_000
    assert api.request("POST", "/jobs", raw=big, content_type="text/plain").status == 415
    assert api.request("POST", "/jobs", raw=big).status == 413
    r = api.request("POST", "/jobs", raw=b"{broken")
    assert r.json["error"]["code"] == codes.IDEMPOTENCY_KEY_REQUIRED


def test_unknown_route_404_and_wrong_method_405(api):
    assert_error(api.request("GET", "/nope"), 404, codes.ROUTE_NOT_FOUND)
    r = api.request("DELETE", "/jobs/123")
    assert_error(r, 405, codes.METHOD_NOT_ALLOWED)
    assert r.header("Allow") == "GET"


# ---- 5xx: no stack trace, no paths, no SQL ------------------------------------------------------------
class ExplodingDispatcher:
    def submit(self, *a, **kw):
        raise RuntimeError('sqlite3.OperationalError near "SELECT * FROM jobs" in /srv/app/secret.py line 42')

    def get(self, job_id):
        raise StorageUnavailable("disk I/O error at /var/lib/jobs.db")


class BrokenProbe:
    def ping(self):
        raise StorageUnavailable("gone")


def test_unexpected_failure_500_reveals_nothing(caplog):
    client = ApiClient(JobServiceApp(ExplodingDispatcher(), BrokenProbe(), version="t"))
    r = client.create("convert_unit", C_TO_F)
    err = assert_error(r, 500, codes.INTERNAL_ERROR)
    for leak in ("sqlite", "SELECT", "/srv", ".py", "Traceback", "line 42"):
        assert leak not in r.raw.decode()
    # ... the details go to the log only, under the same correlation id
    logged = [rec for rec in caplog.records if getattr(rec, "correlation_id", None) == err["correlation_id"]]
    assert any("secret.py" in rec.exc_text for rec in logged if rec.exc_text)


def test_storage_unavailable_503_with_retry_after():
    client = ApiClient(JobServiceApp(ExplodingDispatcher(), BrokenProbe(), version="t"))
    r = client.get("any")
    assert_error(r, 503, codes.STORAGE_UNAVAILABLE)
    assert r.header("Retry-After") == "1" and "/var/lib" not in r.raw.decode()
    health = client.request("GET", "/health")
    assert health.status == 503 and health.json["checks"]["database"] == "unavailable"


def test_database_file_deleted_gives_503_not_500(tmp_path, db_path, sql_repo):
    client = ApiClient(JobServiceApp(Dispatcher(Registry(), sql_repo), sql_repo, version="t"))
    assert client.request("GET", "/health").status == 200
    db_path.unlink()
    assert client.request("GET", "/health").status == 503
    assert_error(client.get("x"), 503, codes.STORAGE_UNAVAILABLE)
    assert not db_path.exists()  # the repository does not silently create an empty database


# ---- Correlation id -------------------------------------------------------------------------------------
def test_correlation_id_is_taken_from_the_request_and_stored_with_the_job(api):
    r = api.create("transform_text", TITLE, headers={"X-Correlation-Id": "req-42"})
    assert r.header("X-Correlation-Id") == "req-42" and r.json["correlation_id"] == "req-42"


def test_invalid_correlation_id_is_replaced(api):
    r = api.request("GET", "/health", headers={"X-Correlation-Id": "<script>"})
    assert r.header("X-Correlation-Id") != "<script>" and len(r.header("X-Correlation-Id")) == 12
