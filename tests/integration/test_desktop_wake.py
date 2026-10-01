"""Actual SQLite/command/outbox integration; Desktop RPC is the test boundary.

The real Desktop experiments are recorded separately and are not claimed by
these fixtures. Both public message transports must commit the same outbox.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi import Response
from tests.integration.test_m1_runtime_flow import _baseline, _endpoint
from tests.unit.test_codex_desktop import DesktopHost

from tsunagou.api.app import CommandRequest
from tsunagou.bootstrap.container import build_application
from tsunagou.modules.projects import ProjectRegistry
from tsunagou.shared_kernel.ids import new_id

# These tests are about delivery mechanics, not about payloads, so they carry a kind that
# is wake-worthy by contract: only "someone is blocked until you act" stages a wake at all.
# Plain notice traffic — which must never ring — has its own test below.
WAKE_WORTHY = "task.assigned"


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    registry = ProjectRegistry.initialize(tmp_path, name="desktop", objective="message delivery")
    # Automatic wake is opt-in at the project level, exactly like the switch
    # ``project.configure`` writes. These tests are about delivery mechanics, so they say
    # yes explicitly instead of relying on an implicit default.
    registry.configure(policy_patch={"auto_wake_multi_agent": True}, reason="wake delivery tests")
    monkeypatch.setenv("TSUNAGOU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("TSUNAGOU_STATE_DIR", str(tmp_path / ".tsunagou" / "local"))
    monkeypatch.setenv("TSUNAGOU_CONTROL_TOKEN", "test-control")
    monkeypatch.setenv("TSUNAGOU_HOST_WAKE", "auto")
    app = build_application()
    endpoint = _endpoint(app)
    registry = json.loads((Path(__file__).parents[2] / "protocol/registry/commands.json").read_text(encoding="utf-8"))

    def call(kind: str, payload: dict, who: dict | None = None, *, token: str | None = None, command_id: str | None = None):
        return endpoint(kind, CommandRequest(
            command_id=command_id or new_id(), protocol_version="1.0", schema_bundle_digest=registry["schema_bundle_digest"],
            payload=payload,
        ), Response(), f"Bearer {token or (who['secret_token'] if who else 'test-control')}",
                        who["session_id"] if who else None, who["connection_epoch"] if who else None)["result"]

    def enroll(name: str):
        ticket = call("agent.ticket.create.user", {"kind": "worker", "installation_id": name,
                                                  "conversation_evidence": {"conversation_id": name}})
        return call("agent.enroll", {"installation_id": name, "conversation_evidence": {"conversation_id": name},
                                     "probe_payload": _baseline()}, token=ticket["secret"])

    sender, receiver = enroll("sender"), enroll("receiver")
    host = DesktopHost()
    app.state.hostwake_provider.native.client_factory = lambda _: host
    app.state.hostwake_provider.register_binding(
        provider="codex_desktop_app", agent_id=receiver["agent_id"], binding_id="binding",
        adapter_profile="codex", cwd=tmp_path, scope_digest="scope", policy_digest="policy",
        endpoint="endpoint-private-sentinel", thread_id="original-thread", attach_confirmed=True,
    )
    try:
        yield app, call, sender, receiver, host
    finally:
        app.state.host_delivery.stop()
        app.state.project_database.release_process_lock()


def drain(app: Any) -> None:
    worker = app.state.host_delivery
    worker.run_once()
    deadline = time.monotonic() + 5
    while worker._pending and time.monotonic() < deadline:
        time.sleep(0.01)
        worker.run_once()
    assert not worker._pending


def test_user_ticket_binds_the_redeeming_conversation_automatically(runtime):
    app, call, sender, receiver, host = runtime
    original = "user-selected-original-thread"
    ticket = call("agent.ticket.create.user", {
        "kind": "worker", "installation_id": "codex:desktop",
        "conversation_evidence": {"conversation_id": original},
        "host_binding": {"provider": "codex_desktop_app", "endpoint": "onboarding-pipe-private",
                         "thread_id": original, "host_generation": "generation"},
    })
    payload = {"installation_id": "codex:desktop", "conversation_evidence": {"conversation_id": original},
               "probe_payload": _baseline()}
    command_id = new_id()
    receipt = call("agent.enroll", payload, token=ticket["secret"], command_id=command_id)
    item = app.state.hostwake_provider.native.store.get(receipt["agent_id"])
    assert item and item[1]["thread_id"] == original and item[1]["endpoint"] == "onboarding-pipe-private"
    assert item[0].connection_epoch == receipt["connection_epoch"]
    assert call("agent.enroll", payload, token=ticket["secret"], command_id=command_id) == receipt
    assert app.state.hostwake_provider.native.store.get(receipt["agent_id"])[0] == item[0]
    refreshed = call("session.reconnect", {
        "reconnect_nonce": receipt["reconnect_nonce"], "expected_connection_epoch": receipt["connection_epoch"],
        "host_binding_refresh": {"provider": "codex_desktop_app", "endpoint": "new-private-pipe", "host_generation": "next"},
    }, receipt)
    call("agent.enroll", payload, token=ticket["secret"], command_id=command_id)
    latest = app.state.hostwake_provider.native.store.get(receipt["agent_id"])
    assert latest[0].connection_epoch == refreshed["connection_epoch"] and latest[1]["endpoint"] == "new-private-pipe"
    with contextlib.closing(app.state.project_database._connect()) as conn:
        public_events = json.dumps([tuple(row) for row in conn.execute("SELECT payload_json FROM events")])
        assert original not in public_events and "onboarding-pipe-private" not in public_events


def test_enrollment_binding_cannot_name_a_different_thread(runtime):
    from fastapi import HTTPException

    app, call, sender, receiver, host = runtime
    before = app.state.state_runtime.capture()
    with pytest.raises(HTTPException) as exc:
        call("agent.ticket.create.user", {
            "kind": "worker", "installation_id": "codex:desktop", "conversation_evidence": {"conversation_id": "one"},
            "host_binding": {"provider": "codex_desktop_app", "endpoint": "private", "thread_id": "two", "host_generation": "g"},
        })
    assert exc.value.detail["code"] == "enrollment_host_binding_invalid"
    assert app.state.state_runtime.capture() == before


@pytest.mark.parametrize("transport", ["command", "a2a"])
def test_messages_commit_outbox_once_and_resume_delivery(runtime, transport: str) -> None:
    app, call, sender, receiver, host = runtime
    identity = new_id()
    if transport == "command":
        def send():
            return call("message.send", {
                "recipient_agent_id": receiver["agent_id"], "kind": WAKE_WORTHY, "subject_ref": "project",
                "summary": "private body sentinel", "payload": {},
            }, sender, command_id=identity)
    else:
        def send():
            result = app.state.a2a_gateway.dispatch({
                "jsonrpc": "2.0", "id": 1, "method": "message/send",
                "params": {"message": {
                    "messageId": identity, "role": "user", "parts": [{"text": "private body sentinel"}],
                    "metadata": {"tsunagou": {"kind": WAKE_WORTHY}},
                }},
            }, authorization=f"Bearer {sender['secret_token']}", session_id=sender["session_id"],
               connection_epoch=sender["connection_epoch"], recipient_agent_id=receiver["agent_id"])
            assert "result" in result, result
            return result
    send()
    send()
    db = app.state.project_database
    with contextlib.closing(db._connect()) as conn:
        rows = conn.execute("SELECT * FROM outbox WHERE kind='host_wake'").fetchall()
        assert len(rows) == 1
        event_count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    # This is the same drain invoked on startup; command-transport messages
    # need no A2A callback or extra user turn in order to reach the provider.
    drain(app)
    assert len(host.turns) == 1
    assert "private body sentinel" not in host.calls[-1][1].get("prompt", "")
    with contextlib.closing(db._connect()) as conn:
        assert conn.execute("SELECT status FROM outbox WHERE kind='host_wake'").fetchone()[0] == "done"
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == event_count


def test_pull_only_notice_never_costs_a_host_turn(runtime) -> None:
    """Nothing is blocked, so nothing rings — but the message is still delivered."""
    app, call, sender, receiver, host = runtime
    message = call("message.send", {"recipient_agent_id": receiver["agent_id"], "kind": "notice",
                                    "subject_ref": "project", "summary": "no action required", "payload": {}}, sender)
    with contextlib.closing(app.state.project_database._connect()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM outbox WHERE kind='host_wake'").fetchone()[0] == 0
    drain(app)
    assert not host.turns and not host.calls
    runtime_state = app.state.state_runtime
    assert [item.message_id for item in runtime_state.messages.waiting(receiver["agent_id"])] == [message["message_id"]]
    # Peeking is not claiming: the delivery is still there for the real reader.
    call("inbox.claim", {"limit": 20}, receiver)
    assert runtime_state.messages.waiting(receiver["agent_id"]) == []


def test_reconnect_refresh_is_own_binding_only_and_private(runtime) -> None:
    app, call, sender, receiver, _ = runtime
    refresh = {"provider": "codex_desktop_app", "endpoint": "refreshed-private-sentinel", "host_generation": "new"}
    result = call("session.reconnect", {
        "reconnect_nonce": receiver["reconnect_nonce"], "expected_connection_epoch": receiver["connection_epoch"],
        "host_binding_refresh": refresh,
    }, receiver)
    ref, record = app.state.hostwake_provider.store.get(receiver["agent_id"])
    assert ref.connection_epoch == result["connection_epoch"]
    assert record["endpoint"] == "refreshed-private-sentinel"
    assert record["thread_id"] == "original-thread"
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        call("session.reconnect", {
            "reconnect_nonce": sender["reconnect_nonce"], "expected_connection_epoch": sender["connection_epoch"],
            "host_binding_refresh": refresh,
        }, sender)
    with contextlib.closing(app.state.project_database._connect()) as conn:
        public = json.dumps([tuple(r) for r in conn.execute("SELECT payload_json FROM events")])
        public += json.dumps([tuple(r) for r in conn.execute("SELECT payload_json FROM module_state")])
        assert "refreshed-private-sentinel" not in public


def test_busy_notification_does_not_wake_after_current_turn_acked_message(runtime) -> None:
    app, call, sender, receiver, host = runtime
    host.active = True
    message = call("message.send", {
        "recipient_agent_id": receiver["agent_id"], "kind": WAKE_WORTHY, "subject_ref": "project",
        "summary": "Consumed during an existing turn", "payload": {},
    }, sender)
    drain(app)
    dispatcher = app.state.wake_dispatcher
    assert dispatcher.status(message_id=message["message_id"], recipient_agent_id=receiver["agent_id"])["state"] == "queued"
    reader = dispatcher.deliveries_acked

    def without_dispatcher_lock(recipient, identities):
        assert not dispatcher._lock._is_owned(), "SQLite ACK reads must not invert the dispatcher/database lock order"
        return reader(recipient, identities)

    dispatcher.deliveries_acked = without_dispatcher_lock
    call("inbox.claim", {"limit": 20}, receiver)
    call("inbox.presented", {"message_id": message["message_id"], "evidence_kind": "test_turn"}, receiver)
    call("inbox.ack", {"message_id": message["message_id"]}, receiver)
    with contextlib.closing(app.state.project_database._connect()) as conn:
        committed_events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    host.active = False
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        current = dispatcher.status(message_id=message["message_id"], recipient_agent_id=receiver["agent_id"])
        if current["state"] != "queued":
            break
        time.sleep(0.01)
    assert not host.turns, "ACKed queued notification started an unnecessary model turn"
    assert current["state"] == "completed" and current["completion_reason"] == "messages_already_acked"
    assert current.get("turn_id_digest") is None
    assert "wake_skipped" in {item["kind"] for item in current["evidence"]}
    assert not {"host_accepted", "turn_started", "turn_completed"}.intersection(item["kind"] for item in current["evidence"])
    with contextlib.closing(app.state.project_database._connect()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == committed_events


@pytest.mark.parametrize("acked", [0, 1, 2])
def test_coalesced_notification_checks_every_recipient_delivery(runtime, acked: int) -> None:
    app, call, sender, receiver, host = runtime
    host.active = True
    identities = []
    for number in range(2):
        message = call("message.send", {"recipient_agent_id": receiver["agent_id"], "kind": WAKE_WORTHY,
                                       "subject_ref": "project", "summary": f"batch {number}", "payload": {}}, sender)
        identities.append(message["message_id"])
        drain(app)
    dispatcher = app.state.wake_dispatcher
    statuses = [dispatcher.status(message_id=identity, recipient_agent_id=receiver["agent_id"]) for identity in identities]
    assert statuses[0]["wake_attempt_id"] == statuses[1]["wake_attempt_id"]
    call("inbox.claim", {"limit": 20}, receiver)
    for index, identity in enumerate(identities):
        call("inbox.presented", {"message_id": identity, "evidence_kind": "test_turn"}, receiver)
        if index < acked:
            call("inbox.ack", {"message_id": identity}, receiver)
    # Reading/presentation alone must not suppress a still-pending delivery.
    host.active = False
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        statuses = [dispatcher.status(message_id=identity, recipient_agent_id=receiver["agent_id"]) for identity in identities]
        if statuses[0]["state"] != "queued":
            break
        time.sleep(0.01)
    if acked == 2:
        assert not host.turns
        assert all(item["completion_reason"] == "messages_already_acked" for item in statuses)
        events = dispatcher.diagnostics()
        assert {event["message_id"] for event in events if event["kind"] == "wake_completed"
                and event["details"].get("completion_reason") == "messages_already_acked"} == set(identities)
        assert not any(event["kind"] == "turn_completed" for event in events)
    else:
        assert len(host.turns) == 1
        assert all(not item.get("completion_reason") for item in statuses)


def test_already_acked_outbox_never_dispatches_and_reader_checks_recipient(runtime) -> None:
    app, call, sender, receiver, host = runtime
    message = call("message.send", {"recipient_agent_id": receiver["agent_id"], "kind": WAKE_WORTHY, "subject_ref": "project",
                                   "summary": "processed before outbox", "payload": {}}, sender)
    identity = message["message_id"]
    call("inbox.claim", {"limit": 20}, receiver)
    call("inbox.presented", {"message_id": identity, "evidence_kind": "test_turn"}, receiver)
    call("inbox.ack", {"message_id": identity}, receiver)
    reader = app.state.host_delivery._deliveries_acked
    assert reader(receiver["agent_id"], (identity,))
    assert not reader(sender["agent_id"], (identity,))
    assert not reader(receiver["agent_id"], (identity, "missing"))
    drain(app)
    assert not host.turns and not host.calls
    state = app.state.wake_dispatcher.status(message_id=identity, recipient_agent_id=receiver["agent_id"])
    assert state["completion_reason"] == "messages_already_acked"


@pytest.mark.parametrize("lost_reply", [False, True])
def test_ack_does_not_finish_an_accepted_or_unknown_host_turn(runtime, lost_reply: bool) -> None:
    app, call, sender, receiver, host = runtime
    host.send_error = "desktop_request_timeout" if lost_reply else None
    message = call("message.send", {"recipient_agent_id": receiver["agent_id"], "kind": WAKE_WORTHY, "subject_ref": "project",
                                   "summary": "host turn already requested", "payload": {}}, sender)
    drain(app)
    if lost_reply:
        # No matching original turn is observable yet: it must stay unknown.
        host.turns[0]["items"] = []
    call("inbox.claim", {"limit": 20}, receiver)
    call("inbox.presented", {"message_id": message["message_id"], "evidence_kind": "test_turn"}, receiver)
    call("inbox.ack", {"message_id": message["message_id"]}, receiver)
    time.sleep(0.65)
    state = app.state.wake_dispatcher.status(message_id=message["message_id"], recipient_agent_id=receiver["agent_id"])
    assert state["state"] == ("unknown" if lost_reply else "running")
    assert not state.get("completion_reason")
    assert not any(item["kind"] in {"wake_skipped", "turn_completed"} for item in state["evidence"])
    assert len(host.turns) == 1


def test_restarted_queued_batch_reads_persisted_ack_without_host_call(runtime) -> None:
    from tsunagou.hostwake import CodexDesktopProvider, WakeDispatcher
    from tsunagou.platform.host_delivery import HostDeliveryWorker

    app, call, sender, receiver, host = runtime
    host.active = True
    message = call("message.send", {"recipient_agent_id": receiver["agent_id"], "kind": WAKE_WORTHY, "subject_ref": "project",
                                   "summary": "read before restart", "payload": {}}, sender)
    drain(app)
    original = app.state.wake_dispatcher
    app.state.host_delivery.stop()
    call("inbox.claim", {"limit": 20}, receiver)
    call("inbox.presented", {"message_id": message["message_id"], "evidence_kind": "test_turn"}, receiver)
    call("inbox.ack", {"message_id": message["message_id"]}, receiver)
    host.active = False
    before = len(host.calls)
    restored = WakeDispatcher(CodexDesktopProvider(original.provider.store, client_factory=lambda _: host),
                              attempts_path=original.attempts_path, diagnostics_path=original.diagnostics_path)
    worker = HostDeliveryWorker(app.state.project_database, restored)
    try:
        restored.resume_pending()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status = restored.status(message_id=message["message_id"], recipient_agent_id=receiver["agent_id"])
            if status.get("completion_reason"):
                break
            time.sleep(0.01)
        assert status["completion_reason"] == "messages_already_acked"
        assert not host.turns and len(host.calls) == before
    finally:
        worker.stop()


def test_ack_suppression_preserves_previous_host_failure(runtime) -> None:
    app, call, sender, receiver, host = runtime
    provider = app.state.hostwake_provider
    provider.store.update_status(receiver["agent_id"], "stale")
    message = call("message.send", {"recipient_agent_id": receiver["agent_id"], "kind": WAKE_WORTHY, "subject_ref": "project",
                                   "summary": "received by manual follow-up", "payload": {}}, sender)
    drain(app)
    dispatcher = app.state.wake_dispatcher
    first = dispatcher.status(message_id=message["message_id"], recipient_agent_id=receiver["agent_id"])
    assert first["state"] == "failed" and first["error_code"] == "host_binding_not_ready"
    call("inbox.claim", {"limit": 20}, receiver)
    call("inbox.presented", {"message_id": message["message_id"], "evidence_kind": "test_turn"}, receiver)
    call("inbox.ack", {"message_id": message["message_id"]}, receiver)
    provider.store.update_status(receiver["agent_id"], "ready")
    later = dispatcher.on_delivery(message_id=message["message_id"], recipient_agent_id=receiver["agent_id"],
                                   project_id=app.state.project_database.project_id)
    assert later["completion_reason"] == "messages_already_acked"
    assert later["previous_attempts"][0]["state"] == "failed"
    assert later["previous_attempts"][0]["wake_attempt_id"] == first["wake_attempt_id"]
    events = dispatcher.diagnostics()
    assert any(event["kind"] == "wake_failed" and event["wake_attempt_id"] == first["wake_attempt_id"] for event in events)
    assert not any(event["kind"] == "turn_completed" for event in events)
    assert not host.turns


def test_the_project_switch_really_controls_automatic_wake(runtime) -> None:
    """The switch advertised to Main has to do something, and must not lose work.

    Off means nothing is dispatched; the staged row waits. Turning it back on delivers
    what accumulated, because the row is the intent to wake rather than a one-shot nudge.
    """
    app, call, sender, receiver, host = runtime
    registry = app.state.project_registry
    registry.configure(policy_patch={"auto_wake_multi_agent": False}, reason="deliver without ringing")
    call("message.send", {"recipient_agent_id": receiver["agent_id"], "kind": WAKE_WORTHY,
                          "subject_ref": "task/task-1", "summary": "work is waiting", "payload": {}}, sender)
    drain(app)
    assert not host.turns and not host.calls
    with contextlib.closing(app.state.project_database._connect()) as conn:
        assert conn.execute("SELECT status FROM outbox WHERE kind='host_wake'").fetchone()[0] == "pending"
    registry.configure(policy_patch={"auto_wake_multi_agent": True}, reason="ring again")
    drain(app)
    assert len(host.turns) == 1


def test_an_unwakeable_host_ends_the_delivery_instead_of_retrying(runtime) -> None:
    """Desktop holding the writer is a fact, not a transient outage.

    The attempt ends with the reason on record, the binding is marked degraded so the
    judgement is visible, and the outbox row is finished rather than retried behind a call
    that cannot succeed.
    """
    app, call, sender, receiver, host = runtime
    host.read_error = "desktop_thread_unavailable"
    message = call("message.send", {"recipient_agent_id": receiver["agent_id"], "kind": WAKE_WORTHY,
                                    "subject_ref": "project", "summary": "blocked until you act", "payload": {}}, sender)
    drain(app)
    attempt = app.state.wake_dispatcher.status(message_id=message["message_id"], recipient_agent_id=receiver["agent_id"])
    assert attempt["state"] == "failed" and attempt["error_code"] == "desktop_thread_unavailable"
    assert app.state.hostwake_provider.native.store.get(receiver["agent_id"])[0].status == "degraded"
    with contextlib.closing(app.state.project_database._connect()) as conn:
        row = conn.execute("SELECT status,attempt_count FROM outbox WHERE kind='host_wake'").fetchone()
    assert tuple(row) == ("done", 1)
    assert any(item["kind"] == "wake_failed" for item in app.state.wake_dispatcher.diagnostics())


def test_a2a_reports_staging_without_running_a_host_turn_inline(runtime) -> None:
    """One message must not be reachable through two wake paths with two retry rules."""
    app, call, sender, receiver, host = runtime
    response = app.state.a2a_gateway.dispatch({
        "jsonrpc": "2.0", "id": 1, "method": "message/send",
        "params": {"message": {
            "messageId": "external-1", "role": "user", "parts": [{"text": "private body sentinel"}],
            "metadata": {"tsunagou": {"kind": WAKE_WORTHY}},
        }},
    }, authorization=f"Bearer {sender['secret_token']}", session_id=sender["session_id"],
       connection_epoch=sender["connection_epoch"], recipient_agent_id=receiver["agent_id"])
    host_wake = response["result"]["message"]["metadata"]["tsunagou"]["host_wake"]
    assert host_wake["status"] == "staged"
    # Nothing has touched the host yet: the durable outbox row is the only wake path.
    assert not host.turns and not host.calls
    drain(app)
    assert len(host.turns) == 1
