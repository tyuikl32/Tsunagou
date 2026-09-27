from pathlib import Path

import pytest

from tsunagou.application.workspace_evidence import WorkspaceEvidence
from tsunagou.modules.projects import ProjectRegistry
from tsunagou.modules.tasks import Task
from tsunagou.modules.workspaces import WorkspaceService


def fixture(tmp_path: Path):
    project = tmp_path / "coordination"
    (project / ".git").mkdir(parents=True)
    registry = ProjectRegistry.initialize(project, name="scope", objective="test")
    paths = [tmp_path / "external-one", tmp_path / "external-two"]
    ids = []
    for index, path in enumerate(paths):
        (path / "src").mkdir(parents=True)
        (path / "src" / "same.txt").write_text(f"root {index}", encoding="utf-8")
        (path / "outside.txt").write_text("PRIVATE-OUTSIDE-SCOPE", encoding="utf-8")
        ids.append(registry.register_root(f"root-{index}", path))
    task = Task("task", "scope", "read", execution_scope={"resources": [
        {"kind": "path", "root_id": root_id, "segments": ["src"], "mode": "exclusive_write"}
        for root_id in ids
    ]})
    service = WorkspaceService()
    evidence = WorkspaceEvidence(service, registry, str(project))
    roots = evidence.resolve_scope(task, [])
    decision = service.record_isolation_decision(task_id="task", attempt_id="attempt", driver_kind="shared",
        input_snapshot={}, hard_constraints=set(), evidence_refs=[], decided_by="main")
    workspace = service.request_workspace(decision.decision_id, root_binding_refs=ids,
        scope_paths=evidence.virtual_paths(roots), scope_roots=roots)
    return registry, paths, ids, task, evidence, workspace


def test_external_multiple_roots_use_task_scope_and_unambiguous_paths(tmp_path: Path) -> None:
    registry, paths, ids, task, evidence, workspace = fixture(tmp_path)
    observation = evidence.scan(workspace, task, include_patch=True)
    assert set(observation["changed_paths"]) == {root_id + "/src/same.txt" for root_id in ids}
    assert b"PRIVATE-OUTSIDE-SCOPE" not in observation["patch_bytes"]
    assert all(str(path) not in str(workspace.scope_roots) for path in paths)
    (paths[1] / "src" / "same.txt").write_text("edited", encoding="utf-8")
    assert observation["tracked_state_digest"] != evidence.scan(workspace, task)["tracked_state_digest"]
    task.execution_scope = {"roots": [ids[0]]}
    with pytest.raises(PermissionError, match="scope"):
        evidence.scan(workspace, task)


def test_bound_root_cannot_expand_scope_and_rebind_invalidates_workspace(tmp_path: Path) -> None:
    registry, paths, ids, task, evidence, workspace = fixture(tmp_path)
    third = registry.register_root("not-authorized", paths[0])
    with pytest.raises(PermissionError, match="scope"):
        evidence.resolve_scope(task, [third])
    registry.bind_root(ids[0], paths[1])
    with pytest.raises(PermissionError, match="scope_changed"):
        evidence.scan(workspace, task)


@pytest.mark.parametrize("scope", [{"resources": "all"}, {"resources": ["all"]}, {"roots": "all"}])
def test_invalid_scope_shape_fails_as_input_error(tmp_path: Path, scope) -> None:
    _, _, _, task, evidence, _ = fixture(tmp_path)
    task.execution_scope = scope
    with pytest.raises(ValueError, match="invalid_task_execution_scope"):
        evidence.resolve_scope(task, [])
