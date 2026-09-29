"""FX1 commands use real authorization, SQLite UoW, replay and recovery."""

from __future__ import annotations

import contextlib
import importlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException, Response
from tests.integration.test_m1_runtime_flow import _baseline, _endpoint
from typer.testing import CliRunner

from tsunagou.api.app import CommandRequest
from tsunagou.bootstrap.container import build_application
from tsunagou.modules.projects import ProjectRegistry
from tsunagou.shared_kernel.ids import new_id


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    ProjectRegistry.initialize(tmp_path, name="integrity", objective="state integrity")
    monkeypatch.setenv("TSUNAGOU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("TSUNAGOU_STATE_DIR", str(tmp_path / ".tsunagou/local"))
    monkeypatch.setenv("TSUNAGOU_CONTROL_TOKEN", "control")
    monkeypatch.setenv("TSUNAGOU_HOST_WAKE", "disabled")
    app = build_application()
    registry = json.loads((Path(__file__).parents[2] / "protocol/registry/commands.json").read_text(encoding="utf-8"))

    def call(kind: str, payload: dict, who: dict | None = None, *, token: str | None = None, command_id: str | None = None):
        return _endpoint(app)(kind, CommandRequest(
            command_id=command_id or new_id(), protocol_version="1.0", schema_bundle_digest=registry["schema_bundle_digest"],
            payload=payload,
        ), Response(), f"Bearer {token or (who['secret_token'] if who else 'control')}",
                              who["session_id"] if who else None, who["connection_epoch"] if who else None)["result"]

    def enroll(name: str):
        ticket = call("agent.ticket.create.user", {"kind": "worker", "installation_id": name,
                                                  "conversation_evidence": {"conversation_id": name}})
        return call("agent.enroll", {"installation_id": name, "conversation_evidence": {"conversation_id": name},
                                     "probe_payload": _baseline()}, token=ticket["secret"])

    main, worker = enroll("main"), enroll("worker")
    call("authority.appoint", {"agent_id": main["agent_id"]})
    try:
        yield app, call, main, worker
    finally:
        app.state.project_database.release_process_lock()


def events(app: Any) -> list[dict]:
    with contextlib.closing(app.state.project_database._connect()) as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM events ORDER BY event_seq")]


def propose(call, main, worker, **extra):
    return call("contract.propose", {
        "payload": {"decision": "shared"}, "participants_required": [
            {"slot": "writer", "agent_id": worker["agent_id"]},
            {"slot": "reviewer", "agent_id": main["agent_id"]},
        ], **extra,
    }, main)


@pytest.mark.parametrize("terminal", ["withdrawn", "rejected", "superseded", "accepted"])
def test_terminal_contract_no_mutation_or_success_event_and_replay(runtime, terminal: str) -> None:
    app, call, main, worker = runtime
    proposal = propose(call, main, worker)
    payload = {"proposal_id": proposal["proposal_id"], "proposal_digest": proposal["digest"]}
    if terminal == "withdrawn":
        call("contract.withdraw", {"proposal_id": proposal["proposal_id"], "reason": "changed"}, main)
    elif terminal == "rejected":
        call("contract.reject", {**payload, "reason": "different approach"}, worker)
    elif terminal == "superseded":
        propose(call, main, worker, supersedes_id=proposal["proposal_id"])
    else:
        first_id = new_id()
        first = call("contract.accept", {**payload, "participant_slot": "writer"}, worker, command_id=first_id)
        assert first["status"] == "accepted" and first["proposal_status"] == "proposed"
        accepted = call("contract.accept", {**payload, "participant_slot": "reviewer"}, main)
        assert accepted["proposal_status"] == "accepted"
        before_replay = events(app)
        # Replay is the original response, including its then-current proposal status.
        assert call("contract.accept", {**payload, "participant_slot": "writer"}, worker, command_id=first_id) == first
        assert events(app) == before_replay
    snapshot = app.state.state_runtime.capture()
    before = events(app)
    for kind, body, actor in [
        ("contract.accept", {**payload, "participant_slot": "writer"}, worker),
        ("contract.accept_proxy", {**payload, "participant_slot_id": "writer"}, main),
    ]:
        with pytest.raises(HTTPException) as exc:
            call(kind, body, actor)
        assert exc.value.detail["code"] == "proposal_not_proposed"
    assert app.state.state_runtime.capture() == snapshot
    assert events(app) == before


def test_proxy_identity_and_cancel_survive_restart_with_audit_times(runtime, monkeypatch: pytest.MonkeyPatch) -> None:
    app, call, main, worker = runtime
    proposal = propose(call, main, worker)
    proxy_payload = {"proposal_id": proposal["proposal_id"], "proposal_digest": proposal["digest"], "participant_slot_id": "writer"}
    with pytest.raises(HTTPException) as exc:
        call("contract.accept_proxy", proxy_payload, worker)
    assert exc.value.status_code == 403
    result = call("contract.accept_proxy", proxy_payload, main)
    assert result["real_actor_id"] == main["agent_id"]
    assert result["represented_participant"] == worker["agent_id"]
    assert result["proposal_status"] == "proposed"
    task = call("task.create", {"title": "unowned", "objective": "cancel before claim"}, main)
    payload = {"task_id": task["task_id"], "reason": "unneeded"}
    command_id = new_id()
    cancelled = call("task.cancel_request", payload, main, command_id=command_id)
    assert cancelled["status"] == "cancelled"
    before = events(app)
    assert call("task.cancel_request", payload, main, command_id=command_id) == cancelled
    with pytest.raises(HTTPException) as exc:
        call("task.cancel_request", payload, main)
    assert exc.value.detail["code"] == "terminal_task"
    assert events(app) == before
    proxy_event = next(e for e in before if e["event_type"] == "contract.accept_proxy"
                       and e["subject_ref"].startswith("contract_acceptance/"))
    assert main["agent_id"] in proxy_event["actor_ref"]
    assert isinstance(proxy_event["occurred_at"], int) and proxy_event["occurred_at"] > 0
    assert isinstance(proxy_event["recorded_at"], int)
    app.state.project_database.release_process_lock()
    rebuilt = build_application()
    try:
        state = rebuilt.state.state_runtime
        assert state.tasks.tasks[task["task_id"]].status == "cancelled"
        assert state.cognition.proposals[proposal["proposal_id"]].status == "proposed"
        acceptance = state.cognition.acceptances[(proposal["proposal_id"], "writer")]
        assert acceptance.real_actor_id == main["agent_id"]
        assert acceptance.represented_participant == worker["agent_id"]
        assert next(e for e in events(rebuilt) if e["event_id"] == proxy_event["event_id"]) == proxy_event
        history = next(route.endpoint for route in rebuilt.routes
                       if getattr(route, "path", "") == "/api/v1/projects/{project_id}/history")
        project_id = rebuilt.state.project_database.project_id
        page = history(project_id, authorization="Bearer control", actor_ref=main["agent_id"])
        row = next(item for item in page["items"] if item["source_event_id"] == proxy_event["event_id"])
        assert row["occurred_at"].endswith("Z") and row["recorded_at"].endswith("Z")
        cli = importlib.import_module("tsunagou.cli.app")
        # Keep the real query projection and CLI renderer; only replace the network hop.
        monkeypatch.setattr(cli, "_daemon_request", lambda *args, **kwargs: page)
        monkeypatch.setattr(cli, "_control_token", lambda: "control")
        output = CliRunner().invoke(cli.app, ["project", "history", project_id, "--json"])
        assert output.exit_code == 0, output.output
        assert json.loads(output.output)["items"] == page["items"]
        human = CliRunner().invoke(cli.app, ["project", "history", project_id])
        assert human.exit_code == 0, human.output
        assert row["occurred_at"] in human.output and "contract.accept_proxy" in human.output
    finally:
        rebuilt.state.project_database.release_process_lock()


@pytest.mark.parametrize("participants", [
    ["worker"], [{"slot": "writer"}], [{"slot": "writer", "agent_id": "foreign-project-agent"}],
    [{"slot": "writer", "agent_id": " "}],
])
def test_invalid_members_have_no_persisted_proposal(runtime, participants) -> None:
    app, call, main, worker = runtime
    before = events(app)
    with pytest.raises(HTTPException):
        propose(call, main, worker, participants_required=participants)
    assert not app.state.state_runtime.cognition.proposals
    assert events(app) == before


def test_duplicate_slots_and_invalid_supersede_leave_original_untouched(runtime) -> None:
    app, call, main, worker = runtime
    proposal = propose(call, main, worker)
    snapshot = app.state.state_runtime.capture()
    with pytest.raises(HTTPException) as exc:
        propose(call, main, worker, supersedes_id=proposal["proposal_id"], participants_optional=[
            {"slot": "writer", "agent_id": main["agent_id"]},
        ])
    assert exc.value.detail["code"] == "duplicate_contract_slot"
    assert app.state.state_runtime.capture() == snapshot
    # A different participant cannot replace another Agent's proposal.
    with pytest.raises(HTTPException) as exc:
        call("contract.propose", {"payload": {}, "participants_required": [
            {"slot": "writer", "agent_id": worker["agent_id"]},
        ], "supersedes_id": proposal["proposal_id"]}, worker)
    assert exc.value.detail["code"] == "proposal_owner_required"
    assert app.state.state_runtime.capture() == snapshot


def test_only_owner_ack_or_main_reclaim_can_finish_active_cancel(runtime) -> None:
    app, call, main, worker = runtime
    for reclaim in (False, True):
        task = call("task.create", {"title": "claimed", "objective": "cancel active"}, main)
        task_payload = {"task_id": task["task_id"]}
        call("task.ready", task_payload, main)
        published = call("task.publish", task_payload, main)
        attempt = call("task.begin", {**task_payload, "expected_task_revision": published["revision"]}, worker)
        result = call("task.cancel_request", {**task_payload, "reason": "stop"}, main)
        assert result["status"] == "cancel_requested"
        if reclaim:
            body = {**task_payload, "expected_attempt_id": attempt["attempt_id"], "disposition": "cancel"}
            with pytest.raises(HTTPException) as exc:
                call("task.recover", body, worker)
            assert exc.value.status_code == 403
            result = call("task.recover", body, main)
        else:
            body = {**task_payload, "attempt_id": attempt["attempt_id"]}
            with pytest.raises(HTTPException) as exc:
                call("task.cancel_ack", body, main)
            assert exc.value.detail["code"] == "attempt_owner_required"
            result = call("task.cancel_ack", body, worker)
        assert result["status"] == "cancelled"
        assert app.state.state_runtime.tasks.attempts[attempt["attempt_id"]].ended_at is not None
