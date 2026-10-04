"""Synthetic Agent identities with real private routes; no live enrollment evidence."""

from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest

from tsunagou.application.wake_assistance import WakeAssistance
from tsunagou.hostwake.dispatcher import WakeDispatcher
from tsunagou.interfaces.runtime import CommandDispatcher, PrincipalContext
from tsunagou.modules.authority import AuthorityService
from tsunagou.modules.messaging import MessageStore
from tsunagou.platform.db.sqlite import ProjectDatabase
from tsunagou.shared_kernel.baseline import BASELINE_CAPABILITIES


class Fixture:
    def __init__(self, root: Path, hosts: tuple[str, str] = ("codex", "opencode"), *, target_conversation: str | None = None):
        self.root = root
        self.authority = AuthorityService()
        self.messages = MessageStore()
        self.routes = {host: root / "routes" / host for host in ("codex", "opencode", "deepseek")}
        self.agents = []
        self.route_files = []
        for index, host in enumerate(hosts):
            conversation = target_conversation if index == 1 and target_conversation else f"real-fixture-conversation-{index}"
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
            self.route_files.append(route)
        self.calls: list[str] = []
        self.host_state: dict[str, Any] = {"state": "idle", "can_queue": True, "result": "observed", "version": "2.0.18"}
        self.outcome: dict[str, Any] = {"state": "unknown", "result": "queued", "turn_started": False, "evidence": ["fixture:queue"]}
        self.database = ProjectDatabase(root / "state.sqlite3", project_id="project")
        self.native = WakeDispatcher(object())  # type: ignore[arg-type]
        self.service = self.restart()

    def runner(self, action: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(action)
        assert kwargs["conversation_id"] == "real-fixture-conversation-1"
        return dict(self.host_state if action == "status" else self.outcome)

    def restart(self) -> WakeAssistance:
        return WakeAssistance(authority=self.authority, messages=self.messages, project_id="project",
                              project_root=self.root, state_dir=self.root, database=self.database,
                              native=self.native, route_directories=self.routes, runner=self.runner)

    def context(self, index: int = 0) -> dict[str, Any]:
        receipt = self.agents[index]
        return {"principal_id": receipt.agent_id, "session_id": receipt.session_id,
                "connection_epoch": receipt.connection_epoch}

    def message(self, *, required: bool = True, kind: str = "message", command_id: str = "origin") -> str:
        return self.messages.send(command_id=command_id, sender_agent_id=self.agents[0].agent_id,
                                  recipient_agent_id=self.agents[1].agent_id, kind=kind, subject_ref="task/t",
                                  summary="private message body", response_contract={"required": required}).message_id

    def invoke(self, message_id: str, *, wake: bool = False) -> dict[str, Any]:
        return (self.service.wake if wake else self.service.status)({"message_id": message_id}, self.context())


@pytest.mark.parametrize("hosts", [("codex", "opencode"), ("opencode", "opencode"), ("deepseek", "opencode")])
def test_worker_can_wake_peer_with_private_identity_and_separate_progress(tmp_path: Path, hosts: tuple[str, str]) -> None:
    f = Fixture(tmp_path, hosts)
    message = f.message()
    result = f.invoke(message)
    assert result["target"]["host"] == "opencode"
    assert result["sender"]["host"] == hosts[0]
    assert result["response_required"] is True
    assert result["entry"] == {"tool": "coordination__wake", "arguments": {"message_id": message}}
    assert result["progress"] == {"durably_received": True, "host_turn_started": False, "presented": False, "business_response": False}
    result = f.invoke(message, wake=True)
    assert result["result"] == "queued"
    assert result["progress"]["host_turn_started"] is False
    assert f.calls == ["status", "status", "wake"]
    rendered = json.dumps(result)
    assert "real-fixture-conversation" not in rendered
    assert "private message body" not in rendered
    assert f.agents[1].secret_token not in rendered
    assert str(tmp_path) not in rendered


def test_replay_restart_and_native_future_never_double_dispatch(tmp_path: Path) -> None:
    f = Fixture(tmp_path)
    message = f.message()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: f.invoke(message, wake=True), range(4)))
    assert all(result["result"] == "queued" for result in results)
    assert f.calls == ["status", "wake"]
    f.service = f.restart()
    assert f.invoke(message, wake=True)["result"] == "queued"
    # An outbox future may have been scheduled before the reservation was saved.
    native = f.native.on_delivery(message_id=message, recipient_agent_id=f.agents[1].agent_id, project_id="project")
    assert native["error_code"] == "manual_wake_recorded"
    assert f.calls == ["status", "wake"]
    f.invoke(message)
    assert f.calls[-1] == "status"  # explicit status reads always refresh


def test_unknown_outcome_and_process_crash_are_not_retried(tmp_path: Path) -> None:
    f = Fixture(tmp_path)
    message = f.message()
    f.service._save(message, {"result": "starting"})
    f.service = f.restart()
    assert f.invoke(message, wake=True)["result"] == "unknown"
    assert f.calls == []


def test_native_codex_lane_and_active_other_lane_block_fallback(tmp_path: Path) -> None:
    f = Fixture(tmp_path, ("codex", "codex"))
    message = f.message()
    assert f.invoke(message, wake=True)["result"] == "native_channel_only"
    assert f.calls == []
    # Even an unexpected non-Codex native attempt must win over a second driver.
    route = json.loads(f.route_files[1].read_text())
    route["adapter"] = "opencode"
    replacement = f.routes["opencode"] / f.route_files[1].name
    replacement.parent.mkdir(parents=True)
    replacement.write_text(json.dumps(route))
    f.route_files[1].unlink()
    f.native.attempts["other-message"] = {"agent_id": f.agents[1].agent_id, "state": "running"}
    assert f.invoke(message, wake=True)["error_code"] == "native_wake_pending"
    assert f.calls == []


@pytest.mark.parametrize("state,queue,result", [("unknown", "unknown", "observed"), ("running", False, "observed"),
                                               ("unknown", False, "unsupported")])
def test_unknown_busy_or_unsupported_does_not_drive(tmp_path: Path, state: str, queue: Any, result: str) -> None:
    f = Fixture(tmp_path)
    f.host_state.update(state=state, can_queue=queue, result=result)
    observed = f.invoke(f.message(), wake=True)
    assert observed["state"] == state
    assert f.calls == ["status"]


def test_same_request_running_and_presented_are_independent_no_drive_proofs(tmp_path: Path) -> None:
    f = Fixture(tmp_path)
    message = f.message()
    f.host_state.update(state="running", request_associated=True, turn_started=True)
    result = f.invoke(message, wake=True)
    assert result["result"] == "same_request_running"
    assert result["progress"]["host_turn_started"] is True
    assert result["progress"]["presented"] is False
    f.messages.present(f.agents[1].agent_id, message, {"kind": "fixture", "digest": "digest"})
    result = f.invoke(message, wake=True)
    assert result["progress"]["presented"] is True
    assert result["progress"]["business_response"] is False
    assert f.calls == ["status"]


def test_unrelated_message_stale_epoch_and_conflicting_route_fail_closed(tmp_path: Path) -> None:
    f = Fixture(tmp_path)
    message = f.message()
    with pytest.raises(PermissionError, match="wake_message_access_denied"):
        f.service.status({"message_id": message}, f.context(1))
    with pytest.raises(PermissionError, match="stale_connection_epoch"):
        f.service.wake({"message_id": message}, {**f.context(), "connection_epoch": 99})
    route = json.loads(f.route_files[1].read_text())
    route["project_id"] = "foreign"
    f.route_files[1].write_text(json.dumps(route))
    assert f.invoke(message, wake=True)["error_code"] == "host_identity_unverified"
    f.authority.agents[f.agents[1].agent_id].machine = "remote-workstation"
    assert f.invoke(message, wake=True)["error_code"] == "host_identity_unverified"
    assert f.invoke(message)["target"]["machine"] == "unknown"
    assert f.calls == []


def test_external_commands_do_not_hold_database_lock_and_reject_forged_fields(tmp_path: Path) -> None:
    f = Fixture(tmp_path)
    registry = Path(__file__).resolve().parents[2] / "protocol/registry/commands.json"
    dispatcher = CommandDispatcher(registry, database=f.database)
    dispatcher.register("coordination.wake", f.service.wake)
    original_runner = f.service.runner
    def runner(action: str, **kwargs: Any) -> dict[str, Any]:
        entered = threading.Event()
        def other_transaction() -> None:
            with f.database.transaction():
                entered.set()
        thread = threading.Thread(target=other_transaction)
        thread.start()
        assert entered.wait(2), "host I/O held the database lock"
        thread.join()
        assert original_runner is not None
        return original_runner(action, **kwargs)
    f.service.runner = runner
    receipt = f.agents[0]
    principal = PrincipalContext("B", receipt.agent_id, receipt.session_id, receipt.connection_epoch)
    envelope = {"command_id": "wake-1", "protocol_version": "1", "schema_bundle_digest": "sha256:x",
                "payload": {"message_id": f.message()}}
    assert dispatcher.dispatch("coordination.wake", envelope, principal=principal).result["result"] == "queued"
    envelope["payload"]["sender_agent_id"] = receipt.agent_id  # type: ignore[index]
    with pytest.raises(ValueError, match="unknown_payload_field"):
        dispatcher.dispatch("coordination.wake", envelope, principal=principal)


@pytest.mark.parametrize("main_index", [0, 1, None])
def test_main_worker_matrix_uses_same_sender_permission(tmp_path: Path, main_index: int | None) -> None:
    f = Fixture(tmp_path, ("opencode", "opencode"))
    if main_index is not None:
        f.authority.appoint_main(actor_kind="user_control", agent_id=f.agents[main_index].agent_id)
    assert f.invoke(f.message(), wake=True)["result"] == "queued"
    assert f.calls == ["status", "wake"]


def test_identity_refresh_after_status_revalidates_before_dispatch(tmp_path: Path) -> None:
    f = Fixture(tmp_path)
    message = f.message()
    f.authority.sessions[f.agents[1].session_id].connection_epoch += 1
    assert f.invoke(message, wake=True)["error_code"] == "host_identity_unverified"
    assert f.calls == []
    session_file = tmp_path / "session-1.json"
    private = json.loads(session_file.read_text())
    private["connection_epoch"] += 1
    session_file.write_text(json.dumps(private))
    assert f.invoke(message)["target"]["host"] == "opencode"
    original = f.service.runner
    def change_identity(action: str, **kwargs: Any) -> dict[str, Any]:
        assert original is not None
        result = original(action, **kwargs)
        if action == "status":
            f.authority.sessions[f.agents[1].session_id].connection_epoch += 1
        return result
    f.service.runner = change_identity
    assert f.invoke(message, wake=True)["error_code"] == "host_identity_changed"
    assert "wake" not in f.calls


def test_associated_queue_is_not_a_same_request_active_turn(tmp_path: Path) -> None:
    f = Fixture(tmp_path)
    f.host_state.update(state="running", result="queued", request_associated=True, turn_started=False)
    result = f.invoke(f.message(), wake=True)
    assert result["result"] == "queued"
    assert result["progress"]["host_turn_started"] is False
    assert f.calls == ["status"]


def test_uncertain_then_fresh_idle_observation_still_does_not_redrive(tmp_path: Path) -> None:
    f = Fixture(tmp_path)
    f.outcome.update(state="unknown", result="unknown", error_code="timeout")
    message = f.message()
    assert f.invoke(message, wake=True)["result"] == "unknown"
    observed = f.invoke(message)
    assert observed["state"] == "idle"
    assert observed["prior_result"] == "unknown"
    assert observed["retry_allowed"] is False
    assert observed["entry"]["tool"] == "coordination__wake_status"
    assert f.invoke(message, wake=True)["result"] == "unknown"
    assert f.calls.count("wake") == 1


def test_corrupt_journal_cannot_forget_an_accepted_request(tmp_path: Path) -> None:
    f = Fixture(tmp_path)
    f.invoke(f.message(), wake=True)
    f.service.path.write_text("broken")
    with pytest.raises(RuntimeError, match="host_assistance_journal_invalid"):
        f.restart()


def test_candidates_need_original_authenticated_command_and_response_contract(tmp_path: Path) -> None:
    f = Fixture(tmp_path)
    message = f.message(command_id="submit-id:submitted", kind="task.submitted", required=False)
    with pytest.raises(PermissionError, match="wake_message_access_denied"):
        f.service.candidates({"source_command_id": "submit-id"}, f.context())
    f.database.dispatch(principal_id=f.agents[0].agent_id, command_kind="task.submit", command_id="submit-id",
                        payload={}, handler=lambda _: {})
    assert f.service.candidates({"source_command_id": "submit-id"}, f.context())["messages"] == [{
        "message_id": message, "recipient_agent_id": f.agents[1].agent_id, "kind": "task.submitted", "response_required": False,
    }]
    f.message(command_id="submit-id:ordinary", kind="notice", required=False)
    assert len(f.service.candidates({"source_command_id": "submit-id"}, f.context())["messages"]) == 1
    with pytest.raises(PermissionError, match="wake_message_access_denied"):
        f.service.candidates({"source_command_id": "submit-id"}, f.context(1))


def test_native_future_scheduled_before_manual_reservation_waits_then_skips(tmp_path: Path) -> None:
    f = Fixture(tmp_path)
    message = f.message()
    entered = threading.Event()
    release = threading.Event()
    original = f.service.runner
    def paused(action: str, **kwargs: Any) -> dict[str, Any]:
        if action == "wake":
            entered.set()
            assert release.wait(2)
        assert original is not None
        return original(action, **kwargs)
    f.service.runner = paused
    with ThreadPoolExecutor(max_workers=2) as pool:
        manual = pool.submit(f.invoke, message, wake=True)
        assert entered.wait(2)
        native = pool.submit(f.native.on_delivery, message_id=message,
                             recipient_agent_id=f.agents[1].agent_id, project_id="project")
        assert not native.done()
        release.set()
        assert manual.result()["result"] == "queued"
        assert native.result()["error_code"] == "manual_wake_recorded"
    assert f.calls == ["status", "wake"]


def test_pending_codex_intent_preserved_and_non_codex_intent_fenced(tmp_path: Path) -> None:
    f = Fixture(tmp_path, ("opencode", "codex"))
    message = f.message(kind="task.assigned")
    with f.database.transaction("origin") as uow:
        uow.append_event(lineage_id="lineage", event_type="message.created", aggregate_ref=f"message/{message}",
                         actor_ref=f.agents[0].agent_id, payload={})
        uow.stage_outbox(kind="host_wake", target_ref=f"message/{message}", payload={})
    assert f.invoke(message, wake=True)["error_code"] == "native_wake_pending"
    with f.database._connect() as conn:
        assert conn.execute("SELECT status FROM outbox").fetchone()[0] == "pending"
    route = json.loads(f.route_files[1].read_text())
    route["adapter"] = "opencode"
    new_route = f.routes["opencode"] / f.route_files[1].name
    new_route.write_text(json.dumps(route))
    f.route_files[1].unlink()
    assert f.invoke(message, wake=True)["result"] == "queued"
    with f.database._connect() as conn:
        assert conn.execute("SELECT status FROM outbox").fetchone()[0] == "done"
    assert f.service.native_fence(message) is not None


def test_system_notification_requires_durable_originating_actor(tmp_path: Path) -> None:
    f = Fixture(tmp_path)
    message = f.messages.send(command_id="system", sender_agent_id="system", recipient_agent_id=f.agents[1].agent_id,
                              kind="task.assigned", subject_ref="task/t", summary="system notice").message_id
    with pytest.raises(PermissionError, match="wake_message_access_denied"):
        f.invoke(message)
    with f.database.transaction("origin") as uow:
        uow.append_event(lineage_id="lineage", event_type="message.created", aggregate_ref=f"message/{message}",
                         actor_ref=f.agents[0].agent_id, payload={})
        uow.stage_outbox(kind="host_wake", target_ref=f"message/{message}", payload={})
    assert f.invoke(message)["target"]["host"] == "opencode"
    with pytest.raises(PermissionError, match="wake_message_access_denied"):
        f.service.status({"message_id": message}, f.context(1))


@pytest.mark.parametrize("invalid", ["degraded", "revoked", "replay_only"])
def test_external_dispatch_rechecks_ready_grant_and_disallows_replay_only(tmp_path: Path, invalid: str) -> None:
    f = Fixture(tmp_path)
    message = f.message()
    registry = Path(__file__).resolve().parents[2] / "protocol/registry/commands.json"
    dispatcher = CommandDispatcher(registry, database=f.database)
    dispatcher.register("coordination.wake", f.service.wake)
    receipt = f.agents[0]
    if invalid == "degraded":
        f.authority.sessions[receipt.session_id].status = "degraded"
    if invalid == "revoked":
        for grant_id, grant in list(f.authority.grants.items()):
            if grant.principal_id == receipt.agent_id:
                f.authority.grants[grant_id] = replace(grant, status="revoked")
    principal = PrincipalContext("B", receipt.agent_id, receipt.session_id, receipt.connection_epoch,
                                 replay_only=invalid == "replay_only")
    with pytest.raises(PermissionError):
        dispatcher.dispatch("coordination.wake", {
            "command_id": "wake-1", "protocol_version": "1", "schema_bundle_digest": "sha256:x",
            "payload": {"message_id": message},
        }, principal=principal)
    assert f.calls == []


def test_uncommitted_message_rolled_back_cannot_trigger_host_io(tmp_path: Path) -> None:
    f = Fixture(tmp_path)
    staged = threading.Event()
    caller_started = threading.Event()
    release = threading.Event()
    message_ids = []
    def rollback_command() -> None:
        with f.database.lock:
            message = f.message()
            message_ids.append(message)
            staged.set()
            assert release.wait(2)
            del f.messages.messages[message]
            del f.messages.deliveries[message]
    def wake() -> None:
        caller_started.set()
        with pytest.raises(PermissionError, match="wake_message_access_denied"):
            f.invoke(message_ids[0], wake=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        transaction = pool.submit(rollback_command)
        assert staged.wait(2)
        external = pool.submit(wake)
        assert caller_started.wait(2)
        assert not external.done()
        release.set()
        transaction.result()
        external.result()
    assert f.calls == []


def test_native_status_distinguishes_policy_route_and_observed_turn(tmp_path: Path) -> None:
    f = Fixture(tmp_path, ("codex", "codex"))
    message = f.message()
    f.service.native_policy = lambda: True
    result = f.invoke(message)
    assert result["native"]["enabled"] is True
    assert result["native"]["attempt_state"] is None
    assert result["progress"]["host_turn_started"] is None
    assert result["evidence"] == []
    assert result["error_code"] is None
    with f.database.transaction("native-test") as uow:
        uow.append_event(lineage_id="lineage", event_type="message.created", aggregate_ref=f"message/{message}",
                         actor_ref=f.agents[0].agent_id, payload={})
        uow.stage_outbox(kind="host_wake", target_ref=f"message/{message}", payload={})
    pending = f.invoke(message)["native"]
    assert pending["outbox_status"] == "pending" and pending["attempt_count"] == 0
    key = f.native._key(f.agents[1].agent_id, message)
    f.native.attempts[key] = {"state": "failed", "error_code": "host_binding_not_ready",
                              "error_message": "private endpoint must not be exposed"}
    result = f.invoke(message)
    assert result["native"]["attempt_state"] == "failed"
    assert result["error_code"] == "host_binding_not_ready"
    assert result["progress"]["host_turn_started"] is None
    assert "private endpoint" not in json.dumps(result)
    f.native.attempts[key] = {"state": "running", "turn_id_digest": "sha256:proven-turn"}
    assert f.invoke(message)["progress"]["host_turn_started"] is None
    f.native.attempts[key]["evidence"] = [{"kind": "turn_started", "message_id": message}]
    assert f.invoke(message)["progress"]["host_turn_started"] is True
    f.native.attempts[key]["coalesced_into"] = "other-message"
    assert f.invoke(message)["progress"]["host_turn_started"] is None
    f.service.native_policy = lambda: False
    result = f.invoke(message, wake=True)
    assert result["native"]["enabled"] is False
    assert result["error_code"] == "native_wake_disabled"
    assert f.calls == []
