import os
import subprocess
from pathlib import Path

import pytest

from tsunagou.modules.workspaces import GitReadOnlyPort, WorkspaceService, _normalise_validation_metadata
from tsunagou.shared_kernel.digests import canonical_digest


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


def test_main_integration_request_is_pending_and_no_push() -> None:
    service = WorkspaceService()
    decision = worktree_decision(service)
    workspace = service.request_workspace(
        decision.decision_id, root_binding_refs=["root"], repository_id="repo",
        current_main_id="main",
    )
    baseline = service.record_baseline(
        workspace.workspace_id, head_commit="abc", branch="main", index_digest="i",
        tracked_state_digest="t", untracked_summary=[], root_identities=["r"],
    )
    result = service.record_result(
        workspace.workspace_id, attempt_id="a", baseline_digest=baseline.digest,
        commit_refs=["worker-commit"], patch_artifact_ref=None,
        changed_paths=["src/main.py"], untracked_summary=[], validation_refs=["tests"],
    )
    request = service.request_integration(
        source_result_ref=result.manifest_id, target_repository_id="repo",
        target_baseline_digest="target-baseline", plan_digest="plan", reason="reviewed",
        actor_main_id="main",
    )
    assert request.status == "pending"
    assert request.action == "integrate"
    assert request.parameters["push_allowed"] is False


def test_scan_root_digest_changes_when_same_path_content_changes(tmp_path) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / "tracked.py").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "initial"], cwd=tmp_path, check=True)
    service = WorkspaceService()
    first = service.scan_root(tmp_path)
    (tmp_path / "tracked.py").write_text("two\n", encoding="utf-8")
    second = service.scan_root(tmp_path)
    assert first["tracked_state_digest"] != second["tracked_state_digest"]
    assert second["changed_paths"] == ["tracked.py"]


def test_scan_root_excludes_tsunagou_private_state(tmp_path) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / "app.py").write_text("print(1)\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "initial"], cwd=tmp_path, check=True)
    private = tmp_path / ".tsunagou" / "local"
    private.mkdir(parents=True)
    (private / "secret.json").write_text("secret-sentinel", encoding="utf-8")
    observed = WorkspaceService().scan_root(tmp_path)
    assert all(not path.startswith(".tsunagou") for path in observed["changed_paths"])


@pytest.mark.parametrize("private_dir", [".tsunagou", ".TSUNAGOU"])
def test_patch_cannot_reinclude_tracked_private_credential_files(tmp_path, private_dir: str) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    private = tmp_path / private_dir / "local"
    private.mkdir(parents=True)
    (private / "session.json").write_text('{"secret_token":"old-private-value"}', encoding="utf-8")
    (tmp_path / "app.py").write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "-f", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "fixture"], cwd=tmp_path, check=True)
    (private / "session.json").write_text('{"secret_token":"new-private-sentinel"}', encoding="utf-8")
    subprocess.run(["git", "add", "-f", f"{private_dir}/local/session.json"], cwd=tmp_path, check=True)
    (private / "ticket.json").write_text('{"secret":"untracked-private-sentinel"}', encoding="utf-8")
    service = WorkspaceService()
    # Private-only changes must not cause a global fallback diff.
    only_private = service.scan_root(tmp_path, artifact_root=tmp_path / ".tsunagou/artifacts")
    assert only_private["patch_artifact_ref"] is None
    assert only_private["untracked_summary"] == []
    (tmp_path / "app.py").write_text("after\n", encoding="utf-8")
    observed = service.scan_root(tmp_path, artifact_root=tmp_path / ".tsunagou/artifacts")
    patch = (tmp_path / ".tsunagou/artifacts" / (observed["patch_artifact_ref"].replace(":", "_") + ".patch")).read_bytes()
    assert b"+after" in patch
    assert b"private" not in patch and b".tsunagou" not in patch
    assert observed["changed_paths"] == ["app.py"]


def test_scan_scope_filters_outside_paths_and_patch_bytes(tmp_path) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("before\n", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("before-secret\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "initial"], cwd=tmp_path, check=True)
    (tmp_path / "src" / "app.py").write_text("after\n", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("after-secret-sentinel\n", encoding="utf-8")
    observed = WorkspaceService().scan_root(tmp_path, allowed_paths=["src"], artifact_root=tmp_path / "artifacts")
    assert observed["changed_paths"] == ["src/app.py"]
    assert observed["scope_paths"] == ["src"]
    patch = (tmp_path / "artifacts" / (observed["patch_artifact_ref"].replace(":", "_") + ".patch")).read_bytes()
    assert b"after\n" in patch
    assert b"outside" not in patch and b"secret-sentinel" not in patch


def test_scan_symlink_records_link_without_reading_target(tmp_path) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    target = tmp_path.parent / "tsunagou-scan-secret-target.txt"
    target.write_text("outside-target-secret-sentinel\n", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")
    observed = WorkspaceService().scan_root(tmp_path)
    entry = next(item for item in observed["content_entries"] if item["path"] == "link.txt")
    assert entry["kind"] == "symlink"
    assert "outside-target-secret-sentinel" not in str(entry)


def test_result_scope_and_validation_receipt_do_not_self_elevate() -> None:
    service = WorkspaceService()
    decision = service.record_isolation_decision(
        task_id="task", attempt_id="attempt", driver_kind="shared", input_snapshot={},
        hard_constraints=set(), evidence_refs=[], decided_by="main",
    )
    workspace = service.request_workspace(decision.decision_id, root_binding_refs=[], scope_paths=["src"])
    baseline = service.record_baseline(
        workspace.workspace_id, head_commit=None, branch=None, index_digest="i",
        tracked_state_digest="t", untracked_summary=[], root_identities=[],
    )
    with pytest.raises(PermissionError, match="scope"):
        service.record_result(
            workspace.workspace_id, attempt_id="attempt", baseline_digest=baseline.digest,
            commit_refs=["commit"], patch_artifact_ref=None, changed_paths=["outside/file.py"],
            untracked_summary=[], validation_refs=[],
        )
    result = service.record_result(
        workspace.workspace_id, attempt_id="attempt", baseline_digest=baseline.digest,
        commit_refs=["commit"], patch_artifact_ref=None, changed_paths=["src/file.py"],
        untracked_summary=[], validation_refs=[], evidence_level="system_verified",
        validation_metadata=[{
            "started_at": "2026-09-27T17:00:00Z", "finished_at": "2026-09-27T17:00:01Z",
            "command": "pytest -q", "exit_code": 0, "tool": "pytest", "tool_version": "8",
            "workspace_digest": "sha256:" + "1" * 64, "evidence_level": "system_verified",
        }],
    )
    assert result.validation_metadata[0]["evidence_level"] == "agent_asserted"
    assert result.validation_metadata[0]["reported_evidence_level"] == "system_verified"


def test_full_tree_digest_changes_between_clean_commits(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    file = tmp_path / "app.py"
    file.write_text("first\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "first"], cwd=tmp_path, check=True)
    service = WorkspaceService()
    first = service.scan_root(tmp_path)
    file.write_text("second\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "second"], cwd=tmp_path, check=True)
    second = service.scan_root(tmp_path)
    assert first["changed_paths"] == second["changed_paths"] == []
    assert first["tracked_state_digest"] != second["tracked_state_digest"]
    assert first["index_digest"] != second["index_digest"]
    assert second["content_entries"][0]["path"] == "app.py"


def test_index_digest_hashes_blob_even_when_working_content_is_identical(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    file = tmp_path / "app.py"
    file.write_text("initial\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "initial"], cwd=tmp_path, check=True)
    service = WorkspaceService()
    scans = []
    for staged in ("first staged\n", "second staged\n"):
        file.write_text(staged, encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
        file.write_text("same working bytes\n", encoding="utf-8")
        scans.append(service.scan_root(tmp_path))
    assert scans[0]["tracked_state_digest"] == scans[1]["tracked_state_digest"]
    assert scans[0]["index_digest"] != scans[1]["index_digest"]


def test_nul_rename_keeps_destination_and_source(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    original = "old name 文件.txt"
    destination = "new name 文件.txt"
    (tmp_path / original).write_text("content\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "initial"], cwd=tmp_path, check=True)
    subprocess.run(["git", "mv", original, destination], cwd=tmp_path, check=True)
    observed = WorkspaceService().scan_root(tmp_path, include_patch=True)
    assert observed["changed_paths"] == sorted([original, destination])
    assert {entry["path"]: entry["kind"] for entry in observed["content_entries"]} == {
        original: "missing", destination: "file",
    }
    assert b"rename from" in observed["patch_bytes"]


@pytest.mark.skipif(os.name == "nt", reason="Windows filenames cannot contain newlines")
def test_nul_paths_preserve_newlines(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    name = "line\nbreak.txt"
    (tmp_path / name).write_text("content\n", encoding="utf-8")
    observed = WorkspaceService().scan_root(tmp_path, include_patch=True)
    assert observed["changed_paths"] == [name]
    assert observed["content_entries"][0]["path"] == name


def test_scan_bound_git_subdirectory_does_not_read_siblings(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    root = tmp_path / "service"
    root.mkdir()
    (root / "app.py").write_text("content\n", encoding="utf-8")
    (tmp_path / "private.txt").write_text("outside-secret-sentinel\n", encoding="utf-8")
    observed = WorkspaceService().scan_root(root, include_patch=True)
    assert observed["changed_paths"] == ["app.py"]
    assert observed["content_entries"][0]["path"] == "app.py"
    assert b"outside-secret-sentinel" not in observed["patch_bytes"]


def test_custom_artifact_directory_cannot_reenter_scan(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / "app.py").write_text("content\n", encoding="utf-8")
    artifact_root = tmp_path / "exports"
    service = WorkspaceService()
    first = service.scan_root(tmp_path, artifact_root=artifact_root)
    second = service.scan_root(tmp_path, artifact_root=artifact_root)
    assert first == second
    assert len(list(artifact_root.glob("*.patch"))) == 1


def test_nested_private_state_is_excluded_from_tree_index_and_patch(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    private = tmp_path / "service" / ".TSUNAGOU"
    private.mkdir(parents=True)
    (private / "credentials.json").write_text("private-secret-sentinel", encoding="utf-8")
    (tmp_path / "app.py").write_text("safe\n", encoding="utf-8")
    subprocess.run(["git", "add", "-f", "."], cwd=tmp_path, check=True)
    observed = WorkspaceService().scan_root(tmp_path, include_patch=True)
    assert observed["changed_paths"] == ["app.py"]
    assert [entry["path"] for entry in observed["index_entries"]] == ["app.py"]
    assert b"private-secret-sentinel" not in observed["patch_bytes"]


def test_directory_scan_does_not_follow_links_or_collect_private_state(tmp_path: Path) -> None:
    root = tmp_path / "plain"
    root.mkdir()
    (root / "app.py").write_text("safe\n", encoding="utf-8")
    private = root / ".tsunagou"
    private.mkdir()
    (private / "secret.txt").write_text("private-secret-sentinel", encoding="utf-8")
    target = tmp_path / "outside.txt"
    target.write_text("target-secret-sentinel", encoding="utf-8")
    link = root / "link"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")
    observed = WorkspaceService().scan_root(root, include_patch=True)
    assert observed["head_commit"] is None
    assert observed["changed_paths"] == ["app.py", "link"]
    assert b"safe" in observed["patch_bytes"]
    assert b"sentinel" not in observed["patch_bytes"]
    assert str(target).encode() not in observed["patch_bytes"]


def test_unreadable_file_is_observed_but_never_passed_to_patch(tmp_path: Path, monkeypatch) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    candidate = tmp_path / "secret.txt"
    candidate.write_text("secret-sentinel", encoding="utf-8")
    original = Path.read_bytes

    def read_bytes(path: Path) -> bytes:
        if path == candidate:
            raise PermissionError("fixture unreadable")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    observed = WorkspaceService().scan_root(tmp_path, include_patch=True)
    assert observed["content_entries"][0]["kind"] == "unreadable"
    assert observed["patch_bytes"] == b""


def test_corrupt_existing_artifact_is_rejected(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / "app.py").write_text("safe\n", encoding="utf-8")
    artifacts = tmp_path / ".tsunagou" / "artifacts"
    service = WorkspaceService()
    service.scan_root(tmp_path, artifact_root=artifacts)
    next(artifacts.glob("*.patch")).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="artifact_content_conflict"):
        service.scan_root(tmp_path, artifact_root=artifacts)


def test_tracked_path_through_link_cannot_read_or_patch_outside_scope(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(["git", "init", "--quiet", str(repository)], check=True)
    directory = repository / "src" / "linked"
    directory.mkdir(parents=True)
    (directory / "data.txt").write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "initial"], cwd=repository, check=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "data.txt").write_text("outside-secret-sentinel\n", encoding="utf-8")
    (directory / "data.txt").unlink()
    directory.rmdir()
    try:
        directory.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")
    observed = WorkspaceService().scan_root(repository, allowed_paths=["src"], include_patch=True)
    entries = {entry["path"]: entry for entry in observed["content_entries"]}
    assert entries["src/linked/data.txt"]["kind"] == "link_outside"
    assert b"outside-secret-sentinel" not in observed["patch_bytes"]
    assert b"data.txt" not in observed["patch_bytes"]


def test_scope_uses_literal_paths_and_index_excludes_other_names(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / "file[1].txt").write_text("safe-content\n", encoding="utf-8")
    (tmp_path / "file1.txt").write_text("outside-secret-sentinel\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    observed = WorkspaceService().scan_root(tmp_path, allowed_paths=["file[1].txt"], include_patch=True)
    assert observed["changed_paths"] == ["file[1].txt"]
    assert [entry["path"] for entry in observed["index_entries"]] == ["file[1].txt"]
    assert b"safe-content" in observed["patch_bytes"]
    assert b"outside-secret-sentinel" not in observed["patch_bytes"]


@pytest.mark.skipif(os.name == "nt", reason="Windows paths are case-insensitive")
def test_scope_does_not_casefold_distinct_posix_directories(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    for name in ("src", "SRC"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "app.py").write_text(name, encoding="utf-8")
    observed = WorkspaceService().scan_root(tmp_path, allowed_paths=["src"])
    assert observed["changed_paths"] == ["src/app.py"]


@pytest.mark.skipif(os.name != "nt", reason="Windows junction regression")
def test_windows_junction_cannot_export_external_content(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(["git", "init", "--quiet", str(repository)], check=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("junction-secret-sentinel", encoding="utf-8")
    link = repository / "junction"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True)
    observed = WorkspaceService().scan_root(repository, include_patch=True)
    assert b"junction-secret-sentinel" not in observed["patch_bytes"]
    assert all(entry["kind"] in {"link_outside", "special"} for entry in observed["content_entries"])


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO regression")
def test_special_fifo_is_observed_without_reading_or_patching(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "fifo")
    observed = WorkspaceService().scan_root(tmp_path, include_patch=True)
    assert observed["content_entries"][0]["kind"] == "special"
    assert observed["patch_bytes"] == b""


def test_symlink_only_result_preserves_observation_without_exporting_target(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    service = WorkspaceService()
    decision = service.record_isolation_decision(
        task_id="task", attempt_id="attempt", driver_kind="shared", input_snapshot={},
        hard_constraints=set(), evidence_refs=[], decided_by="main",
    )
    workspace = service.request_workspace(decision.decision_id, root_binding_refs=["root"])
    before = service.scan_root(root)
    baseline = service.record_baseline(
        workspace.workspace_id, head_commit=None, branch=None, index_digest=before["index_digest"],
        tracked_state_digest=before["tracked_state_digest"], untracked_summary=[], root_identities=["root"],
        root_observations=[{"root_id": "root", **before}],
    )
    target = tmp_path / "private-target.txt"
    target.write_text("outside-secret-sentinel", encoding="utf-8")
    try:
        (root / "link").symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")
    observed = service.scan_root(root, include_patch=True)
    assert observed.pop("patch_bytes") == b""
    result = service.record_result(
        workspace.workspace_id, attempt_id="attempt", baseline_digest=baseline.digest,
        commit_refs=[], patch_artifact_ref=None, changed_paths=observed["changed_paths"],
        untracked_summary=observed["untracked_summary"], validation_refs=[],
        observed_state_digest=observed["tracked_state_digest"], submitted_by="worker",
        evidence_level="system_verified", root_observations=[{"root_id": "root", **observed}],
    )
    assert result.patch_artifact_ref is None
    assert result.root_observations[0]["content_entries"][0]["kind"] == "symlink"
    assert "outside-secret-sentinel" not in str(result)
    assert str(target) not in str(result)
    with pytest.raises(ValueError, match="requires_patch"):
        service.record_result(
            workspace.workspace_id, attempt_id="attempt", baseline_digest=baseline.digest,
            commit_refs=[], patch_artifact_ref=None, changed_paths=["regular.txt"],
            untracked_summary=[], validation_refs=[], root_observations=[{"root_id": "root", **observed}],
        )


def receipt() -> dict:
    return {
        "started_at": "2026-09-27T17:00:00Z", "finished_at": "2026-09-27T17:00:01Z",
        "command": "pytest -q", "exit_code": 0, "tool": "pytest", "tool_version": "8",
        "workspace_digest": "sha256:" + "a" * 64,
    }


@pytest.mark.parametrize(("field", "value"), [
    ("started_at", 1), ("finished_at", "2026-09-27T16:59:00Z"),
    ("finished_at", "2026-09-27T17:00:01"), ("exit_code", True),
    ("workspace_digest", "not-a-workspace-hash"),
    ("stdout_digest", "raw-secret-sentinel"), ("stderr_digest", "sha256:not-hex"),
])
def test_validation_receipts_reject_malformed_times_and_raw_output(field: str, value) -> None:
    item = {**receipt(), field: value}
    with pytest.raises(ValueError):
        _normalise_validation_metadata([item])


@pytest.mark.parametrize("reported", ["host_observed", "system_verified", "user_confirmed"])
def test_self_reported_receipts_remain_weak_and_include_tool_version_digest(reported: str) -> None:
    item = {**receipt(), "evidence_level": reported, "stdout_digest": "sha256:" + "b" * 64}
    observed = _normalise_validation_metadata([item])[0]
    assert observed["evidence_level"] == "agent_asserted"
    assert observed["reported_evidence_level"] == reported
    assert observed["started_at"] == "2026-09-27T17:00:00.000Z"
    assert observed["tool_version_digest"] == canonical_digest({"tool": "pytest", "version": "8"})
