"""PT3: domain-bound artifact reads through the assembled HTTP application."""

from __future__ import annotations

import base64
import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
import uvicorn
from fastapi import HTTPException
from tests.unit.test_trace_audit import Runtime

from tsunagou.bootstrap.container import build_application
from tsunagou.modules.projects import ProjectRegistry
from tsunagou.modules.tasks import Attempt, Task


@pytest.fixture
def workspace_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    (tmp_path / ".git").mkdir()
    project_registry = ProjectRegistry.initialize(tmp_path, name="PT3", objective="artifact privacy")
    assert project_registry.project is not None
    project_id = project_registry.project.project_id
    monkeypatch.setenv("TSUNAGOU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("TSUNAGOU_PROJECT_ID", project_id)
    monkeypatch.setenv("TSUNAGOU_STATE_DIR", str(tmp_path / ".tsunagou/local"))
    monkeypatch.setenv("TSUNAGOU_CONTROL_TOKEN", "control")
    monkeypatch.delenv("TSUNAGOU_HOST_WAKE", raising=False)
    app = build_application()
    runtime = Runtime(app, project_id)
    owner, _ = runtime.enroll("owner")
    other, _ = runtime.enroll("other")
    main, _ = runtime.enroll("main")
    runtime.call("authority.appoint", {"agent_id": main["agent_id"]})
    state = app.state.state_runtime
    before = state.capture()
    state.tasks.tasks["task"] = Task("task", "fixture", "read", status="completed")
    state.tasks.attempts["attempt"] = Attempt("attempt", "task", owner["agent_id"], status="completed")
    decision = state.workspaces.record_isolation_decision(
        task_id="task",
        attempt_id="attempt",
        driver_kind="shared",
        input_snapshot={},
        hard_constraints=set(),
        evidence_refs=[],
        decided_by=main["agent_id"],
    )
    workspace = state.workspaces.request_workspace(decision.decision_id, root_binding_refs=[], scope_paths=["src"])
    baseline = state.workspaces.record_baseline(
        workspace.workspace_id,
        head_commit=None,
        branch=None,
        index_digest="i",
        tracked_state_digest="t",
        untracked_summary=[],
        root_identities=[],
    )
    content = b"diff --git a/src/app.py b/src/app.py\n+private-workspace-content\n"
    reference = state.artifacts.record_workspace_patch(
        content,
        workspace_id=workspace.workspace_id,
        actor=owner["agent_id"],
        project_id=project_id,
        lineage_id=state.lineage_id,
        scope_digest=workspace.scope_digest,
    )
    manifest = state.workspaces.record_result(
        workspace.workspace_id,
        attempt_id="attempt",
        baseline_digest=baseline.digest,
        commit_refs=[],
        patch_artifact_ref=reference.artifact_ref,
        changed_paths=["src/app.py"],
        untracked_summary=[],
        validation_refs=[],
        submitted_by=owner["agent_id"],
    )
    with runtime.db.transaction("fixture-workspace") as uow:
        state.persist(uow, actor_ref=owner["agent_id"], command_kind="fixture.workspace", before=before)
    try:
        yield {
            "runtime": runtime,
            "owner": owner,
            "other": other,
            "main": main,
            "reference": reference,
            "manifest": manifest,
            "content": content,
        }
    finally:
        runtime.db.release_process_lock()


def artifact_endpoint(runtime: Runtime) -> Any:
    return runtime.endpoint("/api/v1/artifacts/{artifact_ref:path}")


@contextmanager
def serve(app: Any) -> Iterator[str]:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        assert not thread.is_alive()


def test_actual_http_authorizes_domain_before_blob_and_restores_after_restart(workspace_runtime) -> None:
    fixture = workspace_runtime
    runtime = fixture["runtime"]
    reference = fixture["reference"]
    with serve(runtime.app) as base:
        url = f"{base}/api/v1/artifacts/{reference.artifact_ref}"
        with pytest.raises(HTTPError) as anonymous:
            urlopen(url, timeout=5)
        assert anonymous.value.code == 401
        other = fixture["other"]
        with pytest.raises(HTTPError) as cross_owner:
            urlopen(
                Request(
                    url,
                    headers={
                        "Authorization": f"Bearer {other['secret_token']}",
                        "Tsunagou-Session-Id": other["session_id"],
                        "Tsunagou-Connection-Epoch": str(other["connection_epoch"]),
                    },
                ),
                timeout=5,
            )
        assert cross_owner.value.code == 403
        for receipt in (fixture["owner"], fixture["main"]):
            with urlopen(
                Request(
                    url,
                    headers={
                        "Authorization": f"Bearer {receipt['secret_token']}",
                        "Tsunagou-Session-Id": receipt["session_id"],
                        "Tsunagou-Connection-Epoch": str(receipt["connection_epoch"]),
                    },
                ),
                timeout=5,
            ) as response:
                view = json.load(response)
            assert base64.b64decode(view["content_base64"]) == fixture["content"]
            assert view["workspace_result_ref"] == fixture["manifest"].manifest_id
        with pytest.raises(HTTPError) as bare_hash:
            urlopen(Request(f"{base}/api/v1/artifacts/sha256:{reference.digest}", headers={"Authorization": "Bearer control"}), timeout=5)
        assert bare_hash.value.code == 404
    rebuilt = build_application()
    try:
        restarted = Runtime(rebuilt, runtime.project_id)
        view = artifact_endpoint(restarted)(reference.artifact_ref, **runtime.credentials(fixture["owner"]))
        assert base64.b64decode(view["content_base64"]) == fixture["content"]
        persisted = rebuilt.state.state_runtime.workspaces.results[fixture["manifest"].manifest_id]
        assert persisted.scope_paths == ("src",)
        assert persisted.observed_at == fixture["manifest"].observed_at
        with pytest.raises(HTTPException) as denied:
            artifact_endpoint(restarted)(reference.artifact_ref, **runtime.credentials(fixture["other"]))
        assert denied.value.status_code == 403
    finally:
        rebuilt.state.project_database.release_process_lock()


@pytest.mark.parametrize(
    ("field", "status"),
    [
        ("project_id", 404),
        ("lineage_id", 404),
        ("domain_ref", 403),
        ("owner_actor", 403),
        ("scope_digest", 403),
    ],
)
def test_reference_bindings_are_checked_before_reading(workspace_runtime, field: str, status: int) -> None:
    runtime = workspace_runtime["runtime"]
    reference = workspace_runtime["reference"]
    setattr(reference, field, "different-binding")
    with pytest.raises(HTTPException) as failure:
        artifact_endpoint(runtime)(reference.artifact_ref, **runtime.credentials())
    assert failure.value.status_code == status


def test_private_recipient_boundary_applies_to_main_and_user(workspace_runtime) -> None:
    fixture = workspace_runtime
    runtime = fixture["runtime"]
    reference = fixture["reference"]
    reference.recipient_agent_id = fixture["owner"]["agent_id"]
    for receipt in (fixture["main"], None):
        with pytest.raises(HTTPException) as denied:
            artifact_endpoint(runtime)(reference.artifact_ref, **runtime.credentials(receipt))
        assert denied.value.status_code == 403
    assert artifact_endpoint(runtime)(reference.artifact_ref, **runtime.credentials(fixture["owner"]))["content_base64"]


def test_corrupt_blob_returns_explicit_unavailable_without_content(workspace_runtime) -> None:
    fixture = workspace_runtime
    runtime = fixture["runtime"]
    reference = fixture["reference"]
    service = runtime.app.state.state_runtime.artifacts
    path = service.storage_dir / service.blobs[reference.digest].local_relative_path
    path.write_bytes(b"corrupt-secret-sentinel")
    with pytest.raises(HTTPException) as failure:
        artifact_endpoint(runtime)(reference.artifact_ref, **runtime.credentials())
    assert failure.value.status_code == 409
    assert failure.value.detail == {"code": "artifact_unavailable_or_corrupt"}
