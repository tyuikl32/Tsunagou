import pytest

from tsunagou.modules.workspaces import GitReadOnlyPort, WorkspaceService


def worktree_decision(service: WorkspaceService):
    return service.record_isolation_decision(
        task_id="t", attempt_id="a", driver_kind="worktree",
        input_snapshot={"risk": "medium"}, hard_constraints={"single_repository"},
        evidence_refs=[], decided_by="main",
    )


def test_worktree_mutation_is_a_main_request_and_no_main_stays_pending() -> None:
    service = WorkspaceService()
    decision = worktree_decision(service)
    workspace = service.request_workspace(
        decision.decision_id, root_binding_refs=["root"], repository_id="repo",
        current_main_id=None,
    )
    request = next(iter(service.git_requests.values()))
    assert workspace.status == "requested"
    assert request.status == "pending"
    with pytest.raises(PermissionError):
        service.report_git_action(request.request_id, actor_main_id="worker", evidence={}, success=True)


def test_git_port_rejects_mutation_and_network_commands() -> None:
    for args in (["commit", "-m", "x"], ["push", "origin"], ["worktree", "add", "x"], ["show", "https://example.com/repo"]):
        with pytest.raises(PermissionError):
            GitReadOnlyPort.validate(list(args))
    GitReadOnlyPort.validate(["status", "--porcelain=v2"])
    GitReadOnlyPort.validate(["rev-parse", "HEAD"])


def test_dirty_baseline_head_change_and_cleanup_barriers() -> None:
    service = WorkspaceService()
    decision = worktree_decision(service)
    workspace = service.request_workspace(
        decision.decision_id, root_binding_refs=["root"], repository_id="repo",
        current_main_id="main",
    )
    with pytest.raises(ValueError, match="not_clean"):
        service.record_baseline(
            workspace.workspace_id, head_commit="abc", branch="main", index_digest="i",
            tracked_state_digest="t", untracked_summary=["x"], root_identities=["r"], dirty=True,
        )
    baseline = service.record_baseline(
        workspace.workspace_id, head_commit="abc", branch="main", index_digest="i",
        tracked_state_digest="t", untracked_summary=[], root_identities=["r"],
    )
    with pytest.raises(ValueError, match="head_changed"):
        service.verify_integration_target(baseline.manifest_id, "def")
    with pytest.raises(PermissionError, match="dirty"):
        service.request_cleanup(
            workspace.workspace_id, actor_main_id="main", task_terminal=True,
            checkpoint_ref="checkpoint", dirty=True,
        )
