"""HTTP API — a thin WSGI layer over the Dispatcher (Practice 4).

The contract is `docs/api/openapi.yaml` (contract-first). This module only:
  * routes the three documented operations (`ROUTES`, checked against openapi.yaml by tests);
  * applies the HTTP-only checks in the contract's order: media type (415), body size (413),
    Idempotency-Key (400), JSON shape (400) — everything after that is decided by the Dispatcher;
  * maps errors to status codes in ONE table (`STATUS_BY_CODE`) and ONE body format (`ErrorResponse`);
  * never returns a stack trace, a file path or SQL: unexpected failures are logged under the correlation id
    and answered with `500 INTERNAL_ERROR`.

Job rules stay in `domain.job`, the scenario stays in the Dispatcher. Plain WSGI from the standard library:
the service has no third-party runtime dependency (ADR-0006).
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from jobservice import codes
from jobservice.api.dto import error_body, job_to_dto
from jobservice.application.dispatcher import Dispatcher, check_idempotency_key
from jobservice.application.errors import ApplicationError, MalformedRequest
from jobservice.application.ports import JobStateConflict, StorageProbe, StorageUnavailable
from jobservice.domain.job import InvalidJobTransition

logger = logging.getLogger("jobservice.api")

MAX_BODY_BYTES = 64 * 1024  # card K7, openapi.yaml "Limits"
_CORRELATION_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_ENVELOPE_FIELDS = {"operation", "params"}

# One table for the whole service: error code -> HTTP status (lecture 104, "История: разные коды").
STATUS_BY_CODE: Mapping[str, int] = {
    codes.MALFORMED_REQUEST: 400,
    codes.IDEMPOTENCY_KEY_REQUIRED: 400,
    codes.JOB_NOT_FOUND: 404,
    codes.ROUTE_NOT_FOUND: 404,
    codes.METHOD_NOT_ALLOWED: 405,
    codes.IDEMPOTENCY_KEY_REUSED: 409,
    codes.INVALID_JOB_TRANSITION: 409,
    codes.PAYLOAD_TOO_LARGE: 413,
    codes.UNSUPPORTED_MEDIA_TYPE: 415,
    codes.UNKNOWN_OPERATION: 422,
    codes.VALIDATION_ERROR: 422,
    codes.INTERNAL_ERROR: 500,
    codes.STORAGE_UNAVAILABLE: 503,
}

_REASONS = {
    200: "OK", 201: "Created", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed",
    409: "Conflict", 413: "Payload Too Large", 415: "Unsupported Media Type", 422: "Unprocessable Entity",
    500: "Internal Server Error", 503: "Service Unavailable",
}


class HttpError(Exception):
    """An error found by the HTTP layer itself, before the Dispatcher is called."""

    def __init__(self, code: str, message: str, details: Mapping[str, Any] | None = None,
                 headers: Mapping[str, str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.headers = dict(headers or {})


@dataclass(frozen=True)
class Response:
    status: int
    body: Any
    headers: Mapping[str, str]


@dataclass(frozen=True)
class Route:
    method: str
    template: str  # as written in openapi.yaml, e.g. /jobs/{job_id}
    pattern: re.Pattern[str]
    handler_name: str


def _route(method: str, template: str, handler_name: str) -> Route:
    regex = "^" + re.sub(r"\{[a-z_]+\}", r"([^/]+)", template) + "$"
    return Route(method, template, re.compile(regex), handler_name)


ROUTES: tuple[Route, ...] = (
    _route("POST", "/jobs", "create_job"),
    _route("GET", "/jobs/{job_id}", "get_job"),
    _route("GET", "/health", "health"),
)


class JobServiceApp:
    """WSGI application. Create it with the composition root (`bootstrap.build_app`)."""

    def __init__(self, dispatcher: Dispatcher, storage: StorageProbe, *, version: str) -> None:
        self._dispatcher = dispatcher
        self._storage = storage
        self._version = version

    # ---- WSGI entry point -------------------------------------------------------------------------
    def __call__(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> Iterable[bytes]:
        started = time.monotonic()
        correlation_id = self._correlation_id(environ)
        method = environ.get("REQUEST_METHOD", "GET").upper()
        path = environ.get("PATH_INFO", "") or "/"
        try:
            response = self._dispatch(method, path, environ, correlation_id)
        except Exception as exc:  # noqa: BLE001 — every failure becomes the unified error body
            response = self._error_response(exc, correlation_id, method, path)

        payload = json.dumps(response.body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Content-Length": str(len(payload)),
            "X-Correlation-Id": correlation_id,
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            **response.headers,
        }
        start_response(f"{response.status} {_REASONS.get(response.status, '')}".strip(), list(headers.items()))
        logger.info(
            "%s %s -> %s",
            method,
            path,
            response.status,
            extra={"correlation_id": correlation_id, "status": response.status,
                   "duration_ms": round((time.monotonic() - started) * 1000, 1)},
        )
        return [payload]

    # ---- routing ----------------------------------------------------------------------------------
    def _dispatch(self, method: str, path: str, environ: dict[str, Any], correlation_id: str) -> Response:
        allowed: list[str] = []
        for route in ROUTES:
            match = route.pattern.match(path)
            if not match:
                continue
            if route.method == method:
                handler = getattr(self, route.handler_name)
                return handler(environ, correlation_id, *match.groups())
            allowed.append(route.method)
        if allowed:
            raise HttpError(
                codes.METHOD_NOT_ALLOWED,
                f"Method {method} is not allowed here.",
                {"allowed_methods": sorted(allowed)},
                headers={"Allow": ", ".join(sorted(allowed))},
            )
        raise HttpError(codes.ROUTE_NOT_FOUND, "No such endpoint. See docs/api/openapi.yaml.")

    # ---- POST /jobs -------------------------------------------------------------------------------
    def create_job(self, environ: dict[str, Any], correlation_id: str) -> Response:
        # Order of checks = openapi.yaml, POST /jobs description, steps 1–4.
        self._require_json(environ)
        raw = self._read_body(environ)
        check_idempotency_key(environ.get("HTTP_IDEMPOTENCY_KEY"))
        operation, params = self._parse_envelope(raw)

        outcome = self._dispatcher.submit(
            operation, params, idempotency_key=environ["HTTP_IDEMPOTENCY_KEY"], correlation_id=correlation_id
        )
        headers = {"Location": f"/jobs/{outcome.job.id}"}
        if outcome.replayed:
            headers["Idempotent-Replayed"] = "true"
            return Response(200, job_to_dto(outcome.job), headers)
        return Response(201, job_to_dto(outcome.job), headers)

    # ---- GET /jobs/{job_id} -----------------------------------------------------------------------
    def get_job(self, environ: dict[str, Any], correlation_id: str, job_id: str) -> Response:
        return Response(200, job_to_dto(self._dispatcher.get(job_id)), {})

    # ---- GET /health ------------------------------------------------------------------------------
    def health(self, environ: dict[str, Any], correlation_id: str) -> Response:
        try:
            self._storage.ping()
        except StorageUnavailable:
            body = {"status": "unavailable", "checks": {"database": "unavailable"}, "version": self._version}
            return Response(503, body, {})
        return Response(200, {"status": "ok", "checks": {"database": "ok"}, "version": self._version}, {})

    # ---- HTTP-only checks -------------------------------------------------------------------------
    @staticmethod
    def _require_json(environ: Mapping[str, Any]) -> None:
        media_type = str(environ.get("CONTENT_TYPE") or "").split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            raise HttpError(codes.UNSUPPORTED_MEDIA_TYPE, "Content-Type must be application/json.",
                            {"received": media_type or None})

    @staticmethod
    def _read_body(environ: Mapping[str, Any]) -> bytes:
        declared = str(environ.get("CONTENT_LENGTH") or "").strip()
        if not declared:
            length = 0
        elif not declared.isdigit():
            raise MalformedRequest("Content-Length must be a non-negative integer.")
        else:
            length = int(declared)
        if length > MAX_BODY_BYTES:  # refuse before reading anything (card K7)
            raise HttpError(codes.PAYLOAD_TOO_LARGE, f"Request body exceeds {MAX_BODY_BYTES} bytes.",
                            {"limit_bytes": MAX_BODY_BYTES})
        return environ["wsgi.input"].read(length) if length else b""

    @staticmethod
    def _parse_envelope(raw: bytes) -> tuple[Any, Any]:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MalformedRequest("Request body is not valid UTF-8.", {"position": exc.start}) from exc
        try:
            body = json.loads(text, object_pairs_hook=_no_duplicate_keys, parse_constant=_no_constants)
        except json.JSONDecodeError as exc:
            raise MalformedRequest("Request body is not valid JSON.", {"position": exc.pos}) from exc
        except _BadJson as exc:
            raise MalformedRequest(str(exc)) from exc
        except RecursionError as exc:  # "[[[[..." 30 000 levels deep still fits in 64 KiB
            raise MalformedRequest("Request body is nested too deeply.") from exc
        if not isinstance(body, dict):
            raise MalformedRequest("Request body must be a JSON object {operation, params}.")
        unknown = sorted(set(body) - _ENVELOPE_FIELDS)
        if unknown:
            raise MalformedRequest("Request body has fields other than operation and params.",
                                   {"unknown_fields": unknown[:20]})
        return body.get("operation"), body.get("params")

    # ---- errors -----------------------------------------------------------------------------------
    def _error_response(self, exc: Exception, correlation_id: str, method: str, path: str) -> Response:
        headers: dict[str, str] = {}
        if isinstance(exc, HttpError):
            code, message, details, headers = exc.code, exc.message, exc.details, exc.headers
        elif isinstance(exc, ApplicationError):
            code, message, details = exc.code, exc.message, exc.details
        elif isinstance(exc, (InvalidJobTransition, JobStateConflict)):
            logger.error("refused job transition: %s", exc, extra={"correlation_id": correlation_id})
            code, message, details = codes.INVALID_JOB_TRANSITION, "The Job cannot change to that state.", None
        elif isinstance(exc, StorageUnavailable):
            code = codes.STORAGE_UNAVAILABLE
            message = "Storage is not available. Retry later with the same Idempotency-Key."
            details = None
            headers = {"Retry-After": "1"}
        else:
            logger.exception("unexpected error in %s %s", method, path, extra={"correlation_id": correlation_id})
            code, message, details = (
                codes.INTERNAL_ERROR, "Unexpected error. Use the correlation id when reporting it.", None
            )
        status = STATUS_BY_CODE.get(code, 500)
        return Response(status, error_body(code, message, details, correlation_id), headers)

    @staticmethod
    def _correlation_id(environ: Mapping[str, Any]) -> str:
        supplied = environ.get("HTTP_X_CORRELATION_ID")
        if isinstance(supplied, str) and _CORRELATION_ID.match(supplied):
            return supplied
        return uuid.uuid4().hex[:12]  # invalid or missing -> our own; never echo arbitrary input to logs


class _BadJson(ValueError):
    pass


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:  # {"value": 1, "value": 2}: which one did the client mean? Refuse to guess.
            raise _BadJson(f"Duplicate field '{key[:50]}' in request body.")
        result[key] = value
    return result


def _no_constants(name: str) -> Any:
    raise _BadJson(f"'{name}' is not valid JSON.")
