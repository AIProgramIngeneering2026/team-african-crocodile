"""In-process client for the WSGI app: real HTTP semantics without sockets, plus the contract check.

Every call goes through `OpenApi.check`, so every API test is also a contract test.
`tests/test_api_server.py` additionally runs the same app behind a real socket.
"""

from __future__ import annotations

import io
import json
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from jobservice.api.app import ROUTES
from openapi_contract import openapi


@dataclass
class ApiResponse:
    status: int
    headers: dict[str, str]
    raw: bytes

    @property
    def json(self) -> Any:
        return json.loads(self.raw)

    def header(self, name: str) -> str | None:
        return {k.lower(): v for k, v in self.headers.items()}.get(name.lower())


def route_template(method: str, path: str) -> str | None:
    for route in ROUTES:
        if route.method == method and route.pattern.match(path):
            return route.template
    return None


class ApiClient:
    def __init__(self, app: Any, *, check_contract: bool = True) -> None:
        self.app = app
        self.check_contract = check_contract

    def request(self, method: str, path: str, *, json_body: Any = None, raw: bytes | None = None,
                headers: Mapping[str, str] | None = None, content_type: str | None = "application/json") -> ApiResponse:
        path, _, query = path.partition("?")  # like a real server: the query string is not part of PATH_INFO
        body = raw if raw is not None else (b"" if json_body is None else json.dumps(json_body).encode())
        environ: dict[str, Any] = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "SERVER_NAME": "test",
            "SERVER_PORT": "80",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "wsgi.input": io.BytesIO(body),
            "wsgi.url_scheme": "http",
            "CONTENT_LENGTH": str(len(body)) if body else "",
        }
        if content_type is not None:
            environ["CONTENT_TYPE"] = content_type
        for name, value in (headers or {}).items():
            key = name.upper().replace("-", "_")
            if key == "CONTENT_LENGTH":
                environ[key] = value
            else:
                environ["HTTP_" + key] = value
        captured: dict[str, Any] = {}

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            captured["status"] = int(status.split(" ", 1)[0])
            captured["headers"] = dict(response_headers)

        payload = b"".join(self.app(environ, start_response))
        response = ApiResponse(captured["status"], captured["headers"], payload)
        if self.check_contract:
            openapi().check(method, route_template(method, path), response.status, response.headers, response.json)
        return response

    # ---- shortcuts --------------------------------------------------------------------------------
    def create(self, operation: Any, params: Any, *, key: str | None = "auto", **kw: Any) -> ApiResponse:
        headers = dict(kw.pop("headers", {}) or {})
        if key is not None:
            headers["Idempotency-Key"] = uuid.uuid4().hex if key == "auto" else key
        return self.request("POST", "/jobs", json_body={"operation": operation, "params": params},
                            headers=headers, **kw)

    def get(self, job_id: str, **kw: Any) -> ApiResponse:
        return self.request("GET", f"/jobs/{job_id}", **kw)


# Request bodies used in many tests (scenarios from docs/requirements.md).
C_TO_F = {"value": 25, "from_unit": "C", "to_unit": "F", "precision": 2, "uncertainty": 0.1,
          "experiment_id": "EXP-2026-041"}
KM_TO_MI = {"value": 12.345, "from_unit": "km", "to_unit": "mi", "precision": 3, "engineer_id": "ENG-007"}
M_TO_KG = {"value": 12.5, "from_unit": "m", "to_unit": "kg", "engineer_id": "ENG-007"}
TITLE = {"text": "the quick brown fox jumps over the lazy dog", "author_id": "AUTH-12", "document_id": "DOC-345"}
