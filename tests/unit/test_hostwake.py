"""Tests for the host-neutral managed Codex wake boundary."""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

import tsunagou.hostwake.dispatcher as dispatcher_module
from tsunagou.api.app import HostBindingRequest, create_app
from tsunagou.api.auth import LocalCommandAuthenticator
from tsunagou.application.wake_assistance import WakeAssistance
from tsunagou.hostwake import (
    CodexAppServerClient,
    CodexDesktopProvider,
    DesktopAttachProvider,
    HostBindingRef,
    HostWakeError,
    HostWakeProviderRegistry,
    HostWakeRequest,
    ManagedCodexProvider,
    PrivateBindingStore,
    UnixWebSocketAppServerClient,
    WakeDispatcher,
)
from tsunagou.hostwake.deepseek_wake import (
    DEEPSEEK_WAKE_PROVIDER,
    CombinedBindingStore,
    DeepSeekWakeBindingStore,
    DeepSeekWakeProvider,
)
from tsunagou.hostwake.timing import plan_delivery
from tsunagou.interfaces.runtime import CommandDispatcher
from tsunagou.modules.authority import AuthorityService
from tsunagou.modules.messaging import MessageStore
from tsunagou.platform.db.sqlite import ProjectDatabase
from tsunagou.platform.deepseek_wake import bind_deepseek_wake, ensure_deepseek_wake_configuration, set_deepseek_wake_mode
from tsunagou.shared_kernel.baseline import BASELINE_CAPABILITIES
from tsunagou.shared_kernel.time import format_timestamp, now_ms


class FakeProcess:
    def poll(self) -> int | None:
        return None


class FakeClient:
    methods = ("thread/start", "thread/resume", "turn/start")
    server_info = {"version": "fake-1"}

    def __init__(self) -> None:
        self.process = FakeProcess()
        self.calls: list[tuple[str, dict]] = []
        self.notifications = [{
            "method": "turn/completed",
            "params": {"turn": {"id": "turn-1", "status": "completed"}},
        }]

    def initialize(self) -> dict:
        return {"serverInfo": self.server_info, "methods": list(self.methods)}

    def request(self, method: str, params: dict, *, timeout: float = 30.0) -> dict:
        del timeout
        self.calls.append((method, params))
        if method == "thread/start":
            return {"thread": {"id": "thread-1", "sessionId": "session-1"}}
        if method == "thread/resume":
            return {"thread": {"id": params["threadId"], "sessionId": "session-1"}}
        if method == "turn/start":
            return {"turn": {"id": "turn-1", "status": "inProgress"}}
        raise AssertionError(method)

    def next_notification(self, *, timeout: float = 0.0) -> dict | None:
        del timeout
        return self.notifications.pop(0) if self.notifications else None

    def close(self) -> None:
        self.process = None


class FakeDesktopClient(FakeClient):
    methods = ("thread/read", "thread/resume", "turn/start")

    def __init__(self) -> None:
        super().__init__()
        self.notifications = [{
            "method": "turn/completed",
            "params": {"turn": {"id": "desktop-turn-1", "status": "completed"}},
        }]

    def request(self, method: str, params: dict, *, timeout: float = 30.0) -> dict:
        del timeout
        self.calls.append((method, params))
        if method == "thread/read":
            return {"thread": {"id": params["threadId"], "sessionId": "desktop-session-1"}}
        if method == "thread/resume":
            return {"thread": {"id": params["threadId"], "sessionId": "desktop-session-1"}}
        if method == "turn/start":
            return {"turn": {"id": "desktop-turn-1", "status": "inProgress"}}
        raise AssertionError(method)


class _HandshakeStream:
    def __init__(self) -> None:
        self.written = bytearray()

    def write(self, data: bytes) -> int:
        self.written.extend(data)
        return len(data)

    def flush(self) -> None:
        return None

    def read1(self, _length: int) -> bytes:
        request = self.written.decode("ascii")
        key = next(line.split(": ", 1)[1] for line in request.split("\r\n") if line.startswith("Sec-WebSocket-Key:"))
        accept = base64.b64encode(hashlib.sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii"),
        ).digest()).decode("ascii")
        return (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
        ).encode("ascii")


class _FrameSocket:
    def __init__(self, incoming: bytes = b"") -> None:
        self.incoming = bytearray(incoming)
        self.sent: list[bytes] = []

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def recv(self, length: int) -> bytes:
        if not self.incoming:
            return b""
        result = bytes(self.incoming[:length])
        del self.incoming[:length]
        return result


def test_unix_websocket_client_handshake_and_masked_frames() -> None:
    client = UnixWebSocketAppServerClient("C:/private/codex.sock")
    stream = _HandshakeStream()
    client._handshake(stream, stream)
    frame_socket = _FrameSocket()
    client.socket = frame_socket  # type: ignore[assignment]
    client._send_frame(b"hello")
    sent = frame_socket.sent[0]
    assert sent[0] == 0x81
    assert sent[1] & 0x80
    mask = sent[2:6]
    assert bytes(value ^ mask[index % 4] for index, value in enumerate(sent[6:])) == b"hello"

    incoming = bytes((0x81, 5)) + b"world"
    client.socket = _FrameSocket(incoming)  # type: ignore[assignment]
    final, opcode, payload = client._recv_frame()
    assert (final, opcode, payload) == (True, 1, b"world")


def test_desktop_attach_probe_rejects_a_different_thread_identity(tmp_path: Path) -> None:
    class MismatchClient(FakeDesktopClient):
        def request(self, method: str, params: dict, *, timeout: float = 30.0) -> dict:
            if method == "thread/read":
                self.calls.append((method, params))
                return {"thread": {"id": "different-thread", "sessionId": "desktop-session-1"}}
            return super().request(method, params, timeout=timeout)

    store = PrivateBindingStore(tmp_path / "bindings.json")
    provider = DesktopAttachProvider(store, client_factory=lambda record: MismatchClient())
    binding = provider.register_binding(
        agent_id="agent-1", binding_id="binding-1", adapter_profile="codex-desktop",
        cwd=tmp_path, scope_digest="sha256:scope", policy_digest="sha256:policy",
        endpoint=f"unix://{tmp_path / 'codex.sock'}", thread_id="thread-existing", attach_confirmed=True,
    )
    report = provider.probe(binding)
    assert report.status == "degraded"
    assert report.reason == "desktop_thread_identity_mismatch"


def test_desktop_attach_uses_the_shared_dispatcher_and_evidence(tmp_path: Path) -> None:
    store = PrivateBindingStore(tmp_path / "bindings.json")
    client = FakeDesktopClient()
    provider = DesktopAttachProvider(store, client_factory=lambda record: client, wake_timeout=0.1)
    bridge_config = tmp_path / "bridge.json"
    bridge_config.write_text(
        '{"command":"node","args":["bridge.js"],"env":{"TSUNAGOU_PROJECT_ROOT":"project"}}',
        encoding="utf-8",
    )
    _binding = provider.register_binding(
        agent_id="agent-1", binding_id="binding-1", adapter_profile="codex-desktop",
        cwd=tmp_path, scope_digest="sha256:scope", policy_digest="sha256:policy",
        endpoint=f"unix://{tmp_path / 'codex.sock'}", thread_id="thread-existing", attach_confirmed=True,
        bridge_config=bridge_config,
    )
    dispatcher = WakeDispatcher(provider, attempts_path=tmp_path / "attempts.json")
    result = dispatcher.on_delivery(
        message_id="message-desktop", recipient_agent_id="agent-1", project_id="project-1",
    )
    assert result["state"] == "completed"
    assert [item["kind"] for item in result["evidence"]] == [
        "thread_resumed", "turn_started", "turn_completed",
    ]
    turn_params = next(params for method, params in client.calls if method == "turn/start")
    assert turn_params["config"]["mcp_servers"]["tsunagou"]["args"] == ["bridge.js"]
    presented = dispatcher.record_presented(
        agent_id="agent-1", message_id="message-desktop",
        evidence_digest="sha256:presentation", evidence_kind="context_and_inbox_read",
    )
    assert presented is not None
    assert presented["evidence"][-1]["kind"] == "agent_presented"


def test_desktop_attach_rejects_a_stale_binding_after_reattach(tmp_path: Path) -> None:
    store = PrivateBindingStore(tmp_path / "bindings.json")
    clients: list[FakeDesktopClient] = []

    def factory(record: dict) -> FakeDesktopClient:
        del record
        client = FakeDesktopClient()
        clients.append(client)
        return client

    provider = DesktopAttachProvider(store, client_factory=factory)
    first = provider.register_binding(
        agent_id="agent-1", binding_id="binding-old", adapter_profile="codex-desktop",
        cwd=tmp_path, scope_digest="sha256:scope", policy_digest="sha256:policy",
        endpoint=f"unix://{tmp_path / 'old.sock'}", thread_id="thread-old", attach_confirmed=True,
    )
    provider.probe(first)
    second = provider.register_binding(
        agent_id="agent-1", binding_id="binding-new", adapter_profile="codex-desktop",
        cwd=tmp_path, scope_digest="sha256:scope", policy_digest="sha256:policy",
        endpoint=f"unix://{tmp_path / 'new.sock'}", thread_id="thread-new", attach_confirmed=True,
    )
    with pytest.raises(HostWakeError, match="revision is stale"):
        provider.probe(first)
    assert second.binding_id == "binding-new"
    assert clients[0].process is None


def test_desktop_attach_restart_keeps_retryable_wake_state(tmp_path: Path) -> None:
    store = PrivateBindingStore(tmp_path / "bindings.json")
    first_client = FakeDesktopClient()
    first_client.notifications = []
    first_provider = DesktopAttachProvider(store, client_factory=lambda record: first_client, wake_timeout=0.01)
    binding = first_provider.register_binding(
        agent_id="agent-1", binding_id="binding-1", adapter_profile="codex-desktop",
        cwd=tmp_path, scope_digest="sha256:scope", policy_digest="sha256:policy",
        endpoint=f"unix://{tmp_path / 'codex.sock'}", thread_id="thread-existing", attach_confirmed=True,
    )
    attempts = tmp_path / "attempts.json"
    first_dispatcher = WakeDispatcher(first_provider, attempts_path=attempts)
    first = first_dispatcher.on_delivery(
        message_id="message-restart", recipient_agent_id="agent-1", project_id="project-1",
    )
    assert first["state"] == "running"
    first_provider.close(binding, "daemon_restart")

    recovered_client = FakeDesktopClient()
    recovered_provider = DesktopAttachProvider(store, client_factory=lambda record: recovered_client, wake_timeout=0.1)
    restarted = WakeDispatcher(recovered_provider, attempts_path=attempts)
    assert restarted.status(message_id="message-restart", recipient_agent_id="agent-1")["state"] == "unknown"
    recovered = restarted.on_delivery(
        message_id="message-restart", recipient_agent_id="agent-1", project_id="project-1",
    )
    assert recovered["state"] == "completed"
    assert [method for method, _params in recovered_client.calls].count("thread/start") == 0


def test_desktop_attach_requires_explicit_local_endpoint_and_confirmation(tmp_path: Path) -> None:
    store = PrivateBindingStore(tmp_path / "bindings.json")
    provider = DesktopAttachProvider(store, client_factory=lambda record: FakeDesktopClient())
    with pytest.raises(HostWakeError, match="confirmation"):
        provider.register_binding(
            agent_id="agent-1", binding_id="binding-1", adapter_profile="codex-desktop",
            cwd=tmp_path, scope_digest="sha256:scope", policy_digest="sha256:policy",
            endpoint=f"unix://{tmp_path / 'codex.sock'}", thread_id="thread-existing",
        )
    with pytest.raises(HostWakeError, match="only an explicit unix"):
        provider.register_binding(
            agent_id="agent-1", binding_id="binding-1", adapter_profile="codex-desktop",
            cwd=tmp_path, scope_digest="sha256:scope", policy_digest="sha256:policy",
            endpoint="ws://127.0.0.1:9999", thread_id="thread-existing", attach_confirmed=True,
        )


def test_desktop_attach_probe_and_wake_never_creates_a_thread(tmp_path: Path) -> None:
    store = PrivateBindingStore(tmp_path / "bindings.json")
    client = FakeDesktopClient()
    provider = DesktopAttachProvider(store, client_factory=lambda record: client, wake_timeout=0.1)
    binding = provider.register_binding(
        agent_id="agent-1", binding_id="binding-1", adapter_profile="codex-desktop",
        cwd=tmp_path, scope_digest="sha256:scope", policy_digest="sha256:policy",
        endpoint=f"unix://{tmp_path / 'codex.sock'}", thread_id="thread-existing", attach_confirmed=True,
    )
    public = binding
    assert public.endpoint_kind == "unix_proxy"
    assert public.thread_id_digest is not None
    assert "thread-existing" not in repr(public)
    _stored_ref, record = store.get("agent-1")
    assert record["endpoint"].startswith("unix://")
    assert record["thread_id"] == "thread-existing"

    report = provider.probe(binding)
    assert report.status == "supported"
    assert "thread/read" in report.methods
    assert [method for method, _params in client.calls] == ["thread/read"]

    attempt = provider.wake(HostWakeRequest(
        wake_attempt_id="wake-desktop-1", agent_id="agent-1", message_id="message-1",
        project_id="project-1", binding=binding, cwd_digest=binding.cwd_digest,
        scope_digest=binding.scope_digest, policy_digest=binding.policy_digest,
    ))
    assert attempt.state == "completed"
    methods = [method for method, _params in client.calls]
    assert "thread/start" not in methods
    assert methods[-2:] == ["thread/resume", "turn/start"]


def test_private_binding_store_round_trip_keeps_raw_values_private(tmp_path: Path) -> None:
    store = PrivateBindingStore(tmp_path / "bindings.json")
    provider = ManagedCodexProvider(store, client_factory=lambda record: FakeClient())
    ref = provider.register_binding(
        agent_id="agent-1",
        binding_id="binding-1",
        adapter_profile="codex-main",
        cwd=tmp_path,
        scope_digest="sha256:scope",
        policy_digest="sha256:policy",
    )
    assert store.get("agent-1")[0] == ref
    assert "thread_id" not in ref.__dict__ if hasattr(ref, "__dict__") else True
    assert '"thread_id":' not in (tmp_path / "bindings.json").read_text(encoding="utf-8")


def test_managed_provider_probe_and_wake_record_separate_evidence(tmp_path: Path) -> None:
    store = PrivateBindingStore(tmp_path / "bindings.json")
    clients: list[FakeClient] = []

    def factory(record: dict) -> FakeClient:
        del record
        client = FakeClient()
        clients.append(client)
        return client

    provider = ManagedCodexProvider(store, client_factory=factory, wake_timeout=0.1)
    binding = provider.register_binding(
        agent_id="agent-1",
        binding_id="binding-1",
        adapter_profile="codex-worker",
        cwd=tmp_path,
        scope_digest="sha256:scope",
        policy_digest="sha256:policy",
    )
    report = provider.probe(binding)
    assert report.status == "supported"
    assert set(report.methods) == {"thread/start", "thread/resume", "turn/start"}
    assert report.capabilities["thread/start"] == "supported"
    assert report.capabilities["turn/start"] == "supported"

    attempt = provider.wake(HostWakeRequest(
        wake_attempt_id="wake-1",
        agent_id="agent-1",
        message_id="message-1",
        project_id="project-1",
        binding=binding,
        cwd_digest=binding.cwd_digest,
        scope_digest="sha256:scope",
        policy_digest="sha256:policy",
    ))
    assert attempt.state == "completed"
    assert [item.kind for item in attempt.evidence] == ["thread_resumed", "turn_started", "turn_completed"]
    assert clients[0].calls[0][0] == "thread/start"
    assert clients[0].calls[-1][0] == "turn/start"
    turn_prompt = clients[0].calls[-1][1]["input"][0]["text"]
    assert "context__project_read" in turn_prompt
    assert "message-1" not in turn_prompt


def test_wake_dispatcher_replays_same_delivery_without_second_turn(tmp_path: Path) -> None:
    store = PrivateBindingStore(tmp_path / "bindings.json")
    client = FakeClient()
    provider = ManagedCodexProvider(store, client_factory=lambda record: client, wake_timeout=0.1)
    binding = provider.register_binding(
        agent_id="agent-1", binding_id="binding-1", adapter_profile="codex-worker",
        cwd=tmp_path, scope_digest="sha256:scope", policy_digest="sha256:policy",
    )
    provider.probe(binding)
    diagnostics = tmp_path / "diagnostics.json"
    dispatcher = WakeDispatcher(provider, attempts_path=tmp_path / "attempts.json", diagnostics_path=diagnostics)
    first = dispatcher.on_delivery(message_id="message-1", recipient_agent_id="agent-1", project_id="project-1")
    second = dispatcher.on_delivery(message_id="message-1", recipient_agent_id="agent-1", project_id="project-1")
    assert first == second
    assert [method for method, _params in client.calls].count("turn/start") == 1
    presented = dispatcher.record_presented(
        agent_id="agent-1", message_id="message-1",
        evidence_digest="sha256:presented", evidence_kind="context_and_inbox_read",
    )
    assert presented is not None
    assert [item["kind"] for item in presented["evidence"]][-1] == "agent_presented"

    callback = dispatcher.on_delivery(
        message_id="message-callback", recipient_agent_id="agent-1", project_id="project-1",
        callback_status="delivered",
    )
    assert callback["evidence"][0]["kind"] == "callback_received"
    kinds = [item["kind"] for item in dispatcher.diagnostics(project_id="project-1")]
    assert "wake_requested" in kinds
    assert "callback_received" in kinds
    assert "thread_resumed" in kinds
    assert "turn_started" in kinds
    assert "turn_completed" in kinds
    count = len(dispatcher.diagnostics(project_id="project-1"))
    assert dispatcher.on_delivery(message_id="message-1", recipient_agent_id="agent-1", project_id="project-1") == first
    assert len(dispatcher.diagnostics(project_id="project-1")) == count
    restarted = WakeDispatcher(provider, attempts_path=tmp_path / "attempts.json", diagnostics_path=diagnostics)
    assert len(restarted.diagnostics(project_id="project-1")) >= count
    assert any(item["kind"] == "wake_unknown" for item in restarted.diagnostics(project_id="project-1"))


def test_wake_dispatcher_finishes_running_turn_in_background(tmp_path: Path) -> None:
    store = PrivateBindingStore(tmp_path / "bindings.json")
    client = FakeClient()
    client.notifications = []
    provider = ManagedCodexProvider(store, client_factory=lambda record: client, wake_timeout=0.01)
    _binding = provider.register_binding(
        agent_id="agent-1", binding_id="binding-1", adapter_profile="codex-worker",
        cwd=tmp_path, scope_digest="sha256:scope", policy_digest="sha256:policy",
    )
    dispatcher = WakeDispatcher(provider, attempts_path=tmp_path / "attempts.json")
    first = dispatcher.on_delivery(message_id="message-running", recipient_agent_id="agent-1", project_id="project-1")
    assert first["state"] == "running"
    client.notifications.append({
        "method": "turn/completed",
        "params": {"turn": {"id": "turn-1", "status": "completed"}},
    })
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        current = dispatcher.status(message_id="message-running", recipient_agent_id="agent-1")
        if current and current["state"] == "completed":
            break
        time.sleep(0.05)
    assert current is not None and current["state"] == "completed"


def test_presentation_evidence_survives_background_event_update(tmp_path: Path) -> None:
    store = PrivateBindingStore(tmp_path / "bindings.json")
    client = FakeClient()
    client.notifications = []
    provider = ManagedCodexProvider(store, client_factory=lambda record: client, wake_timeout=0.01)
    _binding = provider.register_binding(
        agent_id="agent-1", binding_id="binding-1", adapter_profile="codex-worker",
        cwd=tmp_path, scope_digest="sha256:scope", policy_digest="sha256:policy",
    )
    dispatcher = WakeDispatcher(provider, attempts_path=tmp_path / "attempts.json")
    first = dispatcher.on_delivery(message_id="message-race", recipient_agent_id="agent-1", project_id="project-1")
    assert first["state"] == "running"
    dispatcher.record_presented(
        agent_id="agent-1", message_id="message-race",
        evidence_digest="sha256:presentation", evidence_kind="context_and_inbox_read",
    )
    client.notifications.append({
        "method": "turn/completed",
        "params": {"turn": {"id": "turn-1", "status": "completed"}},
    })
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        current = dispatcher.status(message_id="message-race", recipient_agent_id="agent-1")
        if current and current["state"] == "completed":
            break
        time.sleep(0.05)
    assert current is not None
    assert any(entry["kind"] == "agent_presented" for entry in current["evidence"])


def test_restart_marks_running_attempt_unknown_then_allows_one_recovery(tmp_path: Path) -> None:
    store = PrivateBindingStore(tmp_path / "bindings.json")
    client = FakeClient()
    client.notifications = []
    provider = ManagedCodexProvider(store, client_factory=lambda record: client, wake_timeout=0.01)
    binding = provider.register_binding(
        agent_id="agent-1", binding_id="binding-1", adapter_profile="codex-worker",
        cwd=tmp_path, scope_digest="sha256:scope", policy_digest="sha256:policy",
    )
    attempts = tmp_path / "attempts.json"
    first_dispatcher = WakeDispatcher(provider, attempts_path=attempts)
    first = first_dispatcher.on_delivery(message_id="message-restart", recipient_agent_id="agent-1", project_id="project-1")
    assert first["state"] == "running"
    provider.close(binding, "daemon_restart")
    recovered_client = FakeClient()
    recovered_client.notifications = [{
        "method": "turn/completed",
        "params": {"turn": {"id": "turn-1", "status": "completed"}},
    }]
    recovered_provider = ManagedCodexProvider(store, client_factory=lambda record: recovered_client, wake_timeout=0.1)
    restarted = WakeDispatcher(recovered_provider, attempts_path=attempts)
    assert restarted.status(message_id="message-restart", recipient_agent_id="agent-1")["state"] == "unknown"
    recovered = restarted.on_delivery(message_id="message-restart", recipient_agent_id="agent-1", project_id="project-1")
    assert recovered["state"] == "completed"
    assert [method for method, _params in recovered_client.calls].count("turn/start") == 1


def test_jsonl_client_correlates_responses_and_preserves_notifications() -> None:
    server = (
        "import json,sys\n"
        "for line in sys.stdin:\n"
        "  msg=json.loads(line)\n"
        "  mid=msg.get('id')\n"
        "  method=msg.get('method')\n"
        "  if method=='initialize': out={'id':mid,'result':{'methods':['thread/start']}}\n"
        "  elif method=='thread/start': out={'id':mid,'result':{'thread':{'id':'thread-1'}}}\n"
        "  else: out={'id':mid,'result':{}}\n"
        "  print(json.dumps(out),flush=True)\n"
    )
    client = CodexAppServerClient(sys.executable, args=("-u", "-c", server), startup_timeout=2)
    try:
        result = client.initialize()
        assert result["methods"] == ["thread/start"]
        thread = client.request("thread/start", {})
        assert thread["thread"]["id"] == "thread-1"
    finally:
        client.close()


def test_managed_binding_resumes_after_provider_restart(tmp_path: Path) -> None:
    store = PrivateBindingStore(tmp_path / "bindings.json")
    first_client = FakeClient()
    first = ManagedCodexProvider(store, client_factory=lambda record: first_client)
    binding = first.register_binding(
        agent_id="agent-1", binding_id="binding-1", adapter_profile="codex-worker",
        cwd=tmp_path, scope_digest="sha256:scope", policy_digest="sha256:policy",
    )
    first.probe(binding)
    first.close(binding, "restart")

    stored_ref, _record = store.get("agent-1")
    second_client = FakeClient()
    second = ManagedCodexProvider(store, client_factory=lambda record: second_client)
    resumed = second.ensure_thread(stored_ref)
    assert resumed.resumed is True
    assert second_client.calls[0][0] == "thread/resume"
    second.close(stored_ref, "test_complete")


def test_managed_binding_builds_private_bridge_overrides(tmp_path: Path) -> None:
    bridge = tmp_path / "bridge.json"
    bridge.write_text(
        '{"command":"node","args":["C:/bridge/server.js"],"env":'
        '{"TSUNAGOU_HTTP_URL":"http://127.0.0.1:1234",'
        '"TSUNAGOU_TICKET_FILE":"C:/private/ticket.json"}}',
        encoding="utf-8",
    )
    store = PrivateBindingStore(tmp_path / "bindings.json")
    provider = ManagedCodexProvider(store)
    provider.register_binding(
        agent_id="agent-1", binding_id="binding-1", adapter_profile="codex-worker",
        cwd=tmp_path, scope_digest="sha256:scope", policy_digest="sha256:policy",
        bridge_config=bridge,
    )
    _ref, record = store.get("agent-1")
    client = provider._default_client(record)
    assert client.cwd == str(tmp_path.resolve())
    assert "mcp_servers.tsunagou.command=\"node\"" in client.args
    assert any("TSUNAGOU_TICKET_FILE" in item for item in client.args)


def test_managed_client_does_not_inherit_parent_codex_identity(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_SESSION_ID", "parent-conversation")
    store = PrivateBindingStore(tmp_path / "bindings.json")
    provider = ManagedCodexProvider(store)
    binding = provider.register_binding(
        agent_id="agent-1", binding_id="binding-1", adapter_profile="codex-worker",
        cwd=tmp_path, scope_digest="sha256:scope", policy_digest="sha256:policy",
    )
    _ref, record = store.get(binding.agent_id)
    client = provider._default_client(record)
    assert client.env is not None
    assert "CODEX_SESSION_ID" not in client.env


def test_user_http_binding_endpoint_returns_only_secret_free_reference(tmp_path: Path) -> None:
    store = PrivateBindingStore(tmp_path / "bindings.json")
    provider = ManagedCodexProvider(store, client_factory=lambda record: FakeClient())
    app = create_app(
        CommandDispatcher(Path(__file__).parents[2] / "protocol" / "registry" / "commands.json"),
        authenticator=LocalCommandAuthenticator(control_token="control"),
        hostwake_provider=provider,
    )
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/v1/host-wake/bindings")
    result = endpoint(
        HostBindingRequest(
            agent_id="agent-1", adapter_profile="codex-worker", cwd=str(tmp_path),
            scope_digest="sha256:scope", policy_digest="sha256:policy", sandbox="workspace-write",
        ),
        authorization="Bearer control", session_id=None, connection_epoch=None,
    )
    assert result["binding"]["agent_id"] == "agent-1"
    assert "thread_id" not in result["binding"]
    assert "session_id" not in result["binding"]


def test_user_http_desktop_attach_routes_to_shared_registry(tmp_path: Path) -> None:
    store = PrivateBindingStore(tmp_path / "bindings.json")
    registry = HostWakeProviderRegistry(
        ManagedCodexProvider(store, client_factory=lambda record: FakeClient()),
        DesktopAttachProvider(store, client_factory=lambda record: FakeDesktopClient()),
    )
    app = create_app(
        CommandDispatcher(Path(__file__).parents[2] / "protocol" / "registry" / "commands.json"),
        authenticator=LocalCommandAuthenticator(control_token="control"),
        hostwake_provider=registry,
    )
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/v1/host-wake/bindings")
    result = endpoint(
        HostBindingRequest(
            agent_id="agent-desktop", provider="desktop_attach", adapter_profile="codex-desktop",
            cwd=str(tmp_path), scope_digest="sha256:scope", policy_digest="sha256:policy",
            endpoint=f"unix://{tmp_path / 'codex.sock'}", thread_id="thread-existing", attach_confirmed=True,
        ),
        authorization="Bearer control", session_id=None, connection_epoch=None,
    )
    assert result["binding"]["provider"] == "desktop_attach"
    assert result["binding"]["endpoint_kind"] == "unix_proxy"
    assert "thread-existing" not in str(result)


def test_user_http_desktop_attach_requires_an_enrolled_active_agent(tmp_path: Path) -> None:
    store = PrivateBindingStore(tmp_path / "bindings.json")
    registry = HostWakeProviderRegistry(
        ManagedCodexProvider(store, client_factory=lambda record: FakeClient()),
        DesktopAttachProvider(store, client_factory=lambda record: FakeDesktopClient()),
    )
    app = create_app(
        CommandDispatcher(Path(__file__).parents[2] / "protocol" / "registry" / "commands.json"),
        authenticator=LocalCommandAuthenticator(control_token="control"),
        query_provider=lambda kind, project_id: {"items": []},
        hostwake_provider=registry,
    )
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/v1/host-wake/bindings")
    with pytest.raises(HTTPException) as error:
        endpoint(
            HostBindingRequest(
                agent_id="not-enrolled", provider="desktop_attach", adapter_profile="codex-desktop",
                cwd=str(tmp_path), scope_digest="sha256:scope", policy_digest="sha256:policy",
                endpoint=f"unix://{tmp_path / 'codex.sock'}", thread_id="thread-existing", attach_confirmed=True,
            ),
            authorization="Bearer control", session_id=None, connection_epoch=None,
        )
    assert error.value.status_code == 403
    assert error.value.detail == {"code": "host_agent_not_enrolled"}


def _bound_provider(tmp_path: Path, *, agent_id: str = "agent-1") -> tuple[ManagedCodexProvider, FakeClient]:
    store = PrivateBindingStore(tmp_path / "bindings.json")
    client = FakeClient()
    provider = ManagedCodexProvider(store, client_factory=lambda record: client, wake_timeout=0.1)
    provider.register_binding(
        agent_id=agent_id, binding_id="binding-1", adapter_profile="codex-worker",
        cwd=tmp_path, scope_digest="sha256:scope", policy_digest="sha256:policy",
    )
    return provider, client


def test_a_host_without_the_wake_methods_is_never_called(tmp_path: Path) -> None:
    """A published catalogue that omits the wake methods is an answer, not an outage.

    Acting on it ends the attempt instead of queueing work that cannot succeed, and the
    binding is marked degraded so the judgement is visible rather than implied.
    """
    provider, client = _bound_provider(tmp_path)
    binding = provider.store.get("agent-1")[0]
    provider.store.put(replace(binding, capabilities={**binding.capabilities, "turn/start": "unsupported"}))
    dispatcher = WakeDispatcher(provider, attempts_path=tmp_path / "attempts.json")
    result = dispatcher.on_delivery(message_id="message-1", recipient_agent_id="agent-1", project_id="project-1")
    assert result["state"] == "failed"
    assert result["error_code"] == "host_wake_capability_unsupported"
    assert client.calls == []
    assert provider.store.get("agent-1")[0].status == "degraded"
    assert [item["kind"] for item in dispatcher.diagnostics(project_id="project-1")] == ["wake_requested", "wake_failed"]


def test_a_degraded_binding_ends_the_attempt_without_a_host_call(tmp_path: Path) -> None:
    """Degraded means "not wakeable this way"; retrying it would loop on a known answer."""
    provider, client = _bound_provider(tmp_path)
    provider.store.update_status("agent-1", "degraded", reason="desktop_thread_unavailable")
    dispatcher = WakeDispatcher(provider, attempts_path=tmp_path / "attempts.json")
    result = dispatcher.on_delivery(message_id="message-1", recipient_agent_id="agent-1", project_id="project-1")
    assert result["state"] == "failed"
    assert result["error_code"] == "host_binding_degraded"
    assert client.calls == []


def test_an_unobservable_wake_is_closed_after_its_grace_period(tmp_path: Path) -> None:
    """A restart cannot inspect the original host turn, so the question must still end."""
    attempts = tmp_path / "attempts.json"
    attempts.write_text(json.dumps({
        "agent-1:message-1": {
            "wake_attempt_id": "wake-1", "agent_id": "agent-1", "message_id": "message-1",
            "project_id": "project-1", "state": "running", "evidence": [],
        },
    }), encoding="utf-8")
    provider, _client = _bound_provider(tmp_path)
    dispatcher = WakeDispatcher(provider, attempts_path=attempts)
    # Loading a restarted runtime turns "running" into "unknown" and starts the clock.
    assert dispatcher.status(message_id="message-1", recipient_agent_id="agent-1")["state"] == "unknown"
    assert dispatcher.sweep_unknown(grace_ms=0) == 1
    closed = dispatcher.status(message_id="message-1", recipient_agent_id="agent-1")
    assert closed["state"] == "failed"
    assert closed["error_code"] == "host_wake_unknown_expired"
    # Both transitions are on the record, including the one that closed the question.
    assert [item["kind"] for item in dispatcher.diagnostics(project_id="project-1")] == ["wake_unknown", "wake_failed"]


def test_the_attempt_journal_keeps_a_bounded_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The journal is rewritten whole on every change, so it may not grow forever."""
    monkeypatch.setattr(dispatcher_module, "_MAX_ATTEMPTS_KEPT", 2)
    attempts = tmp_path / "attempts.json"
    attempts.write_text(json.dumps({
        f"agent-1:message-{index}": {
            "wake_attempt_id": f"wake-{index}", "agent_id": "agent-1", "message_id": f"message-{index}",
            "project_id": "project-1", "state": "completed", "evidence": [],
            "updated_at": format_timestamp(now_ms() - (10 - index) * 1000),
        }
        for index in range(4)
    }), encoding="utf-8")
    provider, _client = _bound_provider(tmp_path)
    dispatcher = WakeDispatcher(provider, attempts_path=attempts)
    # In-flight work is never dropped; only closed history is trimmed, oldest first.
    dispatcher._save()
    kept = json.loads(attempts.read_text(encoding="utf-8"))
    assert len(kept) == 2
    assert set(kept) == {"agent-1:message-2", "agent-1:message-3"}


def test_the_callback_fact_is_recorded_without_starting_a_turn(tmp_path: Path) -> None:
    """The A2A request path reports a callback; it does not become a second wake path."""
    provider, client = _bound_provider(tmp_path)
    dispatcher = WakeDispatcher(provider, attempts_path=tmp_path / "attempts.json",
                                diagnostics_path=tmp_path / "diagnostics.json")
    recorded = dispatcher.note_callback(
        message_id="message-1", recipient_agent_id="agent-1", project_id="project-1",
        callback_status="delivered", command_id="a2a:message:1", actor_id="peer",
    )
    assert recorded["status"] == "recorded"
    assert client.calls == []
    assert dispatcher.status(message_id="message-1", recipient_agent_id="agent-1") is None
    assert [item["kind"] for item in dispatcher.diagnostics(project_id="project-1")] == ["callback_received"]
    # Re-recording the same callback adds nothing: one fact, one line.
    dispatcher.note_callback(
        message_id="message-1", recipient_agent_id="agent-1", project_id="project-1",
        callback_status="delivered", command_id="a2a:message:1", actor_id="peer",
    )
    assert len(dispatcher.diagnostics(project_id="project-1")) == 1


# ---------------------------------------------------------------------------
# DSH: the automatic channel that used to be missing entirely
# ---------------------------------------------------------------------------

def _dsh_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, agent_id: str = "agent-dsh",
                 conversation: str = "dsh-original-session", route_agent: str | None = None,
                 wake_mode: str = "queue", with_route: bool = True) -> tuple[DeepSeekWakeBindingStore, Path, Path]:
    """A verified DSH enrollment on disk: managed config plus this project's own route."""
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    ensure_deepseek_wake_configuration()
    set_deepseek_wake_mode(wake_mode)
    bind_deepseek_wake("project-1", agent_id, conversation)
    routes = tmp_path / "routing"
    routes.mkdir(parents=True, exist_ok=True)
    if with_route:
        credential = tmp_path / "bridge-session.json"
        credential.write_text(json.dumps({"agent_id": route_agent if route_agent is not None else agent_id,
                                          "session_id": "session-1"}), encoding="utf-8")
        (routes / (hashlib.sha256(conversation.encode()).hexdigest() + ".json")).write_text(json.dumps({
            "format_version": 1, "adapter": "deepseek", "conversation_id": conversation,
            "project_id": "project-1", "project_root": str(tmp_path), "session_file": str(credential),
        }), encoding="utf-8")
    store = DeepSeekWakeBindingStore(
        routes_dir=routes, project_id="project-1", project_root=tmp_path,
        overlay_path=tmp_path / "host-bindings-deepseek.json",
    )
    return store, routes, tmp_path / "bridge-session.json"


def _dsh_runner(declared: str = "turn_boundary") -> Any:
    def runner(action: str, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["conversation_id"] == "dsh-original-session"
        if action == "wake":
            return {"host": "deepseek", "state": "idle", "can_queue": True, "result": "queued",
                    "error_code": None, "evidence": ["deepseek:wake-plugin:accepted"],
                    "observed_at": format_timestamp(now_ms()), "turn_started": False,
                    "request_associated": True,
                    "delivery": plan_delivery(used=declared, declared=declared, source="plugin_wake_mode").to_public()}
        return {"host": "deepseek", "state": "idle", "can_queue": True, "result": "observed",
                "error_code": None, "evidence": ["deepseek:wake-plugin:status"],
                "observed_at": format_timestamp(now_ms()), "turn_started": False, "request_associated": False,
                "delivery": plan_delivery(used=declared, declared=declared,
                                          source="plugin_wake_mode_declared").to_public()}
    return runner


def test_a_verified_dsh_binding_has_a_working_automatic_channel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """DSH could never be woken automatically: every delivery died on the binding lookup.

    Before this, no provider store held a DSH binding, so ``WakeDispatcher`` ended every
    daemon-delivered DSH wake as ``failed / host_binding_not_found`` (16 of 16 on disk).
    """
    store, _routes, _credential = _dsh_fixture(tmp_path, monkeypatch)
    provider = DeepSeekWakeProvider(store, runner=_dsh_runner())
    dispatcher = WakeDispatcher(provider, attempts_path=tmp_path / "host-wake-attempts.json")
    result = dispatcher.on_delivery(message_id="message-dsh", recipient_agent_id="agent-dsh",
                                    project_id="project-1")
    assert result["state"] == "queued"
    assert result["error_code"] is None
    assert result["provider"] == DEEPSEEK_WAKE_PROVIDER
    assert result["delivery"]["used"] == "turn_boundary"
    assert result["delivery"]["declared"] == "turn_boundary"
    assert "degraded" not in result["delivery"]
    assert "host_binding_not_found" not in json.dumps(dispatcher.status(
        message_id="message-dsh", recipient_agent_id="agent-dsh"))
    journal = (tmp_path / "host-wake-attempts.json").read_text(encoding="utf-8")
    assert "host_binding_not_found" not in journal
    kinds = [item["kind"] for item in dispatcher.diagnostics(project_id="project-1")]
    # Requested, then the host's own acceptance, then the state the attempt reached.
    assert kinds == ["wake_requested", "wake_starting", "accepted", "wake_queued"]


def test_the_declared_timing_follows_the_plugin_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for mode, expected in (("queue", "turn_boundary"), ("steer", "step")):
        root = tmp_path / mode
        root.mkdir()
        store, _routes, _credential = _dsh_fixture(root, monkeypatch, wake_mode=mode)
        provider = DeepSeekWakeProvider(store, runner=_dsh_runner(declared=expected))
        assert provider.delivery_timing("agent-dsh") == (expected, "plugin_wake_mode")
        report = provider.probe(store.get("agent-dsh")[0])  # type: ignore[index]
        assert report.delivery_timing == expected
        dispatcher = WakeDispatcher(provider, attempts_path=root / "attempts.json")
        result = dispatcher.on_delivery(message_id="message-dsh", recipient_agent_id="agent-dsh",
                                        project_id="project-1")
        assert result["delivery"]["used"] == expected
        assert "degraded" not in result["delivery"]


def test_an_unbound_or_unverified_dsh_host_still_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Declared is not the same as verified, and neither is the same as unknown."""
    store, _routes, _credential = _dsh_fixture(tmp_path, monkeypatch)
    provider = DeepSeekWakeProvider(store, runner=_dsh_runner())
    dispatcher = WakeDispatcher(provider, attempts_path=tmp_path / "attempts.json")
    # Nobody at all.
    unknown = dispatcher.on_delivery(message_id="message-unknown", recipient_agent_id="agent-nobody",
                                     project_id="project-1")
    assert unknown["state"] == "failed"
    assert unknown["error_code"] == "host_binding_not_found"

    # Configured for this Agent, but this project holds no route that verifies it: the
    # plugin would accept the call, and that is exactly why it must not be made.
    declared_but_unverified, routes, _credential = _dsh_fixture(
        tmp_path / "other", monkeypatch, agent_id="agent-other", conversation="other-session", with_route=False)
    assert declared_but_unverified.get("agent-other") is None
    unverified = WakeDispatcher(DeepSeekWakeProvider(declared_but_unverified, runner=_dsh_runner()),
                               attempts_path=tmp_path / "attempts-2.json").on_delivery(
        message_id="message-other", recipient_agent_id="agent-other", project_id="project-1")
    assert unverified["state"] == "failed"
    assert unverified["error_code"] == "host_binding_not_found"
    del routes

    # A route that names another Agent is not this Agent's route either.
    mismatched, _routes, _credential = _dsh_fixture(
        tmp_path / "mismatch", monkeypatch, route_agent="agent-somebody-else")
    assert mismatched.get("agent-dsh") is None


def test_the_combined_store_keeps_both_channels_visible(tmp_path: Path) -> None:
    """One lookup, two stores: neither channel may hide the other's bindings."""
    codex_store = PrivateBindingStore(tmp_path / "codex-bindings.json")
    codex_provider = ManagedCodexProvider(codex_store, client_factory=lambda record: FakeClient())
    codex_provider.register_binding(
        agent_id="agent-codex", binding_id="binding-1", adapter_profile="codex-worker",
        cwd=tmp_path, scope_digest="sha256:scope", policy_digest="sha256:policy",
    )
    combined = CombinedBindingStore(codex_store, _NoBindings())
    assert combined.get("agent-codex")[0].provider == "managed_app_server"
    assert combined.get("agent-dsh") is None
    with pytest.raises(KeyError):
        combined.update_status("agent-nobody", "degraded")


class _NoBindings:
    def get(self, agent_id: str) -> None:
        del agent_id
        return None


class _OneBinding:
    """A store that knows exactly one Agent -- enough to prove a lane is visible."""

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id

    def get(self, agent_id: str) -> tuple[Any, dict[str, Any]] | None:
        if agent_id != self.agent_id:
            return None
        return (HostBindingRef(
            binding_id="binding-dsh", agent_id=agent_id, provider="deepseek_wake",
            adapter_profile="deepseek", endpoint_kind="plugin",
        ), {"wake_mode": "queue"})


class _OneLaneProvider:
    provider_name = "deepseek_wake"

    def __init__(self, agent_id: str) -> None:
        self.store = _OneBinding(agent_id)


def test_a_lane_added_to_extra_is_visible_without_reassigning_the_store(tmp_path: Path) -> None:
    """Adding a provider to ``extra`` has to be enough on its own.

    Live re-test, 2026-10-10: the DSH binding verified ``ready`` through its own store while
    the dispatcher -- reading ``registry.store``, which then held only the Codex store --
    answered ``host_binding_not_found`` for that same Agent. That is the dead-channel
    symptom 待改 12 removed, and it returns the moment a lane is added and the attribute is
    not reassigned by hand. So the registry merges the lanes itself, and this pins it.
    """

    codex_store = PrivateBindingStore(tmp_path / "host-bindings.json")
    registry = HostWakeProviderRegistry(
        ManagedCodexProvider(codex_store), DesktopAttachProvider(codex_store),
        extra=(_OneLaneProvider("agent-dsh"),),
    )
    # 没有任何人重新赋值 registry.store：这一行就是那条规则。
    found = registry.store.get("agent-dsh")
    assert found is not None and found[0].provider == "deepseek_wake"
    assert registry.store.get("agent-nobody") is None
    # Codex 那两条 lane 照旧：extra 只是并列，不是替换。
    assert [type(item).__name__ for item in registry.extra] == ["_OneLaneProvider"]


def test_a_degraded_dsh_binding_is_remembered_and_can_recover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A judgement about the automatic lane must outlive the process, and be reversible."""
    store, _routes, _credential = _dsh_fixture(tmp_path, monkeypatch)
    store.update_status("agent-dsh", "degraded", reason="host_wake_capability_unsupported")
    assert store.get("agent-dsh")[0].status == "degraded"  # type: ignore[index]
    reloaded = DeepSeekWakeBindingStore(
        routes_dir=tmp_path / "routing", project_id="project-1", project_root=tmp_path,
        overlay_path=tmp_path / "host-bindings-deepseek.json",
    )
    assert reloaded.get("agent-dsh")[0].status == "degraded"  # type: ignore[index]
    provider = DeepSeekWakeProvider(reloaded, runner=_dsh_runner())
    dispatcher = WakeDispatcher(provider, attempts_path=tmp_path / "attempts.json")
    blocked = dispatcher.on_delivery(message_id="message-dsh", recipient_agent_id="agent-dsh",
                                     project_id="project-1")
    assert blocked["error_code"] == "host_binding_degraded"
    reloaded.update_status("agent-dsh", "ready")
    assert reloaded.get("agent-dsh")[0].status == "ready"  # type: ignore[index]
    assert "degraded" not in (tmp_path / "host-bindings-deepseek.json").read_text(encoding="utf-8")


def test_a_second_message_on_an_admission_only_lane_is_still_announced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """受理通道上的第二条消息必须照样投出去（2026-10-10 回归）。

    这条 lane 只报"受理"，没有看护线程（``_ADMISSION_ONLY_PROVIDERS``），所以一次投递之后
    ``queued`` 就是它的**终态**。而派发器把"收件人已经有一个 queued 尝试"当成"合并进同一批"：
    第二条消息于是只被记成 alias 并**直接返回、不投递** —— 那个 agent 从此再也叫不醒，而且是
    静默的（实测里每个 agent 的唤醒数是 17/8/6/4，也就是 35 次里 34 次会被吞掉）。

    合并本身没错，错在它的前提：只有在"这个 queued 终将往前走"的通道上才成立（Codex 那条有
    watcher）。这里钉住受理通道的相反事实。
    """

    store, _routes, _credential = _dsh_fixture(tmp_path, monkeypatch)
    provider = DeepSeekWakeProvider(store, runner=_dsh_runner())
    dispatcher = WakeDispatcher(provider, attempts_path=tmp_path / "attempts.json")
    try:
        first = dispatcher.on_delivery(message_id="message-1", recipient_agent_id="agent-dsh",
                                       project_id="project-1")
        second = dispatcher.on_delivery(message_id="message-2", recipient_agent_id="agent-dsh",
                                        project_id="project-1")
        assert first["state"] == "queued" and second["state"] == "queued"
        assert second.get("coalesced_into") is None, "受理通道没有 watcher，合并等于静默丢失"
        assert second["wake_attempt_id"] != first["wake_attempt_id"], "第二条消息必须自己投一次"
        # 第一条仍留在台账里（它确实被宣告过），不是 alias。
        assert dispatcher.attempts[dispatcher._key("agent-dsh", "message-1")].get("coalesced_into") is None
    finally:
        dispatcher.stop()


def test_the_provider_class_timing_table_matches_the_declaration_table() -> None:
    """``wake_assistance`` reads a literal table; it must not drift from the classes."""
    from tsunagou.application.wake_assistance import _PROVIDER_DELIVERY_TIMING

    assert _PROVIDER_DELIVERY_TIMING == {
        "codex_desktop_app": CodexDesktopProvider.delivery_timing,
        "managed_app_server": ManagedCodexProvider.delivery_timing,
        "desktop_attach": DesktopAttachProvider.delivery_timing,
    }


def test_a_dsh_binding_is_never_created_by_the_http_api(tmp_path: Path) -> None:
    """The plugin's own configuration is the only source of a DSH binding."""
    store = _NoBindings()
    provider = DeepSeekWakeProvider(store)  # type: ignore[arg-type]
    registry = HostWakeProviderRegistry(
        ManagedCodexProvider(PrivateBindingStore(tmp_path / "codex.json"), client_factory=lambda record: FakeClient()),
        DesktopAttachProvider(PrivateBindingStore(tmp_path / "codex.json"), client_factory=lambda record: FakeClient()),
        extra=(provider,),
    )
    with pytest.raises(HostWakeError, match="unknown host binding provider"):
        registry.register_binding(provider=DEEPSEEK_WAKE_PROVIDER, agent_id="agent-x", binding_id="b",
                                  adapter_profile="deepseek", cwd=tmp_path,
                                  scope_digest="sha256:s", policy_digest="sha256:p")


# ---------------------------------------------------------------------------
# Why a wake is refused: one classification per lane, including the dead branch
# ---------------------------------------------------------------------------

class _RefusalFixture:
    """A project with one local sender and one target whose machine scope is chosen.

    ``target_machine`` writes the invitation-time machine name; ``with_target_route``
    removes (or keeps) the project's own local route for that Agent. The two together
    are what decide ``machine_scope``: a verified route means local, a name without one
    means remote, and neither means unknown.
    """

    def __init__(self, root: Path, target_machine: str | None, *, with_target_route: bool = True) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.authority = AuthorityService()
        self.messages = MessageStore()
        self.routes = {host: root / "routes" / host for host in ("codex", "opencode", "deepseek")}
        self.agents = []
        for index, host in enumerate(("opencode", "opencode")):
            conversation = f"refusal-conversation-{index}"
            ticket = self.authority.issue_ticket(f"{host}:test", conversation)
            receipt = self.authority.redeem_ticket(ticket, f"{host}:test", conversation, baseline={"baseline": {
                name: {"status": "supported", "evidence_refs": [f"fixture:{name}"]} for name in BASELINE_CAPABILITIES
            }})
            self.agents.append(receipt)
            session = root / f"session-{index}.json"
            session.write_text(json.dumps(asdict(receipt)), encoding="utf-8")
            route = self.routes[host] / (hashlib.sha256(conversation.encode()).hexdigest() + ".json")
            route.parent.mkdir(parents=True, exist_ok=True)
            route.write_text(json.dumps({"format_version": 1, "adapter": host, "project_id": "project",
                                        "project_root": str(root), "conversation_id": conversation,
                                        "session_file": str(session)}), encoding="utf-8")
            if index == 1 and not with_target_route:
                route.unlink()
        if target_machine is not None:
            self.authority.agents[self.agents[1].agent_id].machine = target_machine
        self.database = ProjectDatabase(root / "state.sqlite3", project_id="project")
        self.service = WakeAssistance(
            authority=self.authority, messages=self.messages, project_id="project", project_root=root,
            state_dir=root, database=self.database, native=WakeDispatcher(object()),  # type: ignore[arg-type]
            route_directories=self.routes, runner=lambda action, **kwargs: {"state": "idle", "can_queue": True,
                                                                          "result": "observed"},
        )

    def send(self) -> str:
        return self.messages.send(command_id="origin", sender_agent_id=self.agents[0].agent_id,
                                  recipient_agent_id=self.agents[1].agent_id, kind="message",
                                  subject_ref="task/t", summary="body",
                                  response_contract={"required": True}).message_id

    def status(self, message_id: str) -> dict[str, Any]:
        receipt = self.agents[0]
        return self.service.status({"message_id": message_id}, {
            "principal_id": receipt.agent_id, "session_id": receipt.session_id,
            "connection_epoch": receipt.connection_epoch,
        })


def test_the_shipped_container_wires_both_channels_into_one_dispatcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registry routes, and the dispatcher looks bindings up through a combined store.

    Wiring the combined store *as* the dispatcher's provider instead of onto the
    registry is silent and expensive: ``getattr(provider, "store")`` is then ``None``,
    so every delivery — including the Codex lanes that worked before — fails with
    ``host_binding_not_found``. Nothing else catches that, so this test does.
    """
    from tsunagou.bootstrap.container import build_application
    from tsunagou.modules.projects import ProjectRegistry

    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    ProjectRegistry.initialize(root, name="wiring", objective="verify the wake wiring only")
    monkeypatch.setenv("TSUNAGOU_PROJECT_ROOT", str(root))
    monkeypatch.setenv("TSUNAGOU_STATE_DIR", str(root / ".tsunagou" / "local"))
    monkeypatch.setenv("TSUNAGOU_CONTROL_TOKEN", "control")
    monkeypatch.setenv("TSUNAGOU_HOST_WAKE", "auto")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    app = build_application()
    try:
        registry = app.state.hostwake_provider
        dispatcher = app.state.wake_dispatcher
        assert dispatcher.provider is registry
        assert [type(item).__name__ for item in registry.extra] == ["DeepSeekWakeProvider"]
        assert isinstance(registry.store, CombinedBindingStore)
        assert registry.store.get("nobody-at-all") is None
        # 空闲看门狗要能问"这条会话现在在干什么"（2026-10-10：worker 输出总结后会话就空闲，
        # 没有人再叫它）。这个问题只有宿主能答，所以接的是注册表那条 lane 路由；没有绑定的
        # Agent 必须得到 None（"不说"），而不是被猜成 idle。
        watchdog = app.state.idle_watchdog
        assert watchdog.reader.session_state is not None, "宿主观察没接上看门狗"
        assert watchdog.reader.session_state("nobody-at-all") is None
    finally:
        app.state.host_delivery.stop()
        app.state.project_database.release_process_lock()


def test_each_lane_reports_its_own_refusal_reason(tmp_path: Path) -> None:
    """Pinning the classification, including the branch that used to be unreachable.

    ``cross_machine_unsupported`` could never be produced: the machine field was only
    ever ``unknown`` or ``local``, so a network-enrolled Agent was always reported as
    ``host_identity_unverified`` — which is not what was wrong with it.
    """
    # Enrolled here, route intact: this is a local Agent, so nothing is refused.
    local = _RefusalFixture(tmp_path / "local", None)
    assert local.status(local.send())["error_code"] is None
    assert local.status(local.send())["target"]["machine_scope"] == "local"

    # Enrolled here but no verifiable local route: unproven, not remote.
    unproven = _RefusalFixture(tmp_path / "unproven", None, with_target_route=False)
    assert unproven.status(unproven.send())["error_code"] == "host_identity_unverified"
    assert unproven.status(unproven.send())["target"]["machine_scope"] == "unknown"

    # Invited from another machine: nothing here can reach it, and the refusal says so.
    remote = _RefusalFixture(tmp_path / "remote", "workstation-b", with_target_route=False)
    refused = remote.status(remote.send())
    assert refused["lane"] == "unsupported"
    assert refused["error_code"] == "cross_machine_unsupported"
    assert refused["target"]["machine"] == "workstation-b"
    assert refused["target"]["machine_scope"] == "remote"
    # The caller is told the truth in words as well as in code: it comes and collects.
    assert "跨机器" in refused["next"] and "自己来取" in refused["next"]


def test_a_local_route_beats_a_self_reported_machine_name(tmp_path: Path) -> None:
    """Where an Agent is, is decided by the verified route — not by what it called itself."""
    fixture = _RefusalFixture(tmp_path, "some-other-name")
    target = fixture.status(fixture.send())["target"]
    assert target["machine_scope"] == "local"
    assert target["machine"] == "local"
    # The raw self-reported value stays visible: it is a fact, just not the verdict.
    assert target["machine_name"] == "some-other-name"
