"""The same app behind a real socket: what a curl / Postman user gets (README "Запуск сервиса")."""

from __future__ import annotations

import http.client
import json
import threading

import pytest

from api_client import TITLE
from jobservice.bootstrap import build_app
from jobservice.server import make_http_server
from openapi_contract import openapi


@pytest.fixture
def server(db_path):
    httpd = make_http_server(build_app(db_path), "127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_port
    httpd.shutdown()
    httpd.server_close()


def call(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request(method, path, body=body, headers=headers or {})
    resp = conn.getresponse()
    payload = resp.read()
    conn.close()
    return resp.status, dict(resp.getheaders()), json.loads(payload)


def test_create_and_read_over_a_real_socket(server):
    body = json.dumps({"operation": "transform_text", "params": TITLE})
    status, headers, job = call(server, "POST", "/jobs", body,
                                {"Content-Type": "application/json", "Idempotency-Key": "socket-1"})
    assert status == 201
    openapi().check("POST", "/jobs", status, headers, job)
    status, headers, again = call(server, "GET", headers["Location"])
    assert status == 200 and again == job
    openapi().check("GET", "/jobs/{job_id}", status, headers, again)


def test_server_header_does_not_reveal_the_python_version(server):
    _, headers, _ = call(server, "GET", "/health")
    assert headers["Server"] == "jobservice"
