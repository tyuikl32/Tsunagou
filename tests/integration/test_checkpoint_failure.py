from __future__ import annotations

import json
import subprocess
from importlib.resources import files
from pathlib import Path
from typing import Any

from fastapi import Response

from tsunagou.api.app import CommandRequest
from tsunagou.bootstrap.container import build_application
from tsunagou.modules.projects import ProjectRegistry
from tsunagou.shared_kernel.baseline import ADMISSION_CAPABILITIES
from tsunagou.shared_kernel.ids import new_id


def test_project_completion_survives_checkpoint_materialization_failure(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    registry = ProjectRegistry.initialize(tmp_path, name="failure", objective="checkpoint failure")
    state_dir = tmp_path / ".tsunagou" / "local"
    monkeypatch.setenv("TSUNAGOU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("TSUNAGOU_STATE_DIR", str(state_dir))
    monkeypatch.setenv("TSUNAGOU_CONTROL_TOKEN", "control")
    app = build_application()
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/v1/commands/{command_kind}")
    command_registry = json.loads(files("tsunagou.protocol_data").joinpath("registry", "commands.json").read_text(encoding="utf-8"))

    def call(kind: str, payload: dict[str, Any], authorization: str, receipt: dict[str, Any] | None = None) -> dict[str, Any]:
        request = CommandRequest(
            command_id=new_id(), protocol_version="1.0",
            schema_bundle_digest=command_registry["schema_bundle_digest"], payload=payload,
        )
        result = endpoint(
            kind, request, Response(), f"Bearer {authorization}",
            receipt.get("session_id") if receipt else None,
            receipt.get("connection_epoch") if receipt else None,
        )
        return result["result"]

    ticket = call("agent.ticket.create.user", {
        "kind": "worker", "installation_id": "completion-main",
        "conversation_evidence": {"conversation_id": "completion-main"},
    }, "control")
    main = call("agent.enroll", {
        "installation_id": "completion-main",
        "conversation_evidence": {"conversation_id": "completion-main"},
        "probe_payload": {"baseline": {
            name: {"status": "supported", "evidence_refs": [f"fixture:{name}"]}
            for name in ADMISSION_CAPABILITIES
        }},
    }, ticket["secret"])
    call("authority.appoint", {"agent_id": main["agent_id"]}, "control")
    proposal = call("project.completion.propose.main", {
        "expected_project_revision": 1,
        "objective_ref": "project",
        "outstanding_summary": "none",
        "evidence_refs": [],
    }, main["secret_token"], main)

    def fail_materialization(**_: Any) -> Any:
        raise OSError("disk full")

    assert app.state.checkpoint_store is not None
    monkeypatch.setattr(app.state.checkpoint_store, "materialize", fail_materialization)
    confirmed = call("project.completion.confirm", {
        "proposal_id": proposal["proposal_id"],
        "expected_project_revision": 1,
        "expected_revisions": {"decision": proposal["revision"]},
        "proposal_digest": proposal["proposal_digest"],
    }, "control")
    assert confirmed["status"] == "completed"
    assert confirmed["checkpoint_status"] == "failed"
    assert confirmed["operation_id"]

    app.state.project_database.release_process_lock()
    rebuilt = build_application()
    assert registry.project is not None
    assert ProjectRegistry(tmp_path).project is not None
    assert ProjectRegistry(tmp_path).project.lifecycle == "completed"
    operation = next(route.endpoint for route in rebuilt.routes if getattr(route, "path", "") == "/api/v1/operations/{operation_id}")
    view = operation(confirmed["operation_id"])
    assert view["status"] == "failed"
    assert view["error_code"] == "checkpoint_materialization_failed"
    rebuilt_endpoint = next(
        route.endpoint for route in rebuilt.routes if getattr(route, "path", "") == "/api/v1/commands/{command_kind}"
    )
    retry_request = CommandRequest(
        command_id=new_id(), protocol_version="1.0",
        schema_bundle_digest=command_registry["schema_bundle_digest"],
        payload={"scope_refs": [confirmed["operation_id"]], "reason": "retry checkpoint materialization"},
    )
    retried = rebuilt_endpoint(
        "durability.reconcile", retry_request, Response(),
        f"Bearer {main['secret_token']}", main["session_id"], main["connection_epoch"],
    )["result"]
    assert retried["operation_id"] == confirmed["operation_id"]
    assert retried["status"] == "succeeded"
    assert retried["checkpoint_digest"].startswith("sha256:")


def _caller(app: Any) -> Any:
    """Route endpoints called directly, the way the tests in this file do it."""
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/v1/commands/{command_kind}")
    command_registry = json.loads(files("tsunagou.protocol_data").joinpath("registry", "commands.json").read_text(encoding="utf-8"))

    def call(kind: str, payload: dict[str, Any], authorization: str, receipt: dict[str, Any] | None = None) -> dict[str, Any]:
        request = CommandRequest(
            command_id=new_id(), protocol_version="1.0",
            schema_bundle_digest=command_registry["schema_bundle_digest"], payload=payload,
        )
        result = endpoint(
            kind, request, Response(), f"Bearer {authorization}",
            receipt.get("session_id") if receipt else None,
            receipt.get("connection_epoch") if receipt else None,
        )
        return result["result"]

    return call


def _enroll_main(call: Any, identity: str) -> dict[str, Any]:
    conversation = {"installation_id": identity, "conversation_evidence": {"conversation_id": identity}}
    ticket = call("agent.ticket.create.user", conversation, "control")
    main = call("agent.enroll", {
        **conversation,
        "probe_payload": {"baseline": {
            name: {"status": "supported", "evidence_refs": [f"fixture:{name}"]}
            for name in ADMISSION_CAPABILITIES
        }},
    }, ticket["secret"])
    call("authority.appoint", {"agent_id": main["agent_id"]}, "control")
    return main


def test_checkpoint_failures_exit_lists_what_never_materialized(tmp_path: Path, monkeypatch: Any) -> None:
    """A page of sealed checkpoints cannot answer "was anything ever lost?".

    The failures are a ledger, not checkpoints: an operation that never materialized
    produced no manifest, so the only place they can be read from is the same table the
    retry path writes. That is what this exit exists for — and why it has to hand out the
    operation ids, because retrying one is a separate command that needs the id.
    """

    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    registry = ProjectRegistry.initialize(tmp_path, name="failures", objective="list failed checkpoints")
    monkeypatch.setenv("TSUNAGOU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("TSUNAGOU_STATE_DIR", str(tmp_path / ".tsunagou" / "local"))
    monkeypatch.setenv("TSUNAGOU_CONTROL_TOKEN", "control")
    app = build_application()
    call = _caller(app)
    main = _enroll_main(call, "checkpoint-failures")
    proposal = call("project.completion.propose.main", {
        "expected_project_revision": 1,
        "objective_ref": "project",
        "outstanding_summary": "none",
        "evidence_refs": [],
    }, main["secret_token"], main)

    def fail_materialization(**_: Any) -> Any:
        raise OSError("disk full")

    assert app.state.checkpoint_store is not None
    monkeypatch.setattr(app.state.checkpoint_store, "materialize", fail_materialization)
    confirmed = call("project.completion.confirm", {
        "proposal_id": proposal["proposal_id"],
        "expected_project_revision": 1,
        "expected_revisions": {"decision": proposal["revision"]},
        "proposal_digest": proposal["proposal_digest"],
    }, "control")
    assert confirmed["checkpoint_status"] == "failed"

    assert registry.project is not None
    project_id = registry.project.project_id
    failures = next(
        route.endpoint for route in app.routes
        if getattr(route, "path", "") == "/api/v1/projects/{project_id}/checkpoint-failures"
    )
    listed = failures(project_id, authorization="Bearer control")
    assert listed["project_id"] == project_id
    assert [item["operation_id"] for item in listed["items"]] == [confirmed["operation_id"]]
    (item,) = listed["items"]
    assert item["status"] == "failed"
    assert item["error_code"] == "checkpoint_materialization_failed"
    # Why a checkpoint was being taken is the caller's own words: "failed while the
    # project was being completed" reads differently from "a user asked for one".
    assert item["reason"] == "project_completion"
    assert item["created_at"] and item["attempt_count"] >= 1

    # The console's retry button: user token plus the explicit operation id this exit
    # just handed out. Nothing runs in the background here, so the retry re-runs inline
    # and fails again — which is exactly the point: the retry must re-run *that* ledger
    # row rather than open a second one, or the page would grow a duplicate card per try.
    retried = call("checkpoint.create.user", {
        "retry_operation_id": confirmed["operation_id"], "reason": "retry from console",
    }, "control")
    assert retried["operation_id"] == confirmed["operation_id"]
    again = failures(project_id, authorization="Bearer control")["items"]
    assert [entry["operation_id"] for entry in again] == [confirmed["operation_id"]]
    assert again[0]["attempt_count"] > item["attempt_count"]
    app.state.project_database.release_process_lock()
