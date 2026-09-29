from __future__ import annotations

import asyncio
import copy
import json
import struct
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tsunagou.hostwake import CodexDesktopProvider, HostWakeError, HostWakeRequest, PrivateBindingStore, WakeDispatcher
from tsunagou.hostwake.codex_desktop import NativeAppToolsClient


class DesktopHost:
    def __init__(self, *, native: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.active = False
        self.turns: list[dict[str, Any]] = []
        self.send_error: str | None = None
        self.read_error: str | None = None
        self.native = native

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, arguments))
        assert arguments["threadId"] == "original-thread"
        if name == "read_thread":
            if self.read_error:
                raise HostWakeError(self.read_error, "host unavailable")
            turns = copy.deepcopy(list(reversed(self.turns)))
            if not arguments.get("includeOutputs"):
                for turn in turns:
                    for item in turn["items"]:
                        item.pop("output", None)
            return {"thread": {"id": "original-thread", "status": {"type": "active" if self.active else "idle"}}, "turns": turns}
        if name == "send_message_to_thread":
            assert set(arguments) == {"threadId", "hostId", "prompt"}
            item = ({"type": "functionCallOutput", "name": "send_message_to_thread", "namespace": "codex_app",
                     "output": {"text": "<codex_delegation>\n  <source_thread_id>real-caller</source_thread_id>\n"
                                        f"  <input>{arguments['prompt']}</input>\n</codex_delegation>", "truncated": False}}
                    if self.native else {"type": "userMessage", "content": [{"type": "text", "text": arguments["prompt"]}]})
            self.turns.append({
                "id": f"turn-{len(self.turns)}", "status": "inProgress", "startedAt": 100,
                "items": [item],
            })
            self.active = True
            if self.send_error:
                raise HostWakeError(self.send_error, "reply lost")
            return {"threadId": "original-thread"}
        raise AssertionError(name)

    def close(self) -> None:
        pass


def setup_provider(tmp_path: Path, *, native: bool = False) -> tuple[CodexDesktopProvider, DesktopHost, HostWakeRequest]:
    host = DesktopHost(native=native)
    store = PrivateBindingStore(tmp_path / "binding.json")
    provider = CodexDesktopProvider(store, client_factory=lambda _: host)
    binding = provider.register_binding(
        agent_id="worker", binding_id="binding", adapter_profile="codex",
        cwd=tmp_path, scope_digest="scope", policy_digest="policy", endpoint="private-endpoint",
        thread_id="original-thread", caller_thread_id="real-caller", attach_confirmed=True,
    )
    return provider, host, HostWakeRequest("wake-1", "worker", "message-1", "project", binding)


def test_native_exchange_frames_and_checks_correlation(monkeypatch: pytest.MonkeyPatch) -> None:
    import tsunagou.hostwake.codex_desktop as module

    sent: list[bytes] = []

    class Writer:
        def write(self, raw: bytes) -> None:
            sent.append(raw)

        async def drain(self) -> None:
            pass

        def close(self) -> None:
            pass

        async def wait_closed(self) -> None:
            pass

    async def connect(_: str) -> tuple[asyncio.StreamReader, Writer]:
        reader = asyncio.StreamReader()
        payload = json.dumps({"id": 7, "result": {"ok": True}}).encode()
        reader.feed_data(struct.pack("<I", len(payload)) + payload)
        reader.feed_eof()
        return reader, Writer()

    # Exercise real framing without requiring a host on a CI machine.
    monkeypatch.setattr(module, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(asyncio, "open_unix_connection", connect, raising=False)
    client = NativeAppToolsClient("test-socket", "caller")
    assert asyncio.run(client._exchange(b"request", 7)) == {"ok": True}
    assert sent == [struct.pack("<I", 7) + b"request"]
    with pytest.raises(ValueError, match="identity"):
        asyncio.run(client._exchange(b"request", 8))


def test_tool_fallback_ids_are_not_active_turn_claims(monkeypatch: pytest.MonkeyPatch) -> None:
    client = NativeAppToolsClient("private", "actual-caller")
    calls = []

    def reply(method: str, params: dict) -> dict:
        calls.append((method, params))
        return {"success": True, "contentItems": [{"type": "inputText", "text": '{"ok":true}'}]}

    monkeypatch.setattr(client, "request", reply)
    assert client.call_tool("read_thread", {"threadId": "target"}) == {"ok": True}
    params = calls[0][1]
    assert params["threadId"] == "actual-caller"
    assert params["turnId"].startswith("mcp-turn-")
    assert params["callId"].startswith("mcp-call-")


@pytest.mark.parametrize("native", [False, True])
def test_original_thread_accept_start_complete_are_distinct(tmp_path: Path, native: bool) -> None:
    provider, host, request = setup_provider(tmp_path, native=native)
    accepted = provider.wake(request)
    assert accepted.state == "starting"
    assert [e.kind for e in accepted.evidence] == ["host_accepted"]
    assert provider.wake(request) == accepted
    running = provider.poll(request.wake_attempt_id)
    assert running.state == "running"
    assert running.turn_id_digest
    host.turns[0].update(status="completed", completedAt=102)
    host.active = False
    completed = provider.poll(request.wake_attempt_id)
    assert completed.state == "completed"
    assert [(e.kind, e.details.get("host_started_at"), e.details.get("host_completed_at")) for e in completed.evidence] == [
        ("host_accepted", None, None), ("turn_started", 100, None), ("turn_completed", None, 102),
    ]
    assert provider.poll(request.wake_attempt_id) == completed
    reads = [args for name, args in host.calls if name == "read_thread"]
    assert reads[0]["includeOutputs"] is False
    assert reads[-1]["includeOutputs"] is True
    assert len(host.turns) == 1


def test_busy_waits_without_starting_another_turn(tmp_path: Path) -> None:
    provider, host, request = setup_provider(tmp_path)
    host.active = True
    assert provider.wake(request).state == "queued"
    assert provider.poll(request.wake_attempt_id).state == "queued"
    assert not host.turns
    host.active = False
    assert provider.poll(request.wake_attempt_id).state == "starting"
    assert len(host.turns) == 1


@pytest.mark.parametrize("native", [False, True])
def test_unknown_reply_is_observed_without_resending(tmp_path: Path, native: bool) -> None:
    provider, host, request = setup_provider(tmp_path, native=native)
    host.send_error = "desktop_request_timeout"
    assert provider.wake(request).state == "unknown"
    assert provider.poll(request.wake_attempt_id).state == "running"
    assert len(host.turns) == 1


def test_connection_loss_before_send_stays_queued_until_reconnected(tmp_path: Path) -> None:
    provider, host, request = setup_provider(tmp_path)
    host.read_error = "desktop_connection_lost"
    assert provider.wake(request).state == "queued"
    assert not host.turns
    host.read_error = None
    assert provider.poll(request.wake_attempt_id).state == "starting"
    assert len(host.turns) == 1


@pytest.mark.parametrize("native", [False, True])
def test_restart_observes_original_turn_and_refresh_cannot_change_target(tmp_path: Path, native: bool) -> None:
    provider, host, request = setup_provider(tmp_path, native=native)
    provider.wake(request)
    restored = CodexDesktopProvider(provider.store, client_factory=lambda _: host)
    restored.restore_attempt(request, "starting")
    assert restored.poll(request.wake_attempt_id).state == "running"
    with pytest.raises(HostWakeError, match="identity"):
        restored.refresh_binding("worker", {"provider": "codex_desktop_app", "thread_id": "other"}, connection_epoch=2)
    restored.refresh_binding("worker", {"provider": "codex_desktop_app", "endpoint": "new-private",
                                        "host_generation": "new"}, connection_epoch=2)
    assert restored.poll(request.wake_attempt_id).state == "running"
    assert len(host.turns) == 1
    ref, record = restored.store.get("worker")
    assert ref.binding_revision == 2
    assert record["thread_id"] == "original-thread"


def test_dispatcher_batches_busy_messages_and_records_failures(tmp_path: Path) -> None:
    provider, host, request = setup_provider(tmp_path)
    host.active = True
    dispatcher = WakeDispatcher(provider, attempts_path=tmp_path / "attempts.json", diagnostics_path=tmp_path / "diagnostics.json")
    try:
        first = dispatcher.on_delivery(message_id="a", recipient_agent_id="worker", project_id="project")
        second = dispatcher.on_delivery(message_id="b", recipient_agent_id="worker", project_id="project")
        assert first["state"] == second["state"] == "queued"
        assert first["wake_attempt_id"] == second["wake_attempt_id"]
        assert not host.turns
        assert second["coalesced_into"] == "worker:a"
    finally:
        dispatcher.stop()


def test_no_raw_host_context_in_dispatcher_records(tmp_path: Path) -> None:
    provider, host, _ = setup_provider(tmp_path)
    host.send_error = "desktop_tool_rejected"
    dispatcher = WakeDispatcher(provider, attempts_path=tmp_path / "attempts.json", diagnostics_path=tmp_path / "diagnostics.json")
    try:
        result = dispatcher.on_delivery(message_id="a", recipient_agent_id="worker", project_id="project")
        assert result["state"] == "failed"
        assert any(e["kind"] == "wake_failed" for e in dispatcher.diagnostics())
        output = (tmp_path / "attempts.json").read_text() + (tmp_path / "diagnostics.json").read_text()
        assert "original-thread" not in output and "private-endpoint" not in output and "real-caller" not in output
    finally:
        dispatcher.stop()


@pytest.mark.parametrize("status,state", [("completed", "completed"), ("failed", "failed"), ("interrupted", "failed")])
def test_native_finished_turn_has_original_times_when_first_observed(tmp_path: Path, status: str, state: str) -> None:
    provider, host, request = setup_provider(tmp_path, native=True)
    provider.wake(request)
    host.active = False
    host.turns[0].update(status=status, startedAt=1790602533, completedAt=1790602621)
    result = provider.poll(request.wake_attempt_id)
    assert result.state == state
    assert result.evidence[-2].kind == "turn_started"
    assert result.evidence[-2].details["host_started_at"] == 1790602533
    assert result.evidence[-1].details["host_completed_at"] == 1790602621
    assert result.turn_id_digest
    assert len(host.turns) == 1


@pytest.mark.parametrize("false_source", [
    "assistant", "other_tool", "other_namespace", "outside_input", "quoted_user", "wrong_marker", "truncated", "not_delegation",
])
def test_marker_in_reply_or_unrelated_output_is_not_a_wake(tmp_path: Path, false_source: str) -> None:
    provider, host, request = setup_provider(tmp_path, native=True)
    provider.wake(request)
    marker = provider._marker(request.wake_attempt_id)
    item = host.turns[0]["items"][0]
    if false_source == "assistant":
        item = {"type": "agentMessage", "text": f"{marker} I received the wake."}
    elif false_source == "other_tool":
        item["name"] = "read_thread"
    elif false_source == "other_namespace":
        item["namespace"] = "unrelated"
    elif false_source == "outside_input":
        item["output"]["text"] = f"<codex_delegation>{marker}<input>unrelated user follow-up</input></codex_delegation>"
    elif false_source == "quoted_user":
        item = {"type": "userMessage", "content": [{"type": "text", "text": f"Quoted earlier: {marker} read inbox"}]}
    elif false_source == "wrong_marker":
        item["output"]["text"] = item["output"]["text"].replace(marker, f"[Tsunagou wake {request.wake_attempt_id}-other]")
    elif false_source == "truncated":
        item["output"]["truncated"] = True
    else:
        item["output"]["text"] = f"{marker} tool output quoting a wake"
    host.turns[0]["items"] = [item]
    host.turns[0].update(status="completed", completedAt=102)
    host.active = False
    result = provider.poll(request.wake_attempt_id)
    assert result.state == "starting"
    assert not result.turn_id_digest
    assert [e.kind for e in result.evidence] == ["host_accepted"]
    assert len(host.turns) == 1
