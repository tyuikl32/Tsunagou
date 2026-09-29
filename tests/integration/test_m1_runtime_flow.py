from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Response

from tsunagou.api.app import CommandRequest
from tsunagou.bootstrap.container import build_application
from tsunagou.modules.projects import ProjectRegistry
from tsunagou.shared_kernel.baseline import ADMISSION_CAPABILITIES
from tsunagou.shared_kernel.digests import canonical_digest
from tsunagou.shared_kernel.ids import new_id


def _baseline() -> dict[str, Any]:
    return {"baseline": {name: {"status": "supported", "evidence_refs": [f"fixture:{name}"]} for name in ADMISSION_CAPABILITIES}}


def _endpoint(app: Any) -> Any:
    return next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/v1/commands/{command_kind}")


def test_m1_task_workspace_review_and_user_completion_survive_rebuild(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    ProjectRegistry.initialize(tmp_path, name="M1", objective="runtime flow")
    state_dir = tmp_path / ".tsunagou" / "local"
    monkeypatch.setenv("TSUNAGOU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("TSUNAGOU_STATE_DIR", str(state_dir))
    monkeypatch.setenv("TSUNAGOU_CONTROL_TOKEN", "control")
    app = build_application()
    endpoint = _endpoint(app)
    from importlib.resources import files

    registry = __import__("json").loads(files("tsunagou.protocol_data").joinpath("registry", "commands.json").read_text(encoding="utf-8"))

    def call(
        kind: str, payload: dict[str, Any], authorization: str, *, session_id: str | None = None, epoch: int | None = None
    ) -> dict[str, Any]:
        request = CommandRequest(
            command_id=new_id(),
            protocol_version="1.0",
            schema_bundle_digest=registry["schema_bundle_digest"],
            payload=payload,
        )
        headers = f"Bearer {authorization}"
        result = endpoint(kind, request, Response(), headers, session_id, epoch)
        return result["result"]

    def enroll(name: str) -> dict[str, Any]:
        ticket = call(
            "agent.ticket.create.user",
            {
                "kind": "worker",
                "installation_id": name,
                "conversation_evidence": {"conversation_id": name},
            },
            "control",
        )
        return call(
            "agent.enroll",
            {
                "installation_id": name,
                "conversation_evidence": {"conversation_id": name},
                "probe_payload": _baseline(),
            },
            ticket["secret"],
        )

    main = enroll("main")
    worker = enroll("worker")
    call("authority.appoint", {"agent_id": main["agent_id"]}, "control")

    def agent_call(kind: str, payload: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
        return call(kind, payload, receipt["secret_token"], session_id=receipt["session_id"], epoch=receipt["connection_epoch"])

    task = agent_call("task.create", {"title": "M1", "objective": "write one file", "execution_scope": {"roots": ["coordination"]}}, main)
    agent_call("workspace.select", {"task_id": task["task_id"], "driver_kind": "shared"}, main)
    agent_call("task.ready", {"task_id": task["task_id"]}, main)
    published = agent_call("task.publish", {"task_id": task["task_id"]}, main)
    started = agent_call("task.begin", {"task_id": task["task_id"], "expected_task_revision": published["revision"]}, worker)
    attempt_id = started["attempt_id"]
    agent_call(
        "cognition.report",
        {
            "task_id": task["task_id"],
            "attempt_id": attempt_id,
            "claims": [{"subject_key": "workspace.driver", "claim_type": "literal", "equality_key": "workspace.driver", "value": "shared"}],
            "assumptions": ["same project root"],
            "uncertainties": [],
        },
        worker,
    )
    agent_call(
        "cognition.report",
        {
            "task_id": task["task_id"],
            "attempt_id": attempt_id,
            "claims": [
                {"subject_key": "workspace.driver", "claim_type": "literal", "equality_key": "workspace.driver", "value": "worktree"}
            ],
            "assumptions": [],
            "uncertainties": ["main may choose shared"],
        },
        main,
    )
    contract = agent_call(
        "contract.propose",
        {
            "payload": {"task_id": task["task_id"], "driver": "shared"},
            "participants_required": [
                {"slot": "worker", "agent_id": worker["agent_id"]},
                {"slot": "main", "agent_id": main["agent_id"]},
            ],
        },
        main,
    )
    agent_call(
        "contract.accept",
        {
            "proposal_id": contract["proposal_id"],
            "participant_slot": "worker",
            "proposal_digest": contract["digest"],
            "evidence_refs": [],
        },
        worker,
    )
    agent_call(
        "contract.accept",
        {
            "proposal_id": contract["proposal_id"],
            "participant_slot": "main",
            "proposal_digest": contract["digest"],
            "evidence_refs": [],
        },
        main,
    )
    pending = agent_call(
        "user_decision.propose",
        {
            "kind": "scope.change",
            "proposal_ref": task["task_id"],
            "summary": "confirm scope",
            "choices": ["approved"],
            "expected_revisions": {"decision": 1},
        },
        main,
    )
    blocked = agent_call("task.block", {"task_id": task["task_id"], "attempt_id": attempt_id, "reason": "await user"}, worker)
    assert pending["related_task_id"] == task["task_id"]
    tasks_query = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/v1/projects/{project_id}/tasks")
    assert (
        next(item for item in tasks_query(ProjectRegistry(tmp_path).project.project_id)["items"] if item["task_id"] == task["task_id"])[
            "status"
        ]
        == "blocked"
    )  # type: ignore[union-attr]
    resolved_pending = call(
        "user_decision.resolve",
        {
            "decision_id": pending["decision_id"],
            "choice": "approved",
            "expected_revisions": {"decision": pending["revision"]},
            "proposal_digest": pending["proposal_digest"],
            "reason": "scope confirmed",
        },
        "control",
    )
    assert resolved_pending["related_task_id"] == task["task_id"]
    assert (
        next(item for item in tasks_query(ProjectRegistry(tmp_path).project.project_id)["items"] if item["task_id"] == task["task_id"])[
            "status"
        ]
        == "blocked"
    )  # type: ignore[union-attr]
    # The task policy remains; a new attempt gets a fresh baseline.
    started = agent_call("task.begin", {"task_id": task["task_id"], "expected_task_revision": blocked["revision"]}, worker)
    attempt_id = started["attempt_id"]
    (tmp_path / "demo.py").write_text("print('ok')\n", encoding="utf-8")
    submitted = agent_call(
        "task.submit",
        {
            "task_id": task["task_id"],
            "attempt_id": attempt_id,
            "summary": "implemented",
            "evidence_refs": ["pytest:ok"],
        },
        worker,
    )
    reviewed = call(
        "task.review.accept",
        {
            "task_id": task["task_id"],
            "result_id": submitted["result_id"],
            "result_digest": submitted["digest"],
            "slot_id": "main",
            "evidence_refs": [],
            "reason": "tests pass",
        },
        main["secret_token"],
        session_id=main["session_id"],
        epoch=main["connection_epoch"],
    )
    assert reviewed["status"] == "completed"
    assert submitted["digest"]
    assert list((state_dir / "artifacts" / "blobs" / "sha256").glob("*/*"))

    proposal = agent_call(
        "user_decision.propose",
        {
            "kind": "design.change",
            "proposal_ref": task["task_id"],
            "summary": "confirm design",
            "choices": ["approved"],
            "expected_revisions": {"decision": 1},
            "proposal_digest": canonical_digest(
                {
                    "subject_ref": task["task_id"],
                    "payload": {"choices": ["approved"], "summary": "confirm design"},
                    "revision": 1,
                }
            ),
        },
        main,
    )
    resolved = call(
        "user_decision.resolve",
        {
            "decision_id": proposal["decision_id"],
            "choice": "approved",
            "expected_revisions": {"decision": proposal["revision"]},
            "proposal_digest": proposal["proposal_digest"],
            "reason": "confirmed",
        },
        "control",
    )
    assert resolved["status"] == "resolved"

    # The proposer's own words are answerable answers (the console sends exactly the
    # option text the user tapped). `subject_ref` points at the project — not a task —
    # so this proposes nothing that would block work.
    wording = agent_call("user_decision.propose", {
        "kind": "design.change", "proposal_ref": "project", "summary": "pick a route",
        "choices": ["再补一轮回归", "换方案"], "expected_revisions": {"decision": 1},
    }, main)
    chosen = call("user_decision.resolve", {
        "decision_id": wording["decision_id"], "choice": "再补一轮回归",
        "expected_revisions": {"decision": wording["revision"]},
        "proposal_digest": wording["proposal_digest"], "reason": "chose the regression round",
    }, "control")
    assert (chosen["status"], chosen["decision"]) == ("resolved", "再补一轮回归")

    completion = agent_call(
        "project.completion.propose.main",
        {
            "expected_project_revision": 1,
            "objective_ref": "project",
            "outstanding_summary": "none",
            "evidence_refs": ["task:" + task["task_id"]],
        },
        main,
    )
    confirmed = call(
        "project.completion.confirm",
        {
            "proposal_id": completion["proposal_id"],
            "expected_project_revision": 1,
            "expected_revisions": {"decision": completion["revision"]},
            "proposal_digest": completion["proposal_digest"],
        },
        "control",
    )
    assert confirmed["status"] == "completed"
    assert confirmed["checkpoint_digest"].startswith("sha256:")
    assert confirmed["operation_id"]

    app.state.project_database.release_process_lock()
    rebuilt = build_application()
    query = next(route.endpoint for route in rebuilt.routes if getattr(route, "path", "") == "/api/v1/projects/{project_id}/tasks")
    tasks = query(ProjectRegistry(tmp_path).project.project_id)  # type: ignore[union-attr]
    assert tasks["items"][0]["status"] == "completed"
    checkpoints = next(route.endpoint for route in rebuilt.routes if getattr(route, "path", "") == "/api/v1/checkpoints")
    checkpoint_view = checkpoints(authorization="Bearer control")
    assert checkpoint_view["current"]["digest"] == confirmed["checkpoint_digest"]
    checkpoint_dir = tmp_path / ".tsunagou" / "checkpoints" / confirmed["checkpoint_digest"].replace(":", "_")
    checkpoint_text = "\n".join(path.read_text(encoding="utf-8") for path in checkpoint_dir.glob("*.ndjson"))
    assert "secret_token" not in checkpoint_text
    assert main["secret_token"] not in checkpoint_text
    reviews = next(
        route.endpoint for route in rebuilt.routes
        if getattr(route, "path", "") == "/api/v1/projects/{project_id}/reviews"
    )
    review_view = reviews(ProjectRegistry(tmp_path).project.project_id)  # type: ignore[union-attr]
    # A result says "something was submitted"; the review says whether it was good
    # enough and who said so. The console's task-acceptance column asks the second
    # question, so the verdict has to be readable rather than re-derived from status.
    assert [(item["round_no"], item["decision"], item["reason"]) for item in review_view["items"]] == [
        (1, "accepted", "tests pass"),
    ]
    assert review_view["items"][0]["task_id"] == task["task_id"]
    assert review_view["items"][0]["result_id"] == submitted["result_id"]
    assert review_view["items"][0]["reviewer_agent_id"] == main["agent_id"]
    workspaces = next(
        route.endpoint for route in rebuilt.routes if getattr(route, "path", "") == "/api/v1/projects/{project_id}/workspaces"
    )
    workspace_view = workspaces(ProjectRegistry(tmp_path).project.project_id)  # type: ignore[union-attr]
    result_view = next(item["result"] for item in workspace_view["items"] if "result" in item)
    assert result_view["baseline_conflict"] is True
    artifact_ref = result_view["patch_artifact_ref"]
    artifact = next(route.endpoint for route in rebuilt.routes if getattr(route, "path", "") == "/api/v1/artifacts/{artifact_ref:path}")
    try:
        artifact(artifact_ref)
    except HTTPException as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError("artifact endpoint exposed a private patch without authentication")
    assert artifact(artifact_ref, authorization="Bearer control")["content_base64"]
    cognition = next(route.endpoint for route in rebuilt.routes if getattr(route, "path", "") == "/api/v1/projects/{project_id}/cognition")
    cognition_view = cognition(ProjectRegistry(tmp_path).project.project_id)  # type: ignore[union-attr]
    assert cognition_view["discrepancies"]
    assert cognition_view["contracts"][0]["status"] == "accepted"
    audit = next(route.endpoint for route in rebuilt.routes if getattr(route, "path", "") == "/api/v1/projects/{project_id}/audit")
    audit_view = audit(ProjectRegistry(tmp_path).project.project_id, authorization="Bearer control")  # type: ignore[union-attr]
    assert audit_view["items"]
    assert all("secret_token" not in item for item in audit_view["items"])
    operation = next(route.endpoint for route in rebuilt.routes if getattr(route, "path", "") == "/api/v1/operations/{operation_id}")
    assert operation(confirmed["operation_id"])["status"] == "succeeded"
    recovery = next(route.endpoint for route in rebuilt.routes if getattr(route, "path", "") == "/api/v1/recovery")
    recovery_view = recovery()
    assert recovery_view["status"] == "ready"
    assert isinstance(recovery_view["runtime_epoch"], str) and recovery_view["runtime_epoch"]


def test_main_can_register_bind_and_query_multiple_project_roots(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    ProjectRegistry.initialize(tmp_path, name="Roots", objective="multi-root")
    extra_root = tmp_path / "service"
    extra_root.mkdir()
    state_dir = tmp_path / ".tsunagou" / "local"
    monkeypatch.setenv("TSUNAGOU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("TSUNAGOU_STATE_DIR", str(state_dir))
    monkeypatch.setenv("TSUNAGOU_CONTROL_TOKEN", "control")
    app = build_application()
    endpoint = _endpoint(app)
    from importlib.resources import files

    registry = __import__("json").loads(files("tsunagou.protocol_data").joinpath("registry", "commands.json").read_text(encoding="utf-8"))

    def call(
        kind: str, payload: dict[str, Any], authorization: str, *, session_id: str | None = None, epoch: int | None = None
    ) -> dict[str, Any]:
        request = CommandRequest(
            command_id=new_id(),
            protocol_version="1.0",
            schema_bundle_digest=registry["schema_bundle_digest"],
            payload=payload,
        )
        return endpoint(kind, request, Response(), f"Bearer {authorization}", session_id, epoch)["result"]

    ticket = call(
        "agent.ticket.create.user",
        {
            "kind": "main",
            "installation_id": "root-main",
            "conversation_evidence": {"conversation_id": "root-main"},
        },
        "control",
    )
    main = call(
        "agent.enroll",
        {
            "installation_id": "root-main",
            "conversation_evidence": {"conversation_id": "root-main"},
            "probe_payload": _baseline(),
        },
        ticket["secret"],
    )
    call("authority.appoint", {"agent_id": main["agent_id"]}, "control")

    def main_call(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        return call(kind, payload, main["secret_token"], session_id=main["session_id"], epoch=main["connection_epoch"])

    registered = main_call(
        "root.register",
        {
            "name": "service",
            "kind": "directory",
            "repository_id": "pending",
            "required": True,
            "binding_request": {"absolute_path": str(extra_root)},
            "reason": "add service root",
        },
    )
    repository = main_call(
        "repository.register",
        {
            "name": "service-repository",
            "root_id": registered["root_id"],
            "required": True,
        },
    )
    assert repository["root_id"] == registered["root_id"]
    roots = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/v1/projects/{project_id}/roots")
    project_id = ProjectRegistry(tmp_path).project.project_id  # type: ignore[union-attr]
    roots_view = roots(project_id)
    assert roots_view["items"][0]["root_id"] == registered["root_id"]
    repositories = next(
        route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/v1/projects/{project_id}/repositories"
    )
    assert repositories(project_id)["items"][0]["repository_id"] == repository["repository_id"]

    # One call answers "what is this project?" for a console header, without
    # re-reading the registry files or flattening the two exits above.
    overview = next(route.endpoint for route in app.routes
                    if getattr(route, "path", "") == "/api/v1/projects/{project_id}/overview")
    header = overview(project_id)
    assert header["project_id"] == project_id
    assert header["name"] == "Roots"
    assert header["objective"] == "multi-root"
    assert header["lifecycle"] == "active"
    assert header["policy_revision"] >= 1
    assert [item["root_id"] for item in header["roots"]][-1] == registered["root_id"]
    assert header["repositories"][-1]["repository_id"] == repository["repository_id"]


def test_task_recovery_cancel_scope_and_plan_actions_are_public_and_owner_scoped(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    ProjectRegistry.initialize(tmp_path, name="Task actions", objective="state transitions")
    state_dir = tmp_path / ".tsunagou" / "local"
    monkeypatch.setenv("TSUNAGOU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("TSUNAGOU_STATE_DIR", str(state_dir))
    monkeypatch.setenv("TSUNAGOU_CONTROL_TOKEN", "control")
    app = build_application()
    endpoint = _endpoint(app)
    from importlib.resources import files

    registry = __import__("json").loads(files("tsunagou.protocol_data").joinpath("registry", "commands.json").read_text(encoding="utf-8"))

    def call(
        kind: str, payload: dict[str, Any], authorization: str, *, session_id: str | None = None, epoch: int | None = None
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
            {
                "kind": "worker",
                "installation_id": name,
                "conversation_evidence": {"conversation_id": name},
            },
            "control",
        )
        return call(
            "agent.enroll",
            {
                "installation_id": name,
                "conversation_evidence": {"conversation_id": name},
                "probe_payload": _baseline(),
            },
            ticket["secret"],
        )

    main, worker = enroll("actions-main"), enroll("actions-worker")
    call("authority.appoint", {"agent_id": main["agent_id"]}, "control")

    def agent_call(kind: str, payload: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
        return call(kind, payload, receipt["secret_token"], session_id=receipt["session_id"], epoch=receipt["connection_epoch"])

    task = agent_call("task.create", {"title": "before", "objective": "old"}, main)
    agent_call("task.update_plan", {"task_id": task["task_id"], "title": "after", "objective": "new"}, main)
    agent_call("task.ready", {"task_id": task["task_id"]}, main)
    agent_call("task.publish", {"task_id": task["task_id"]}, main)
    other = agent_call("task.create", {"title": "blocked-by", "objective": "edge"}, main)
    agent_call(
        "task.edge.add",
        {
            "source_task_id": task["task_id"],
            "target_task_id": other["task_id"],
            "kind": "blocks",
        },
        main,
    )
    agent_call(
        "task.edge.remove",
        {
            "source_task_id": task["task_id"],
            "target_task_id": other["task_id"],
        },
        main,
    )
    claimed = agent_call(
        "task.begin",
        {"task_id": task["task_id"], "expected_task_revision": app.state.state_runtime.tasks.tasks[task["task_id"]].revision},
        worker,
    )
    scope = agent_call(
        "task.scope.request",
        {
            "task_id": task["task_id"],
            "attempt_id": claimed["attempt_id"],
            "requested_scope": {"roots": ["service-2"]},
            "reason": "second scope",
        },
        worker,
    )
    agent_call(
        "task.scope.resolve",
        {
            "scope_request_id": scope["scope_request_id"],
            "choice": "reject",
            "reason": "outside ceiling",
        },
        main,
    )
    agent_call("task.block", {"task_id": task["task_id"], "attempt_id": claimed["attempt_id"], "reason": "wait for user"}, worker)
    recovered = agent_call(
        "task.recover",
        {
            "task_id": task["task_id"],
            "expected_attempt_id": claimed["attempt_id"],
            "disposition": "reopen",
        },
        main,
    )
    assert recovered["status"] == "open"

    cancel_task = agent_call("task.create", {"title": "cancel", "objective": "stop"}, main)
    agent_call("task.ready", {"task_id": cancel_task["task_id"]}, main)
    agent_call("task.publish", {"task_id": cancel_task["task_id"]}, main)
    cancel_attempt = agent_call(
        "task.begin",
        {"task_id": cancel_task["task_id"], "expected_task_revision": app.state.state_runtime.tasks.tasks[cancel_task["task_id"]].revision},
        worker,
    )
    agent_call("task.cancel_request", {"task_id": cancel_task["task_id"], "reason": "user stop"}, main)
    cancelled = agent_call(
        "task.cancel_ack",
        {
            "task_id": cancel_task["task_id"],
            "attempt_id": cancel_attempt["attempt_id"],
            "stop_evidence": {"fixture": True},
            "reason": "stopped",
        },
        worker,
    )
    assert cancelled["status"] == "cancelled"


def test_cognition_discrepancy_and_contract_resolution_are_public_and_scoped(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    ProjectRegistry.initialize(tmp_path, name="Cognition", objective="negotiation")
    state_dir = tmp_path / ".tsunagou" / "local"
    monkeypatch.setenv("TSUNAGOU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("TSUNAGOU_STATE_DIR", str(state_dir))
    monkeypatch.setenv("TSUNAGOU_CONTROL_TOKEN", "control")
    app = build_application()
    endpoint = _endpoint(app)
    from importlib.resources import files

    registry = __import__("json").loads(files("tsunagou.protocol_data").joinpath("registry", "commands.json").read_text(encoding="utf-8"))

    def call(
        kind: str, payload: dict[str, Any], authorization: str, *, session_id: str | None = None, epoch: int | None = None
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
            {
                "kind": "worker",
                "installation_id": name,
                "conversation_evidence": {"conversation_id": name},
            },
            "control",
        )
        return call(
            "agent.enroll",
            {
                "installation_id": name,
                "conversation_evidence": {"conversation_id": name},
                "probe_payload": _baseline(),
            },
            ticket["secret"],
        )

    main, worker = enroll("cognition-main"), enroll("cognition-worker")
    call("authority.appoint", {"agent_id": main["agent_id"]}, "control")

    def agent_call(kind: str, payload: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
        return call(kind, payload, receipt["secret_token"], session_id=receipt["session_id"], epoch=receipt["connection_epoch"])

    task = agent_call("task.create", {"title": "cognition", "objective": "compare"}, main)
    agent_call("task.ready", {"task_id": task["task_id"]}, main)
    agent_call("task.publish", {"task_id": task["task_id"]}, main)
    claimed = agent_call(
        "task.begin",
        {"task_id": task["task_id"], "expected_task_revision": app.state.state_runtime.tasks.tasks[task["task_id"]].revision},
        worker,
    )
    report = agent_call(
        "cognition.report",
        {
            "task_id": task["task_id"],
            "attempt_id": claimed["attempt_id"],
            "claims": [{"subject_key": "design.choice", "value": "worker", "claim_type": "literal", "equality_key": "design.choice"}],
        },
        worker,
    )
    discrepancy = agent_call(
        "discrepancy.create",
        {
            "subject_ref": "design.choice",
            "report_refs": [report["report_id"]],
            "severity": "hard",
            "summary": "different design readings",
            "participants": [worker["agent_id"]],
            "affected_actions": ["task.begin"],
        },
        worker,
    )
    advanced = agent_call(
        "discrepancy.advance",
        {
            "discrepancy_id": discrepancy["discrepancy_id"],
            "status": "clarifying",
        },
        worker,
    )
    assert advanced["status"] == "clarifying"
    resolved = agent_call(
        "discrepancy.resolve",
        {
            "discrepancy_id": discrepancy["discrepancy_id"],
            "kind": "consensus",
        },
        main,
    )
    assert resolved["status"] == "resolved"

    proposal = agent_call(
        "contract.propose",
        {
            "payload": {"subject": "design.choice"},
            "participants_required": [{"slot": "worker", "agent_id": worker["agent_id"]}],
        },
        worker,
    )
    withdrawn = agent_call(
        "contract.withdraw",
        {
            "proposal_id": proposal["proposal_id"],
            "reason": "replace with clarified proposal",
        },
        worker,
    )
    assert withdrawn["status"] == "withdrawn"

    rejected_proposal = agent_call(
        "contract.propose",
        {
            "payload": {"subject": "design.choice", "value": "main"},
            "participants_required": [{"slot": "main", "agent_id": main["agent_id"]}],
        },
        worker,
    )
    rejected = agent_call(
        "contract.reject",
        {
            "proposal_id": rejected_proposal["proposal_id"],
            "proposal_digest": rejected_proposal["digest"],
            "reason": "needs another review",
        },
        main,
    )
    assert rejected["status"] == "rejected"
