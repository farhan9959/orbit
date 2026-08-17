"""Structured logging, correlation ids, and Prometheus metrics.

Assumptions and failure modes:
* The JSON formatter is ~25 lines, which is why structlog was rejected.
* Correlation ids propagate through `contextvars`, so they survive `await`.
* Passwords, cookies, CSRF tokens and Authorization headers are never logged. The redaction
  filter enforces it and a test posts a password then greps the captured stream for it —
  a filter without that test is an assumption, not a control.
* `/healthz` deliberately checks nothing but the process. `/readyz` checks the database.
  A health endpoint that touches the DB takes the whole service down when the DB blips.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from fastapi import Request, Response
from prometheus_client import Counter, Gauge, Histogram

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
user_id_var: ContextVar[str] = ContextVar("user_id", default="-")

REDACTED = "[redacted]"
SENSITIVE_KEYS = ("password", "secret", "token", "cookie", "authorization", "csrf")

http_requests = Counter("http_requests_total", "HTTP requests", ["route", "method", "status"])
http_duration = Histogram(
    "http_request_duration_seconds", "HTTP request duration", ["route", "method"]
)
active_runs = Gauge("orbit_active_runs", "Experiment runs currently executing")
run_duration = Histogram("orbit_run_duration_seconds", "Run duration", ["algorithm"])
control_seconds = Histogram(
    "orbit_control_computation_seconds", "Control-plane computation", ["algorithm"]
)
reroutes_total = Counter("orbit_reroutes_total", "Flow reroutes", ["algorithm"])
preemptions_total = Counter("orbit_preemptions_total", "Flow preemptions")


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": _redact(record.getMessage()),
            "request_id": request_id_var.get(),
            "user_id": user_id_var.get(),
        }
        for key, value in getattr(record, "extra_fields", {}).items():
            payload[key] = REDACTED if _is_sensitive(key) else value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in SENSITIVE_KEYS)


def _redact(message: str) -> str:
    lowered = message.lower()
    if any(marker in lowered for marker in SENSITIVE_KEYS):
        return REDACTED
    return message


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())


async def correlation_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    token = request_id_var.set(request_id)
    route = request.scope.get("route")
    label = getattr(route, "path", request.url.path)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        elapsed = time.perf_counter() - started
        http_duration.labels(route=label, method=request.method).observe(elapsed)
        request_id_var.reset(token)
    http_requests.labels(route=label, method=request.method, status=str(response.status_code)).inc()
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'"
    return response
