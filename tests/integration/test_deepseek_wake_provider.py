"""The automatic DSH wake path, end to end against a stub of the shipped plugin.

Nothing here contacts a real Desktop. The stub speaks the same two loopback routes
with the same request and response shapes as ``packages/dsh-wake-plugin`` (whose own
contract is pinned by that package's tests and by
``tests/integration/test_deepseek_wake_plugin.py``), so this file answers one question
only: does a DSH-bound Agent now have a working **daemon-delivered** channel?

Before the provider existed, no binding store held a DSH binding, so every such
delivery ended as ``failed / host_binding_not_found`` without a single HTTP call.
"""

from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from tsunagou.hostwake.deepseek_wake import DeepSeekWakeBindingStore, DeepSeekWakeProvider
from tsunagou.hostwake.dispatcher import WakeDispatcher
from tsunagou.platform.deepseek_wake import (
    bind_deepseek_wake,
    deepseek_wake_runtime_path,
    ensure_deepseek_wake_configuration,
    set_deepseek_wake_mode,
)

PROJECT = "project-1"
AGENT = "agent-dsh"
SESSION = "dsh-original-session"


class _PluginStub:
    """The plugin's two routes, with its documented shapes and status codes."""

    def __init__(self, *, exists: bool = True, state: str = "idle", accept: bool = True) -> None:
        self.calls: list[dict[str, Any]] = []
        self.exists, self.state, self.accept = exists, state, accept
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:
                pass

            def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's own name
                length = int(self.headers["Content-Length"])
                body = json.loads(self.rfile.read(length))
                outer.calls.append({"path": self.path, "body": body,
                                    "authorization": self.headers.get("Authorization")})
                if self.path.endswith("/status"):
                    payload: dict[str, Any] = {
                        "ok": True, "project_id": body["project_id"], "agent_id": body["agent_id"],
                        "session_id": body["session_id"], "exists": outer.exists,
                        "loaded": True, "state": outer.state if outer.exists else "unknown",
                        "queueable": outer.exists,
                    }
                    code = 200
                elif not outer.exists:
                    # The plugin checks existence before submitting and refuses here.
                    payload = {"ok": False, "error": "session_not_found"}
                    code = 404
                else:
                    request_id = "tsunagou-wake-v1:" + hashlib.sha256(json.dumps(
                        [body["project_id"], body["agent_id"], body["session_id"], body["message_id"]],
                        ensure_ascii=False, separators=(",", ":"),
                    ).encode()).hexdigest()
                    payload = ({"ok": True, "accepted": True, "request_id": request_id} if outer.accept
                               else {"ok": False, "error": "submit_failed"})
                    code = 202 if outer.accept else 502
                raw = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


@pytest.fixture
def dsh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A verified DSH enrollment whose plugin is a stub, reachable on loopback."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    ensure_deepseek_wake_configuration()
    bind_deepseek_wake(PROJECT, AGENT, SESSION)
    stub = _PluginStub()
    runtime = deepseek_wake_runtime_path()
    runtime.parent.mkdir(parents=True, exist_ok=True)
    runtime.write_text(json.dumps({
        "format_version": 1, "contract_version": 1, "plugin_version": "0.1.0",
        "endpoint": f"http://127.0.0.1:{stub.server.server_port}",
        "instance_id": "stub", "pid": 1,
    }), encoding="utf-8")
    credential = tmp_path / "bridge-session.json"
    credential.write_text(json.dumps({"agent_id": AGENT, "session_id": "session-1"}), encoding="utf-8")
    routes = tmp_path / "routing"
    routes.mkdir(parents=True, exist_ok=True)
    (routes / (hashlib.sha256(SESSION.encode()).hexdigest() + ".json")).write_text(json.dumps({
        "format_version": 1, "adapter": "deepseek", "conversation_id": SESSION,
        "project_id": PROJECT, "project_root": str(tmp_path), "session_file": str(credential),
    }), encoding="utf-8")
    try:
        yield tmp_path, routes, stub
    finally:
        stub.stop()


def _dispatcher(root: Path, routes: Path, *, attempts: str = "host-wake-attempts.json") -> WakeDispatcher:
    store = DeepSeekWakeBindingStore(
        routes_dir=routes, project_id=PROJECT, project_root=root,
        overlay_path=root / "host-bindings-deepseek.json",
    )
    return WakeDispatcher(DeepSeekWakeProvider(store), attempts_path=root / attempts)


@pytest.mark.parametrize(("mode", "timing"), [("queue", "turn_boundary"), ("steer", "step")])
def test_a_daemon_delivery_wakes_a_bound_dsh_session(
    dsh: tuple[Path, Path, _PluginStub], mode: str, timing: str,
) -> None:
    root, routes, stub = dsh
    set_deepseek_wake_mode(mode)
    dispatcher = _dispatcher(root, routes)
    result = dispatcher.on_delivery(message_id="message-dsh", recipient_agent_id=AGENT, project_id=PROJECT)

    assert result["state"] == "queued"
    assert result["error_code"] is None
    assert result["provider"] == "deepseek_wake"
    # The reminder really was submitted, once, to the plugin's own wake route.
    wake_calls = [call for call in stub.calls if call["path"] == "/tsunagou/wake"]
    assert len(wake_calls) == 1
    assert set(wake_calls[0]["body"]) == {"project_id", "agent_id", "session_id", "message_id"}
    assert wake_calls[0]["body"]["message_id"] == "message-dsh"
    assert wake_calls[0]["authorization"].startswith("Bearer ")

    # The effective timing is reported, and it is the mode the plugin submits with.
    assert result["delivery"]["used"] == timing
    assert result["delivery"]["declared"] == timing
    assert "degraded" not in result["delivery"]

    # No turn is claimed: admission is not execution.
    assert result["evidence"][0]["kind"] == "accepted"
    journal = (root / "host-wake-attempts.json").read_text(encoding="utf-8")
    assert "host_binding_not_found" not in journal
    assert "turn_started" not in journal


def test_an_unbound_agent_is_refused_without_touching_the_plugin(dsh: tuple[Path, Path, _PluginStub]) -> None:
    root, routes, stub = dsh
    result = _dispatcher(root, routes).on_delivery(
        message_id="message-nobody", recipient_agent_id="agent-nobody", project_id=PROJECT)
    assert result["state"] == "failed"
    assert result["error_code"] == "host_binding_not_found"
    assert stub.calls == []


def test_a_session_that_no_longer_exists_fails_without_claiming_a_wake(
    dsh: tuple[Path, Path, _PluginStub],
) -> None:
    root, routes, stub = dsh
    stub.exists = False
    result = _dispatcher(root, routes).on_delivery(
        message_id="message-missing", recipient_agent_id=AGENT, project_id=PROJECT)
    assert result["state"] == "failed"
    assert result["error_code"] == "deepseek_wake_session_not_found"
    # The wake action observes the session before submitting (that observation is what
    # makes a succeeded wake report a real state), then the plugin itself refuses.
    assert [call["path"] for call in stub.calls] == ["/tsunagou/wake/status", "/tsunagou/wake"]


def test_a_rejected_submission_is_a_failure_not_a_queue(dsh: tuple[Path, Path, _PluginStub]) -> None:
    root, routes, stub = dsh
    stub.accept = False
    result = _dispatcher(root, routes).on_delivery(
        message_id="message-rejected", recipient_agent_id=AGENT, project_id=PROJECT)
    assert result["state"] == "failed"
    assert result["error_code"] == "deepseek_wake_submit_failed"


def test_the_same_delivery_is_not_woken_twice(dsh: tuple[Path, Path, _PluginStub]) -> None:
    root, routes, stub = dsh
    dispatcher = _dispatcher(root, routes)
    first = dispatcher.on_delivery(message_id="message-once", recipient_agent_id=AGENT, project_id=PROJECT)
    second = dispatcher.on_delivery(message_id="message-once", recipient_agent_id=AGENT, project_id=PROJECT)
    assert first["state"] == second["state"] == "queued"
    assert len([call for call in stub.calls if call["path"] == "/tsunagou/wake"]) == 1
