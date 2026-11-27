"""Running the service: a threaded WSGI server from the standard library + JSON logs.

Configuration comes from environment variables (README "Запуск сервиса"):
    JOBSERVICE_DB         path to the SQLite file          (default: var/jobservice.db)
    JOBSERVICE_HOST       interface to listen on            (default: 127.0.0.1)
    JOBSERVICE_PORT       port                              (default: 8000)
    JOBSERVICE_LOG_LEVEL  DEBUG / INFO / WARNING / ERROR    (default: INFO)
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from socketserver import ThreadingMixIn
from typing import Any
from wsgiref.simple_server import ServerHandler, WSGIRequestHandler, WSGIServer, make_server

_STANDARD_RECORD_FIELDS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


@dataclass(frozen=True)
class Settings:
    db_path: str = "var/jobservice.db"
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            db_path=os.environ.get("JOBSERVICE_DB", cls.db_path),
            host=os.environ.get("JOBSERVICE_HOST", cls.host),
            port=int(os.environ.get("JOBSERVICE_PORT", cls.port)),
            log_level=os.environ.get("JOBSERVICE_LOG_LEVEL", cls.log_level).upper(),
        )


class JsonFormatter(logging.Formatter):
    """One JSON object per line; `extra={...}` fields (correlation_id, job_id, status ...) are kept."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        entry.update({k: v for k, v in vars(record).items() if k not in _STANDARD_RECORD_FIELDS})
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)  # logs only, never the HTTP response
        return json.dumps(entry, ensure_ascii=False, default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


class _ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True  # a hanging client does not block shutdown


class _ServerHandler(ServerHandler):
    server_software = "jobservice"  # the stdlib default advertises "WSGIServer/0.2 CPython/3.x.y"


class _QuietHandler(WSGIRequestHandler):
    """Same as the stdlib handler, but: no Python version in `Server`, no plain-text access log."""

    server_version = "jobservice"
    sys_version = ""

    def handle(self) -> None:  # copy of WSGIRequestHandler.handle with our ServerHandler
        self.raw_requestline = self.rfile.readline(65537)
        if len(self.raw_requestline) > 65536:
            self.requestline = self.request_version = self.command = ""
            self.send_error(414)
            return
        if not self.parse_request():
            return
        handler = _ServerHandler(self.rfile, self.wfile, self.get_stderr(), self.get_environ(), multithread=True)
        handler.request_handler = self
        handler.run(self.server.get_app())

    def log_message(self, format: str, *args: Any) -> None:  # access log is written by the app as JSON
        pass


def make_http_server(app: Any, host: str, port: int) -> WSGIServer:
    return make_server(host, port, app, server_class=_ThreadingWSGIServer, handler_class=_QuietHandler)


def serve(settings: Settings) -> None:
    from jobservice.bootstrap import build_app  # imported here: `migrate` must work without building the app

    configure_logging(settings.log_level)
    log = logging.getLogger("jobservice.server")
    app = build_app(settings.db_path)  # checks migrations, runs restart recovery before the socket opens
    server = make_http_server(app, settings.host, settings.port)
    log.info("listening", extra={"host": settings.host, "port": server.server_port, "db": settings.db_path})
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("stopping")
    finally:
        server.server_close()
