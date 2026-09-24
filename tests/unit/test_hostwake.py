"""Tests for the host-neutral managed Codex wake boundary."""

from __future__ import annotations

import base64
import hashlib
import sys
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

from tsunagou.api.app import HostBindingRequest, create_app
from tsunagou.api.auth import LocalCommandAuthenticator
from tsunagou.hostwake import (
    CodexAppServerClient,
    DesktopAttachProvider,
    HostWakeError,
    HostWakeProviderRegistry,
    HostWakeRequest,
    ManagedCodexProvider,
    PrivateBindingStore,
    UnixWebSocketAppServerClient,
    WakeDispatcher,
)
from tsunagou.interfaces.runtime import CommandDispatcher


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
    dispatcher = WakeDispatcher(provider, attempts_path=tmp_path / "attempts.json")
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
