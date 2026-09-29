"""Submit-time adjudication of workspace results.

A result that **leaves out** a change the daemon observed *inside the Attempt's own
leased area* is rejected before anything is written. The other direction — a claimed
path the daemon did not observe, or one outside the workspace's prepared scope — is
owned by the submission boundary and by the workspace domain, so this gate
deliberately does not repeat it.

Two consequences are asserted here, because they are the whole point of the gate:

* the rejection is free of side effects, so a repaired Attempt can simply
  re-submit the same result (self-repair without a new command);
* the rejection itself becomes a durable event, so "this was refused, and why"
  stays queryable and replayable instead of existing only in an error string.

The same boundary also holds a result back while the contract the task depends on is
still being discussed, so the contract cases live here too: the Attempt stays open
across a refusal, which is what makes a refused submit a usable signal.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException, Response

from tsunagou.api.app import CommandRequest
from tsunagou.bootstrap.container import build_application
from tsunagou.modules.projects import ProjectRegistry
from tsunagou.shared_kernel.baseline import ADMISSION_CAPABILITIES
from tsunagou.shared_kernel.ids import new_id


def _baseline() -> dict[str, Any]:
    return {
        "baseline": {
            name: {"status": "supported", "evidence_refs": [f"fixture:{name}"]}
            for name in ADMISSION_CAPABILITIES
        }
    }


def _endpoint(app: Any) -> Any:
    return next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", "") == "/api/v1/commands/{command_kind}"
    )


def _running_attempt(
    tmp_path: Path, monkeypatch: Any, *, extra_roots: tuple[str, ...] = ()
) -> dict[str, Any]:
    """A strict-runtime project with one main agent and one started Attempt holding a
    single write lease over the `leased/` prefix.

    Without ``extra_roots`` the project keeps its implicit fallback root, so the scan
    reports plain relative paths. Naming roots instead registers real directories, which
    makes the scan span more than one root and prefix every reported path with
    ``<root_id>/`` — the shape the lease matcher has to handle as well.
    """
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    ProjectRegistry.initialize(tmp_path, name="gate", objective="submit-time gate")
    state_dir = tmp_path / ".tsunagou" / "local"
    monkeypatch.setenv("TSUNAGOU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("TSUNAGOU_STATE_DIR", str(state_dir))
    monkeypatch.setenv("TSUNAGOU_CONTROL_TOKEN", "control")
    app = build_application()
    endpoint = _endpoint(app)
    registry = json.loads(
        files("tsunagou.protocol_data")
        .joinpath("registry", "commands.json")
        .read_text(encoding="utf-8")
    )

    def call(
        kind: str,
        payload: dict[str, Any],
        authorization: str,
        *,
        session_id: str | None = None,
        epoch: int | None = None,
    ) -> dict[str, Any]:
        request = CommandRequest(
            command_id=new_id(),
            protocol_version="1.0",
            schema_bundle_digest=registry["schema_bundle_digest"],
            payload=payload,
        )
        return endpoint(kind, request, Response(), f"Bearer {authorization}", session_id, epoch)["result"]

    def enroll(name: str) -> dict[str, Any]:
        ticket = call(
            "agent.ticket.create.user",
            {"kind": "worker", "installation_id": name,
             "conversation_evidence": {"conversation_id": name}},
            "control",
        )
        return call(
            "agent.enroll",
            {"installation_id": name,
             "conversation_evidence": {"conversation_id": name},
             "probe_payload": _baseline()},
            ticket["secret"],
        )

    main = enroll("main")
    worker = enroll("worker")
    call("authority.appoint", {"agent_id": main["agent_id"]}, "control")

    def agent_call(kind: str, payload: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
        return call(
            kind, payload, receipt["secret_token"],
            session_id=receipt["session_id"], epoch=receipt["connection_epoch"],
        )

    registered: list[str] = []
    for name in extra_roots:
        root_dir = tmp_path / name
        root_dir.mkdir()
        registered.append(
            agent_call(
                "root.register",
                {"name": name, "kind": "directory",
                 "binding_request": {"absolute_path": str(root_dir)}, "required": False},
                main,
            )["root_id"]
        )
    lease_root_id = registered[0] if registered else "root"

    task = agent_call("task.create", {"title": "gate", "objective": "one file"}, main)
    task_id = task["task_id"]
    agent_call("task.ready", {"task_id": task_id}, main)
    agent_call("task.publish", {"task_id": task_id}, main)
    attempt_id = agent_call("task.claim", {"task_id": task_id}, worker)["attempt_id"]
    decision = agent_call(
        "workspace.select",
        {"task_id": task_id, "attempt_id": attempt_id, "driver_kind": "shared",
         "evidence_refs": ["fixture:shared"], "hard_constraints": [],
         "input_digest": "fixture", "risk_submission_ref": None},
        main,
    )
    intent = agent_call(
        "resource.intent",
        {"task_id": task_id, "attempt_id": attempt_id, "reason": "write leased prefix",
         "scope_digest": "scope",
         "resources": [{"kind": "path", "root_id": lease_root_id, "segments": ["leased"],
                        "mode": "exclusive_write"}]},
        worker,
    )
    agent_call(
        "resource.acquire",
        {"task_id": task_id, "attempt_id": attempt_id, "intent_id": intent["intent_id"],
         "intent_revision": 1, "scope_digest": "scope"},
        worker,
    )
    workspace = agent_call(
        "workspace.prepare",
        {"task_id": task_id, "attempt_id": attempt_id, "decision_id": decision["decision_id"],
         "input_digest": "fixture", "root_binding_refs": [],
         "baseline": {"index_digest": "i", "tracked_state_digest": "t"}},
        worker,
    )
    preflight = agent_call(
        "task.preflight",
        {"task_id": task_id, "attempt_id": attempt_id,
         "evidence_refs": [f"workspace:{workspace['workspace_id']}"]},
        worker,
    )
    agent_call(
        "task.start",
        {"task_id": task_id, "attempt_id": attempt_id, "preflight_id": preflight["preflight_id"]},
        worker,
    )
    return {
        "app": app, "tmp_path": tmp_path, "state_dir": state_dir, "agent_call": agent_call,
        "main": main, "worker": worker, "task_id": task_id, "attempt_id": attempt_id,
        "workspace_id": workspace["workspace_id"], "baseline_digest": workspace["baseline_digest"],
        "root_ids": registered,
    }


def _record(harness: dict[str, Any], changed_paths: list[str]) -> dict[str, Any]:
    return harness["agent_call"](
        "workspace.result",
        {"workspace_id": harness["workspace_id"], "task_id": harness["task_id"],
         "attempt_id": harness["attempt_id"], "baseline_digest": harness["baseline_digest"],
         "changed_paths": changed_paths, "commit_refs": [], "untracked_summary": [],
         "validation_refs": ["pytest:ok"]},
        harness["worker"],
    )


def _denial_events(harness: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    connection = sqlite3.connect(harness["state_dir"] / "state.sqlite3")
    try:
        rows = connection.execute(
            "SELECT event_type, payload_json FROM events WHERE event_type LIKE '%.denied'"
        ).fetchall()
    finally:
        connection.close()
    return [(event_type, json.loads(payload)) for event_type, payload in rows]


def _conflict_denials(harness: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        payload
        for _event_type, payload in _denial_events(harness)
        if str(payload.get("code", "")).startswith("resource_conflict:")
    ]


def test_a_refused_lease_names_the_holder_and_is_recorded(tmp_path: Path, monkeypatch: Any) -> None:
    """Being turned away from a lease is a refusal, not an outage.

    Two things have to be true for that to be useful. The caller must be told **who is
    in the way and until when** -- otherwise the only possible response is to retry
    blindly -- and the refusal must survive as a shared fact, because "how often do
    agents collide, and over what" is a property of the run that no error string keeps.
    """
    harness = _running_attempt(tmp_path, monkeypatch)
    agent_call = harness["agent_call"]
    main, worker = harness["main"], harness["worker"]

    second = agent_call("task.create", {"title": "second", "objective": "same prefix"}, main)
    agent_call("task.ready", {"task_id": second["task_id"]}, main)
    agent_call("task.publish", {"task_id": second["task_id"]}, main)
    attempt = agent_call("task.claim", {"task_id": second["task_id"]}, worker)["attempt_id"]
    intent = agent_call(
        "resource.intent",
        {"task_id": second["task_id"], "attempt_id": attempt, "reason": "same prefix",
         "scope_digest": "scope",
         "resources": [{"kind": "path", "root_id": "root", "segments": ["leased"],
                        "mode": "exclusive_write"}]},
        worker,
    )

    with pytest.raises(HTTPException) as refusal:
        agent_call(
            "resource.acquire",
            {"task_id": second["task_id"], "attempt_id": attempt,
             "intent_id": intent["intent_id"], "intent_revision": 1, "scope_digest": "scope"},
            worker,
        )

    assert refusal.value.status_code == 400
    assert refusal.value.detail["code"].startswith("resource_conflict:")
    (blocked,) = refusal.value.detail["conflicts"]
    assert blocked["holder_attempt_id"] == harness["attempt_id"]
    assert blocked["holder_expires_at"] > 0
    assert blocked["held_key"].endswith("leased")
    assert refusal.value.detail["requester"]["attempt_id"] == attempt

    (recorded,) = _conflict_denials(harness)
    assert recorded["command_kind"] == "resource.acquire"
    (stored,) = recorded["conflicts"]
    assert stored["holder_attempt_id"] == harness["attempt_id"]
    assert stored["holder_expires_at"] == blocked["holder_expires_at"]

    # The console reads the same refusal back as a conflict: the holder is named, and
    # what became of the collision is worked out from the current state rather than
    # reported by anyone.
    project_id = json.loads(
        (tmp_path / ".tsunagou" / "project.json").read_text(encoding="utf-8")
    )["project_id"]
    conflicts = next(
        route.endpoint for route in harness["app"].routes
        if getattr(route, "path", "") == "/api/v1/projects/{project_id}/conflicts"
    )(project_id)["items"]
    (item,) = conflicts
    assert item["phase"] == "resource.acquire"
    assert item["requester"]["attempt_id"] == attempt
    assert item["holders"][0]["attempt_id"] == harness["attempt_id"]
    assert item["holders"][0]["agent_id"] == worker["agent_id"]
    assert item["holders"][0]["task_id"] == harness["task_id"]
    assert item["resolution"] == "open"

    # 总路径上那一行要说清"为什么被拒"。原因码落在事件的 payload.code 上，而读出来的
    # 是投影的 reason_code —— 这个兜底就是这一条在守：以前这里只有动作名，括号里是空的。
    history = next(
        route.endpoint for route in harness["app"].routes
        if getattr(route, "path", "") == "/api/v1/projects/{project_id}/history"
    )(project_id, authorization="Bearer control")
    denied = [item for item in history["items"] if item["action"] == "resource.acquire.denied"]
    assert len(denied) == 1
    assert denied[0]["reason_code"] == refusal.value.detail["code"]


def test_change_inside_own_lease_but_unreported_is_rejected(tmp_path: Path, monkeypatch: Any) -> None:
    harness = _running_attempt(tmp_path, monkeypatch)
    leased = tmp_path / "leased"
    leased.mkdir()
    (leased / "hidden.py").write_text("x = 1\n", encoding="utf-8")

    with pytest.raises(HTTPException) as failure:
        _record(harness, [])

    assert failure.value.detail["code"] == "unreported_changes"
    assert failure.value.detail["violations"] == ["leased/hidden.py"]
    # The refusal tells the caller what *was* allowed and what to do next, which is
    # what lets an agent repair itself instead of retrying blindly.
    assert failure.value.detail["allowed"] == ["leased"]
    assert failure.value.detail["next_steps"]


def test_changes_outside_the_lease_are_recorded_not_rejected(tmp_path: Path, monkeypatch) -> None:
    """Ownership outside the leased area cannot be attributed (user edits, other
    Attempts, the daemon's own state dir), so those paths stay part of the record
    instead of blocking the Attempt."""
    harness = _running_attempt(tmp_path, monkeypatch)
    (tmp_path / "user_edit.py").write_text("hand written\n", encoding="utf-8")

    recorded = _record(harness, [])

    assert recorded["result_manifest_id"]
    assert recorded["status"] == "result_recorded"


def test_repair_then_resubmit_succeeds(tmp_path: Path, monkeypatch: Any) -> None:
    """Verification is just re-submission: declaring the observed path (or rolling it
    back) makes the same result acceptable, with no extra command and no leftover
    state."""
    harness = _running_attempt(tmp_path, monkeypatch)
    leased = tmp_path / "leased"
    leased.mkdir()
    (leased / "offending.py").write_text("x = 1\n", encoding="utf-8")

    with pytest.raises(HTTPException):
        _record(harness, [])

    assert _record(harness, ["leased/offending.py"])["result_manifest_id"]


def test_rejection_leaves_a_durable_event(tmp_path: Path, monkeypatch: Any) -> None:
    harness = _running_attempt(tmp_path, monkeypatch)
    leased = tmp_path / "leased"
    leased.mkdir()
    (leased / "hidden.py").write_text("x = 1\n", encoding="utf-8")

    with pytest.raises(HTTPException):
        _record(harness, [])

    events = _denial_events(harness)
    assert [event_type for event_type, _ in events] == ["command.workspace.result.denied"]
    _, payload = events[0]
    assert payload["code"] == "unreported_changes"
    assert payload["violations"] == ["leased/hidden.py"]


def test_multi_root_lease_prefix_is_matched(tmp_path: Path, monkeypatch: Any) -> None:
    """Spanning more than one root makes the scan prefix every path with `<root_id>/`.

    The gate has to attribute such a prefixed observation back to a lease whose key is
    (root_id, segments) — and must not blame the lease for the *other* root's changes.
    """
    harness = _running_attempt(tmp_path, monkeypatch, extra_roots=("leased_root", "other_root"))
    leased_root, _other_root = harness["root_ids"]
    (tmp_path / "leased_root" / "leased").mkdir()
    (tmp_path / "leased_root" / "leased" / "hidden.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "other_root" / "elsewhere.py").write_text("y = 1\n", encoding="utf-8")

    with pytest.raises(HTTPException) as failure:
        _record(harness, [])

    assert failure.value.detail["code"] == "unreported_changes"
    assert failure.value.detail["violations"] == [f"{leased_root}/leased/hidden.py"]


def test_recording_a_result_after_submitting_is_rejected(tmp_path: Path, monkeypatch: Any) -> None:
    """Recording a result is part of the execution, not a postscript.

    Submitting closes the Attempt and releases its Lease, so a result recorded
    afterwards could no longer be adjudicated against it. The order is pinned:
    result first, submit second.
    """
    harness = _running_attempt(tmp_path, monkeypatch)

    harness["agent_call"](
        "task.submit",
        {"task_id": harness["task_id"], "attempt_id": harness["attempt_id"],
         "summary": "done", "evidence_refs": [], "artifact_refs": [],
         "workspace_result_ref": ""},
        harness["worker"],
    )

    with pytest.raises(HTTPException) as failure:
        _record(harness, [])

    assert failure.value.status_code == 400
    assert failure.value.detail["code"] == "attempt_not_running"


def _submit(harness: dict[str, Any], revisions: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "task_id": harness["task_id"], "attempt_id": harness["attempt_id"],
        "summary": "done", "evidence_refs": [], "artifact_refs": [],
        "workspace_result_ref": "",
    }
    if revisions is not None:
        payload["expected_revisions"] = revisions
    return harness["agent_call"]("task.submit", payload, harness["worker"])


def _propose_contract(
    harness: dict[str, Any], *, actor: dict[str, Any], participants: list[dict[str, Any]],
    supersedes_id: str = "",
) -> dict[str, Any]:
    """A contract declared for *this* task: the payload carries the task id, which is
    the convention the boundary reads to know what a contract covers."""
    return harness["agent_call"](
        "contract.propose",
        {"contract_id": "api", "contract_kind": "interface",
         "payload": {"task_id": harness["task_id"]},
         "participants_required": participants, "participants_optional": [],
         "subject_ref": harness["task_id"], "input_refs": [], "supersedes_id": supersedes_id},
        actor,
    )


def _accept_contract(harness: dict[str, Any], proposal: dict[str, Any], actor: dict[str, Any]) -> None:
    harness["agent_call"](
        "contract.accept",
        {"proposal_id": proposal["proposal_id"], "participant_slot": "worker",
         "proposal_digest": proposal["digest"]},
        actor,
    )


def test_a_pending_revision_holds_the_submit_boundary(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A finished Attempt must not publish while a revision of its contract is still
    being discussed: the parties no longer agree on which version governs.

    Accepting the revision retires the old version and releases the boundary, and the
    participant who has to move to the new version is told once.
    """
    harness = _running_attempt(tmp_path, monkeypatch)
    main, worker = harness["main"], harness["worker"]
    _record(harness, [])

    agreed = _propose_contract(
        harness, actor=main,
        participants=[{"slot": "worker", "agent_id": worker["agent_id"]}],
    )
    _accept_contract(harness, agreed, worker)

    # A revision that declares no participants inherits them from the version it
    # replaces, so it cannot quietly narrow who has to agree.
    revision = _propose_contract(
        harness, actor=main, supersedes_id=agreed["proposal_id"], participants=[],
    )
    assert revision["supersedes_id"] == agreed["proposal_id"]

    with pytest.raises(HTTPException) as failure:
        _submit(harness)
    assert failure.value.status_code == 400
    assert failure.value.detail["code"] == "contract_not_accepted"

    # Accepting the revision retires the agreed version and releases the boundary: the
    # Attempt is still open, so the same submit now goes through.
    _accept_contract(harness, revision, worker)
    assert _submit(harness)["result_id"]

    told = [
        message for message in harness["agent_call"](
            "inbox.claim", {"limit": 20, "max_bytes": 8192}, worker
        )["messages"]
        if message["kind"] == "contract.revised"
    ]
    assert len(told) == 1
    assert told[0]["sender_agent_id"] == main["agent_id"]


def test_a_revision_landing_mid_attempt_is_refused_until_the_work_catches_up(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A revision can land while an attempt is already running, and the work must not be
    published on top of the agreement it was built against.

    The refusal has to be repairable in place: reading the version in force and declaring
    it is enough, because nothing was closed — same attempt, same lease, same files. That
    is what makes "catch up" an option instead of "start over".
    """
    harness = _running_attempt(tmp_path, monkeypatch)
    main, worker = harness["main"], harness["worker"]
    _record(harness, [])

    agreed = _propose_contract(
        harness, actor=main,
        participants=[{"slot": "worker", "agent_id": worker["agent_id"]}],
    )
    _accept_contract(harness, agreed, worker)
    stale = [f"{agreed['proposal_id']}:{agreed['digest']}"]

    revision = _propose_contract(
        harness, actor=main, supersedes_id=agreed["proposal_id"], participants=[],
    )
    _accept_contract(harness, revision, worker)

    with pytest.raises(HTTPException) as failure:
        _submit(harness, {"contract": stale})
    assert failure.value.detail["code"] == "contract_revision_conflict"

    # Same attempt, and it can still deliver once it declares what is in force.
    assert _submit(
        harness, {"contract": [f"{revision['proposal_id']}:{revision['digest']}"]}
    )["result_id"]


def test_a_refused_revision_does_not_freeze_the_task(tmp_path: Path, monkeypatch: Any) -> None:
    """Refusing a revision is a decision, not a dead end.

    The version in force is still the accepted one, so the Attempt stays free to
    publish: a participant can always end the ambiguity by saying no.
    """
    harness = _running_attempt(tmp_path, monkeypatch)
    main, worker = harness["main"], harness["worker"]
    _record(harness, [])

    agreed = _propose_contract(
        harness, actor=main,
        participants=[{"slot": "worker", "agent_id": worker["agent_id"]}],
    )
    _accept_contract(harness, agreed, worker)
    revision = _propose_contract(
        harness, actor=main, supersedes_id=agreed["proposal_id"], participants=[],
    )

    with pytest.raises(HTTPException) as failure:
        _submit(harness)
    assert failure.value.detail["code"] == "contract_not_accepted"

    harness["agent_call"](
        "contract.reject",
        {"proposal_id": revision["proposal_id"], "proposal_digest": revision["digest"],
         "reason": "keep the agreed version"},
        worker,
    )

    assert _submit(harness)["result_id"]
