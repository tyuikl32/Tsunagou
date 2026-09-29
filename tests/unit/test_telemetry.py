from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import pytest
from tools.dev.collect_acceptance_trace import create_collector

from tsunagou.platform.telemetry import Telemetry, TraceLogFilter, active_telemetry, valid_traceparent


def test_disabled_telemetry_is_noop_and_does_not_require_sdk() -> None:
    telemetry = Telemetry()
    with telemetry.activate(), telemetry.span("command.execute", {"command_id": "id"}) as span:
        assert span is None
        assert active_telemetry().current_traceparent() is None
    assert valid_traceparent("00-" + "0" * 32 + "-" + "1" * 16 + "-01") is None
    telemetry.close()


@pytest.mark.parametrize("endpoint", ["https://127.0.0.1:4318", "http://example.com:4318", "http://127.0.0.1:4318/?token=x",
                                     "http://user:secret@localhost:4318", "http://127.0.0.1:4318/other"])
def test_export_is_explicit_and_loopback_only(endpoint: str) -> None:
    with pytest.raises(ValueError, match="telemetry_local_http_endpoint_required"):
        Telemetry(endpoint)


def test_actual_sdk_otlp_export_parentage_and_privacy(tmp_path: Path) -> None:
    pytest.importorskip("opentelemetry.sdk.trace")
    output = tmp_path / "spans.jsonl"
    receiver = create_collector(output)
    thread = threading.Thread(target=receiver.serve_forever, daemon=True)
    thread.start()
    telemetry = Telemetry(f"http://127.0.0.1:{receiver.server_port}")
    parent = "00-" + "1" * 32 + "-" + "2" * 16 + "-01"
    try:
        with telemetry.activate(parent):
            with telemetry.span("command.execute", {"command_id": "cmd-1", "token": "SENTINEL-TOKEN", "prompt": "SENTINEL-PROMPT"}):
                saved = telemetry.current_traceparent()
                record = logging.makeLogRecord({"msg": "safe"})
                TraceLogFilter().filter(record)
                assert record.trace_id == "1" * 32
            with telemetry.span("outbox.deliver", {"message_id": "msg-1"}, parent=saved):
                with pytest.raises(ValueError):
                    with telemetry.span("host.wake", {"wake_attempt_id": "wake-1"}):
                        raise ValueError("SENTINEL-EXCEPTION")
        telemetry.close()
        raw = output.read_text(encoding="utf-8")
        assert "SENTINEL" not in raw
        rows = {row["name"]: row for row in map(json.loads, raw.splitlines())}
        assert len(rows) == 3
        assert {row["trace_id"] for row in rows.values()} == {"1" * 32}
        assert rows["command.execute"]["parent_span_id"] == "2" * 16
        assert rows["outbox.deliver"]["parent_span_id"] == rows["command.execute"]["span_id"]
        assert rows["host.wake"]["parent_span_id"] == rows["outbox.deliver"]["span_id"]
        assert rows["host.wake"]["status"] == 2
        assert all(row["duration_ms"] >= 0 and row["token_usage"] == "unavailable" for row in rows.values())
    finally:
        receiver.shutdown()
        receiver.server_close()
        thread.join(timeout=3)
