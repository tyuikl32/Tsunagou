"""Temporary localhost OTLP/HTTP receiver for acceptance, not a product service.

Run with the telemetry extra installed. Decode actual protobuf requests and
persist only the allowlisted boundary metadata, never raw request bytes.
"""

from __future__ import annotations

import argparse
import gzip
import importlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import Any

from tsunagou.platform.telemetry import safe_attributes
from tsunagou.shared_kernel.time import format_timestamp, now_ms

BOUNDARIES = {"command.execute", "a2a.submit", "outbox.deliver", "host.wake", "onboarding.restore"}


def decode_spans(data: bytes) -> list[dict[str, Any]]:
    proto = importlib.import_module("opentelemetry.proto.collector.trace.v1.trace_service_pb2")
    request = proto.ExportTraceServiceRequest()
    request.ParseFromString(data)
    rows = []
    for resource in request.resource_spans:
        for scope in resource.scope_spans:
            for span in scope.spans:
                if span.name not in BOUNDARIES:
                    continue
                attrs = {entry.key.removeprefix("tsunagou."): entry.value.string_value
                         for entry in span.attributes if entry.key.startswith("tsunagou.")}
                rows.append({
                    "name": span.name, "trace_id": span.trace_id.hex(), "span_id": span.span_id.hex(),
                    "parent_span_id": span.parent_span_id.hex() or None,
                    "started_at": format_timestamp(span.start_time_unix_nano // 1_000_000),
                    "finished_at": format_timestamp(span.end_time_unix_nano // 1_000_000),
                    "duration_ms": (span.end_time_unix_nano - span.start_time_unix_nano) / 1_000_000,
                    "recorded_at": format_timestamp(now_ms()), "attributes": safe_attributes(attrs),
                    "status": span.status.code, "token_usage": "unavailable",
                })
    return rows


def create_collector(output: Path, port: int = 0) -> ThreadingHTTPServer:
    output.parent.mkdir(parents=True, exist_ok=True)
    lock = Lock()

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path != "/v1/traces":
                self.send_error(404)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 4 * 1024 * 1024:
                    raise ValueError("invalid_size")
                data = self.rfile.read(size)
                if self.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                rows = decode_spans(data)
                with lock, output.open("a", encoding="utf-8", newline="\n") as handle:
                    for row in rows:
                        handle.write(json.dumps(row, sort_keys=True) + "\n")
                self.send_response(200)
                self.send_header("Content-Type", "application/x-protobuf")
                self.send_header("Content-Length", "0")
                self.end_headers()
            except Exception:
                self.send_error(400, "Invalid OTLP trace request")

        def log_message(self, format: str, *args: Any) -> None:
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Receiver)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=4318)
    parser.add_argument("--ready-file", type=Path)
    args = parser.parse_args()
    server = create_collector(args.output, args.port)
    info = {"endpoint": f"http://127.0.0.1:{server.server_port}/v1/traces",
            "started_at": format_timestamp(now_ms()), "output": str(args.output.resolve())}
    if args.ready_file:
        args.ready_file.write_text(json.dumps(info) + "\n", encoding="utf-8")
    print(json.dumps(info), flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
