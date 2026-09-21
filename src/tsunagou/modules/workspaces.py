"""Isolation decisions, workspace manifests, and main-owned Git requests."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tsunagou.shared_kernel.digests import canonical_digest
from tsunagou.shared_kernel.ids import new_id


@dataclass(frozen=True, slots=True)
class DriverSpec:
    kind: str
    version: str
    capabilities: frozenset[str]
    required_evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IsolationDecision:
    decision_id: str
    task_id: str
    attempt_id: str
    driver_kind: str
    input_digest: str
    hard_constraints: tuple[str, ...]
    evidence_refs: tuple[dict[str, Any], ...]
    decided_by: str
    decision_digest: str


@dataclass(slots=True)
class Workspace:
    workspace_id: str
    attempt_id: str
    decision_id: str
    driver_kind: str
    root_binding_refs: tuple[str, ...]
    repository_id: str | None = None
    external_locator: str | None = None
    status: str = "requested"
    baseline_manifest_id: str | None = None
    result_manifest_id: str | None = None
    revision: int = 1


@dataclass(slots=True)
class GitActionRequest:
    request_id: str
    workspace_id: str
    repository_id: str
    action: str
    requested_main_id: str | None
    exact_input_digest: str
    parameters: dict[str, Any]
    status: str = "pending"
    evidence: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class BaselineManifest:
    manifest_id: str
    workspace_id: str
    head_commit: str | None
    branch: str | None
    index_digest: str
    tracked_state_digest: str
    untracked_summary: tuple[str, ...]
    root_identities: tuple[str, ...]
    digest: str


@dataclass(frozen=True, slots=True)
class ResultManifest:
    manifest_id: str
    workspace_id: str
    attempt_id: str
    baseline_digest: str
    commit_refs: tuple[str, ...]
    patch_artifact_ref: str | None
    changed_paths: tuple[str, ...]
    untracked_summary: tuple[str, ...]
    validation_refs: tuple[str, ...]
    digest: str
    observed_state_digest: str | None = None
    baseline_conflict: bool = False


class GitReadOnlyPort:
    READ_ONLY_COMMANDS = {
        "rev-parse", "status", "diff", "ls-files", "show", "cat-file", "log", "branch",
    }
    NETWORK_OR_MUTATION = {
        "add", "apply", "checkout", "clone", "commit", "fetch", "merge", "pull", "push",
        "rebase", "reset", "restore", "switch", "tag", "worktree",
    }

    @classmethod
    def validate(cls, args: list[str]) -> None:
        if not args or args[0] not in cls.READ_ONLY_COMMANDS or args[0] in cls.NETWORK_OR_MUTATION:
            raise PermissionError("git_command_not_read_only")
        lowered = " ".join(args).casefold()
        if any(value in lowered for value in ("http://", "https://", "ssh://", "git@", "--upload-pack")):
            raise PermissionError("network_git_forbidden")
        if args[0] == "status" and "--porcelain" not in lowered:
            raise PermissionError("status_requires_porcelain")

    def run(self, repository: str | Path, args: list[str]) -> str:
        self.validate(args)
        result = subprocess.run(
            ["git", *args], cwd=Path(repository), check=True, capture_output=True,
            text=True, timeout=15,
        )
        return result.stdout


class WorkspaceService:
    def __init__(self) -> None:
        self.drivers = {
            "shared": DriverSpec("shared", "1", frozenset({"multi_root", "dirty_baseline", "original_directory"}), ()),
            "worktree": DriverSpec("worktree", "1", frozenset({"single_repository", "clean_baseline"}), ("head_commit", "status")),
            "external": DriverSpec("external", "1", frozenset({"externally_prepared", "multi_root"}), ("locator", "capabilities")),
        }
        self.decisions: dict[str, IsolationDecision] = {}
        self.workspaces: dict[str, Workspace] = {}
        self.git_requests: dict[str, GitActionRequest] = {}
        self.baselines: dict[str, BaselineManifest] = {}
        self.results: dict[str, ResultManifest] = {}

    def list_driver_candidates(self, hard_constraints: set[str]) -> list[DriverSpec]:
        return [
            driver for driver in self.drivers.values()
            if hard_constraints.issubset(driver.capabilities)
        ]

    def record_isolation_decision(
        self, *, task_id: str, attempt_id: str, driver_kind: str,
        input_snapshot: dict[str, Any], hard_constraints: set[str],
        evidence_refs: list[dict[str, Any]], decided_by: str,
    ) -> IsolationDecision:
        candidates = {item.kind for item in self.list_driver_candidates(hard_constraints)}
        if driver_kind not in candidates:
            raise ValueError("driver_does_not_meet_hard_constraints")
        input_digest = canonical_digest(input_snapshot)
        body = {
            "task_id": task_id, "attempt_id": attempt_id, "driver_kind": driver_kind,
            "input_digest": input_digest, "hard_constraints": sorted(hard_constraints),
            "evidence_refs": evidence_refs, "decided_by": decided_by,
        }
        decision = IsolationDecision(
            new_id(), task_id, attempt_id, driver_kind, input_digest,
            tuple(sorted(hard_constraints)), tuple(evidence_refs), decided_by, canonical_digest(body),
        )
        self.decisions[decision.decision_id] = decision
        return decision

    def request_workspace(
        self, decision_id: str, *, root_binding_refs: list[str], repository_id: str | None = None,
        external_locator: str | None = None, current_main_id: str | None = None,
    ) -> Workspace:
        decision = self.decisions[decision_id]
        if decision.driver_kind == "worktree" and (repository_id is None or len(root_binding_refs) != 1):
            raise ValueError("worktree_requires_single_repository_root")
        workspace = Workspace(
            new_id(), decision.attempt_id, decision_id, decision.driver_kind,
            tuple(root_binding_refs), repository_id, external_locator,
        )
        self.workspaces[workspace.workspace_id] = workspace
        if decision.driver_kind == "worktree":
            request = GitActionRequest(
                new_id(), workspace.workspace_id, repository_id or "", "worktree_create",
                current_main_id, canonical_digest({"workspace_id": workspace.workspace_id, "decision": decision.decision_digest}),
                {"workspace_id": workspace.workspace_id, "repository_id": repository_id},
            )
            self.git_requests[request.request_id] = request
            workspace.status = "preparing" if current_main_id else "requested"
        elif decision.driver_kind == "external" and not external_locator:
            raise ValueError("external_locator_required")
        else:
            workspace.status = "preparing"
        return workspace

    def report_git_action(
        self, request_id: str, *, actor_main_id: str, evidence: dict[str, Any], success: bool,
    ) -> GitActionRequest:
        request = self.git_requests[request_id]
        if request.requested_main_id is None or request.requested_main_id != actor_main_id:
            raise PermissionError("current_main_required")
        request.evidence = evidence
        request.status = "reported" if success else "rejected"
        return request

    def record_baseline(
        self, workspace_id: str, *, head_commit: str | None, branch: str | None,
        index_digest: str, tracked_state_digest: str, untracked_summary: list[str],
        root_identities: list[str], dirty: bool = False,
    ) -> BaselineManifest:
        workspace = self.workspaces[workspace_id]
        if workspace.driver_kind == "worktree" and (dirty or untracked_summary or not head_commit):
            raise ValueError("worktree_baseline_not_clean")
        body = {
            "workspace_id": workspace_id, "head_commit": head_commit, "branch": branch,
            "index_digest": index_digest, "tracked_state_digest": tracked_state_digest,
            "untracked_summary": sorted(untracked_summary), "root_identities": sorted(root_identities),
        }
        manifest = BaselineManifest(
            new_id(), workspace_id, head_commit, branch, index_digest, tracked_state_digest,
            tuple(sorted(untracked_summary)), tuple(sorted(root_identities)), canonical_digest(body),
        )
        self.baselines[manifest.manifest_id] = manifest
        workspace.baseline_manifest_id = manifest.manifest_id
        workspace.status = "ready"
        workspace.revision += 1
        return manifest

    def scan_root(
        self, root: str | Path, *, artifact_root: str | Path | None = None,
    ) -> dict[str, Any]:
        """Read a real Git working tree without attributing edits to a writer.

        The scan is deliberately observational: it records current filesystem
        facts and never decides whether a changed path was written by a user or
        an Agent. A binary patch is stored content-addressed when Git can
        produce one, so a result can be retrieved and verified after restart.
        """
        repository = Path(root).expanduser().resolve()
        status_result = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=repository, check=True, capture_output=True, text=True, timeout=15,
        )
        status_lines = [line for line in status_result.stdout.splitlines() if line]
        head_result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repository, check=False,
            capture_output=True, text=True, timeout=15,
        )
        branch_result = subprocess.run(
            ["git", "branch", "--show-current"], cwd=repository, check=False,
            capture_output=True, text=True, timeout=15,
        )
        head = head_result.stdout.strip() or None
        branch = branch_result.stdout.strip() or None
        changed_paths: set[str] = set()
        untracked: set[str] = set()
        for line in status_lines:
            path = line[3:].strip()
            if " -> " in path:
                path = path.rsplit(" -> ", 1)[-1]
            path = path.strip('"')
            if not path:
                continue
            changed_paths.add(path)
            if line.startswith("??"):
                untracked.add(path)
        tracked_state_digest = canonical_digest({"status": status_lines})
        index_digest = canonical_digest({
            "cached": subprocess.run(
                ["git", "diff", "--cached", "--name-status"], cwd=repository,
                check=True, capture_output=True, text=True, timeout=15,
            ).stdout.splitlines(),
        })
        patch = self._patch_bytes(repository, sorted(changed_paths), status_lines)
        patch_ref = None
        if patch and artifact_root is not None:
            digest = "sha256:" + hashlib.sha256(patch).hexdigest()
            destination = Path(artifact_root) / (digest.replace(":", "_") + ".patch")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                destination.write_bytes(patch)
            patch_ref = digest
        return {
            "head_commit": head,
            "branch": branch,
            "index_digest": index_digest,
            "tracked_state_digest": tracked_state_digest,
            "untracked_summary": sorted(untracked),
            "changed_paths": sorted(changed_paths),
            "patch_artifact_ref": patch_ref,
            "dirty": bool(status_lines),
        }

    @staticmethod
    def _patch_bytes(repository: Path, paths: list[str], status_lines: list[str]) -> bytes:
        chunks: list[bytes] = []
        for args in (["git", "diff", "--binary"], ["git", "diff", "--cached", "--binary"]):
            result = subprocess.run(args, cwd=repository, check=True, capture_output=True, timeout=15)
            if result.stdout:
                chunks.append(result.stdout)
        for path in paths:
            if not any(line.startswith("??") and line[3:].strip().strip('"') == path for line in status_lines):
                continue
            result = subprocess.run(
                ["git", "diff", "--no-index", "--binary", "--", "/dev/null", path],
                cwd=repository, check=False, capture_output=True, timeout=15,
            )
            if result.stdout:
                chunks.append(result.stdout)
        return b"\n".join(chunks)

    def record_result(
        self, workspace_id: str, *, attempt_id: str, baseline_digest: str,
        commit_refs: list[str], patch_artifact_ref: str | None, changed_paths: list[str],
        untracked_summary: list[str], validation_refs: list[str],
        observed_state_digest: str | None = None, baseline_conflict: bool = False,
    ) -> ResultManifest:
        workspace = self.workspaces[workspace_id]
        baseline = self.baselines.get(workspace.baseline_manifest_id or "")
        if baseline is None or baseline.digest != baseline_digest or workspace.attempt_id != attempt_id:
            raise ValueError("workspace_baseline_or_attempt_mismatch")
        if not commit_refs and patch_artifact_ref is None and changed_paths:
            raise ValueError("uncommitted_result_requires_patch_artifact")
        body = {
            "workspace_id": workspace_id, "attempt_id": attempt_id, "baseline_digest": baseline_digest,
            "commit_refs": commit_refs, "patch_artifact_ref": patch_artifact_ref,
            "changed_paths": sorted(changed_paths), "untracked_summary": sorted(untracked_summary),
            "validation_refs": sorted(validation_refs), "observed_state_digest": observed_state_digest,
            "baseline_conflict": baseline_conflict,
        }
        result = ResultManifest(
            new_id(), workspace_id, attempt_id, baseline_digest, tuple(commit_refs), patch_artifact_ref,
            tuple(sorted(changed_paths)), tuple(sorted(untracked_summary)),
            tuple(sorted(validation_refs)), canonical_digest(body),
            observed_state_digest, baseline_conflict,
        )
        self.results[result.manifest_id] = result
        workspace.result_manifest_id = result.manifest_id
        workspace.status = "result_recorded"
        workspace.revision += 1
        return result

    def verify_integration_target(self, baseline_manifest_id: str, current_head: str | None) -> None:
        baseline = self.baselines[baseline_manifest_id]
        if baseline.head_commit != current_head:
            raise ValueError("integration_target_head_changed")

    def request_cleanup(
        self, workspace_id: str, *, actor_main_id: str | None, task_terminal: bool,
        checkpoint_ref: str | None, dirty: bool, user_force_approval: bool = False,
        last_copy: bool = False, recovery_evidence: bool = False,
    ) -> GitActionRequest | None:
        workspace = self.workspaces[workspace_id]
        if not task_terminal or checkpoint_ref is None:
            raise ValueError("cleanup_barrier_not_met")
        if dirty and not user_force_approval:
            raise PermissionError("dirty_cleanup_user_only")
        if last_copy and not (recovery_evidence or user_force_approval):
            raise PermissionError("last_copy_data_loss_risk")
        workspace.status = "cleanup_pending"
        if workspace.driver_kind != "worktree":
            return None
        request = GitActionRequest(
            new_id(), workspace_id, workspace.repository_id or "", "worktree_remove", actor_main_id,
            canonical_digest({"workspace_id": workspace_id, "checkpoint_ref": checkpoint_ref, "dirty": dirty}),
            {"workspace_id": workspace_id, "checkpoint_ref": checkpoint_ref},
        )
        self.git_requests[request.request_id] = request
        return request
