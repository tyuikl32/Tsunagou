from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from tsunagou.application import deepseek_wake_runner as runner


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    ids = {"project_id": "project", "agent_id": "worker", "session_id": "original-session"}
    state: dict[str, Any] = {"calls": [], "status": "unloaded", "error": None}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert self.headers["Authorization"] == "Bearer private-key"
            state["calls"].append((self.path, payload))
            if state["error"]:
                code, value = state["error"]
            elif self.path.endswith("/status"):
                code, value = 200, {"ok": True, **ids, "exists": True, "loaded": state["status"] != "unloaded",
                                    "state": state["status"], "queueable": True}
            else:
                key = [payload[k] for k in ("project_id", "agent_id", "session_id", "message_id")]
                digest = hashlib.sha256(json.dumps(key, separators=(",", ":")).encode()).hexdigest()
                code, value = 202, {"ok": True, "accepted": True, "request_id": "tsunagou-wake-v1:" + digest}
            self.send_response(code)
            if code == 302:
                self.send_header("Location", state["endpoint"] + "/credential-leak")
            self.end_headers()
            self.wfile.write(json.dumps(value).encode())

        def log_message(self, *_args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["endpoint"] = f"http://127.0.0.1:{server.server_port}"
    runtime = tmp_path / "runtime.json"
    state["runtime"] = runtime
    runtime.write_text(json.dumps({"format_version": 1, "contract_version": 1, "endpoint": state["endpoint"]}))
    monkeypatch.setattr(runner, "deepseek_wake_runtime_path", lambda: runtime)
    monkeypatch.setattr(runner, "read_deepseek_wake_configuration",
                        lambda: {"format_version": 1, "key": "private-key", "bindings": [ids]})
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def invoke(action: str = "status", **kwargs: Any) -> dict[str, Any]:
    return runner.run_deepseek_operation(action, project_id="project", agent_id=kwargs.get("agent_id", "worker"),
                                        conversation_id="original-session", message_id="message")


def test_http_original_session_status_and_admission_are_separate(host: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://invalid.example:9")
    assert invoke()["state"] == "unloaded"
    value = invoke("wake")
    assert value["result"] == "queued" and value["request_associated"] is True
    assert value["turn_started"] is False and value["version"] is None
    assert "private-key" not in json.dumps(value) and "original-session" not in json.dumps(value)
    assert host["calls"][1] == ("/tsunagou/wake", {
        "project_id": "project", "agent_id": "worker", "session_id": "original-session", "message_id": "message",
    })


@pytest.mark.parametrize("endpoint", ["http://example.com:80", "http://127.0.0.1:80@evil.example", "http://localhost:80",
                                       "http://127.0.0.1:80/?key=secret", "https://127.0.0.1:80", "http://127.0.0.1:80/path"])
def test_invalid_endpoints_never_receive_credentials(host: Any, endpoint: str) -> None:
    host["runtime"].write_text(json.dumps({"format_version": 1, "contract_version": 1, "endpoint": endpoint}))
    assert invoke()["error_code"] == "deepseek_wake_runtime_invalid"
    assert host["calls"] == []


def test_unbound_target_and_missing_plugin_do_not_send(host: Any) -> None:
    assert invoke(agent_id="other")["error_code"] == "deepseek_wake_binding_required"
    host["runtime"].unlink()
    assert invoke()["error_code"] == "deepseek_wake_plugin_not_running"
    assert host["calls"] == []


@pytest.mark.parametrize(("code", "error", "unknown"), [
    (401, "unauthorized", False), (403, "target_not_bound", False),
    (409, "session_subagent_owned", False), (504, "submit_unknown", True),
    (500, "private secret error", True),
])
def test_plugin_errors_are_safe_and_unknown_is_not_success(host: Any, code: int, error: str, unknown: bool) -> None:
    host["error"] = code, {"error": error, "reason": "private-key original-session"}
    value = invoke("wake")
    assert value["result"] == ("unknown" if unknown else "failed")
    assert all(text not in json.dumps(value) for text in ("private-key", "original-session", "private secret"))


def test_redirect_is_not_followed(host: Any) -> None:
    host["error"] = 302, {"error": "redirect"}
    assert invoke("wake")["result"] == "unknown"
    assert len(host["calls"]) == 1
