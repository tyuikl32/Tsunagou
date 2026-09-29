"""Opt-in SDK tracing of coordination boundaries; never a business dependency.

No HTTP auto-instrumentation, payloads, baggage, prompts or exception text are
recorded. Import the optional SDK only when explicitly configured.
"""

from __future__ import annotations

import importlib
import ipaddress
import logging
import re
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any
from urllib.parse import urlsplit

_incoming: ContextVar[str | None] = ContextVar("tsunagou_traceparent", default=None)
_active: ContextVar[Any] = ContextVar("tsunagou_telemetry", default=None)
_TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$")
_FIELDS = frozenset({"project_id", "actor_id", "agent_id", "command_id", "command_kind", "task_id",
                     "attempt_id", "message_id", "wake_attempt_id", "trigger_source", "outcome", "error_code"})


def valid_traceparent(value: str | None) -> str | None:
    match = _TRACEPARENT.fullmatch(value or "")
    return value if match and int(match[1], 16) and int(match[2], 16) else None


def safe_attributes(values: Mapping[str, Any]) -> dict[str, str]:
    return {f"tsunagou.{key}": value for key, value in values.items()
            if key in _FIELDS and isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9_:./-]{1,160}", value)}


class Telemetry:
    def __init__(self, endpoint: str | None = None) -> None:
        self.provider: Any = None
        self.trace: Any = None
        self.propagator: Any = None
        if not endpoint:
            return
        url = urlsplit(endpoint)
        try:
            local = ipaddress.ip_address(url.hostname or "").is_loopback
        except ValueError:
            local = url.hostname == "localhost"
        if (url.scheme != "http" or not local or url.username or url.password or url.query or url.fragment
                or url.path not in {"", "/", "/v1/traces"}):
            raise ValueError("telemetry_local_http_endpoint_required")
        endpoint = endpoint.rstrip("/")
        if not endpoint.endswith("/v1/traces"):
            endpoint += "/v1/traces"
        try:
            self.trace = importlib.import_module("opentelemetry.trace")
            sdk = importlib.import_module("opentelemetry.sdk.trace")
            resource = importlib.import_module("opentelemetry.sdk.resources")
            export = importlib.import_module("opentelemetry.sdk.trace.export")
            exporter = importlib.import_module("opentelemetry.exporter.otlp.proto.http.trace_exporter")
            self.propagator = importlib.import_module("opentelemetry.trace.propagation.tracecontext").TraceContextTextMapPropagator()
        except ImportError as exc:
            raise RuntimeError("telemetry_extra_required") from exc
        self.provider = sdk.TracerProvider(resource=resource.Resource({"service.name": "tsunagou"}))
        self.provider.add_span_processor(export.BatchSpanProcessor(exporter.OTLPSpanExporter(endpoint=endpoint, timeout=2, headers={})))

    def outcome(self, span: Any, outcome: str, error_code: str | None = None) -> None:
        if span is not None:
            span.set_attributes(safe_attributes({"outcome": outcome, "error_code": error_code}))
            if outcome in {"failed", "unknown", "rejected"}:
                span.set_status(self.trace.Status(self.trace.StatusCode.ERROR))

    @staticmethod
    def annotate(span: Any, values: Mapping[str, Any]) -> None:
        if span is not None:
            span.set_attributes(safe_attributes(values))

    @contextmanager
    def activate(self, traceparent: str | None = None) -> Iterator[None]:
        token = _active.set(self)
        incoming = _incoming.set(valid_traceparent(traceparent))
        try:
            yield
        finally:
            _incoming.reset(incoming)
            _active.reset(token)

    @contextmanager
    def span(self, name: str, attributes: Mapping[str, Any], *, parent: str | None = None) -> Iterator[Any]:
        if self.provider is None:
            yield None
            return
        context = None
        supplied = valid_traceparent(parent or _incoming.get())
        current = self.trace.get_current_span().get_span_context()
        if supplied and (parent or not current.is_valid):
            context = self.propagator.extract({"traceparent": supplied})
        with self.provider.get_tracer("tsunagou.boundaries").start_as_current_span(
            name, context=context, attributes=safe_attributes(attributes),
            record_exception=False, set_status_on_exception=False,
        ) as span:
            started = time.monotonic_ns()
            try:
                yield span
            except Exception:
                # SDK default exception events include arbitrary exception text.
                span.set_status(self.trace.Status(self.trace.StatusCode.ERROR))
                span.set_attribute("tsunagou.outcome", "failed")
                raise
            finally:
                logging.getLogger("tsunagou.telemetry").info(
                    "boundary_finished", extra={"boundary": name,
                    "duration_ms": (time.monotonic_ns() - started) / 1_000_000, **trace_log_fields()},
                )

    def current_traceparent(self) -> str | None:
        if self.provider is None:
            return None
        carrier: dict[str, str] = {}
        self.propagator.inject(carrier)
        return valid_traceparent(carrier.get("traceparent"))

    def close(self) -> None:
        if self.provider is not None:
            self.provider.force_flush(timeout_millis=3000)
            self.provider.shutdown()


_disabled = Telemetry()


def active_telemetry() -> Telemetry:
    value = _active.get()
    return value if isinstance(value, Telemetry) else _disabled


def trace_log_fields() -> dict[str, str]:
    parent = active_telemetry().current_traceparent()
    return {"trace_id": parent[3:35], "span_id": parent[36:52]} if parent else {}


class TraceLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        fields = trace_log_fields()
        record.trace_id = fields.get("trace_id")
        record.span_id = fields.get("span_id")
        return True
