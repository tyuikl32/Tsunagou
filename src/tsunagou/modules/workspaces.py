"""Isolation decisions, workspace manifests, and main-owned Git requests."""

from __future__ import annotations

import hashlib
import os
import re
import stat as stat_module
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tsunagou.shared_kernel.digests import canonical_digest
from tsunagou.shared_kernel.ids import new_id
from tsunagou.shared_kernel.time import format_timestamp, now_ms, parse_timestamp

EVIDENCE_LEVELS = frozenset({
    "agent_asserted", "host_observed", "system_verified", "user_confirmed",
})
_SELF_REPORTED_LEVELS = frozenset({"agent_asserted", "host_observed"})
_PRIVATE_PREFIXES = (".tsunagou", ".git")


def _normalise_relative_path(value: str, *, allow_empty: bool = False) -> str:
    """Return a portable relative path or fail closed.

    Paths are persisted with POSIX separators.  A scope is an allow-list, so
    accepting an absolute path, a parent traversal, or an empty prefix would
    turn a caller supplied value into an authorization expansion.
    """

    if not isinstance(value, str):
        raise ValueError("workspace_path_string_required")
    text = value.replace("\\", "/")
    if not text and allow_empty:
        return ""
    if not text or text.startswith("/") or ":" in text.split("/", 1)[0]:
        raise ValueError("workspace_relative_path_required")
    parts = tuple(part for part in text.split("/") if part not in {""})
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError("workspace_relative_path_required")
    normalised = "/".join(parts)
    if any(part.casefold() in _PRIVATE_PREFIXES for part in parts):
        raise PermissionError("workspace_private_path_denied")
    return normalised


def _normalise_scope_paths(paths: list[str] | tuple[str, ...] | None) -> tuple[str, ...] | None:
    if paths is None:
        return None
    if not isinstance(paths, (list, tuple)):
        raise ValueError("workspace_scope_paths_required")
    values = tuple(sorted({_normalise_relative_path(item) for item in paths}))
    if not values:
        raise ValueError("workspace_scope_empty")
    return values


def scope_digest(paths: tuple[str, ...] | None) -> str:
    return canonical_digest({"paths": list(paths) if paths is not None else "all"})


def _path_in_scope(path: str, paths: tuple[str, ...] | None) -> bool:
    if paths is None:
        return True
    # Windows path identity is case-insensitive. Do not widen a Linux scope by
    # granting ``SRC`` merely because ``src`` was authorized.
    folded = os.path.normcase(path)
    return any(folded == os.path.normcase(allowed) or folded.startswith(os.path.normcase(allowed) + os.sep)
               for allowed in paths)


def _safe_status_path(path: str) -> str | None:
    try:
        return _normalise_relative_path(path)
    except (PermissionError, ValueError):
        return None


def _status_records(raw: str) -> list[tuple[str, str]]:
    """Parse porcelain v1 ``-z`` records without Git's quote escaping."""

    records = raw.split("\0")
    parsed: list[tuple[str, str]] = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if len(record) < 4:
            continue
        status, path = record[:2], record[3:]
        safe = _safe_status_path(path)
        if safe is not None:
            parsed.append((status, safe))
        # Porcelain -z puts the destination first, then the source. Preserve
        # both sides of a rename so deletions and additions are independently
        # filtered against scope. Copies leave the source unchanged.
        if status[0] in {"R", "C"} or status[1] in {"R", "C"}:
            old_path = records[index] if index < len(records) else ""
            index += 1
            safe_old = _safe_status_path(old_path)
            if "R" in status and safe_old is not None:
                parsed.append((status, safe_old))
    return parsed


def _atomic_artifact_write(destination: Path, payload: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_file() or destination.read_bytes() != payload:
            raise ValueError("artifact_content_conflict")
        return
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.replace(temporary, destination)
        except FileExistsError:
            pass
        try:
            directory_fd = os.open(destination.parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _normalise_validation_metadata(
    values: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    *, allow_stronger: bool = False,
) -> tuple[dict[str, Any], ...]:
    """Validate a safe validation receipt without treating it as host proof."""

    if values is None:
        return ()
    if not isinstance(values, (list, tuple)) or len(values) > 100:
        raise ValueError("validation_metadata_list_required")
    allowed = {
        "started_at", "finished_at", "command", "exit_code", "tool", "tool_version",
        "workspace_digest", "evidence_level", "stdout_digest", "stderr_digest",
    }
    result: list[dict[str, Any]] = []
    for item in values:
        if not isinstance(item, dict) or set(item) - allowed:
            raise ValueError("invalid_validation_metadata")
        required = {"started_at", "finished_at", "command", "exit_code", "tool", "tool_version", "workspace_digest"}
        if not required.issubset(item):
            raise ValueError("validation_metadata_fields_required")
        if not isinstance(item["started_at"], str) or not isinstance(item["finished_at"], str):
            raise ValueError("validation_timestamp_required")
        started = parse_timestamp(item["started_at"])
        finished = parse_timestamp(item["finished_at"])
        if started is None or finished is None or finished < started:
            raise ValueError("validation_metadata_time_order")
        command = item["command"]
        tool = item["tool"]
        version = item["tool_version"]
        workspace_value = item["workspace_digest"]
        exit_code = item["exit_code"]
        if (not isinstance(command, str) or not command or len(command) > 4096
                or "\x00" in command or "\r" in command or "\n" in command):
            raise ValueError("invalid_validation_command")
        if not isinstance(tool, str) or not tool or len(tool) > 256:
            raise ValueError("invalid_validation_tool")
        if not isinstance(version, str) or not version or len(version) > 256:
            raise ValueError("invalid_validation_tool_version")
        if not isinstance(workspace_value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", workspace_value):
            raise ValueError("validation_workspace_digest_required")
        if not isinstance(exit_code, int) or isinstance(exit_code, bool) or not -(2**31) <= exit_code < 2**31:
            raise ValueError("validation_exit_code_required")
        level = item.get("evidence_level", "agent_asserted")
        # A worker may report what it claims, but cannot self-elevate its own
        # receipt to system or user evidence.  Keep the original claim as a
        # harmless diagnostic field while the canonical level remains weak.
        if level not in EVIDENCE_LEVELS:
            raise ValueError("invalid_evidence_level")
        canonical_level = level if allow_stronger and level in {"system_verified", "user_confirmed"} else "agent_asserted"
        row: dict[str, Any] = {
            "started_at": format_timestamp(started), "finished_at": format_timestamp(finished),
            "command": command, "exit_code": exit_code, "tool": tool,
            "tool_version": version, "workspace_digest": workspace_value,
            "tool_version_digest": canonical_digest({"tool": tool, "version": version}),
            "evidence_level": canonical_level,
        }
        if level != canonical_level:
            row["reported_evidence_level"] = level
        for digest_key in ("stdout_digest", "stderr_digest"):
            if digest_key in item:
                digest = item[digest_key]
                if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                    raise ValueError("invalid_validation_output_digest")
                row[digest_key] = digest
        result.append(row)
    return tuple(result)


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
    scope_revision: int
    revision: int
    driver_kind: str
    input_digest: str
    hard_constraints: tuple[str, ...]
    evidence_refs: tuple[dict[str, Any], ...]
    decided_by: str
    decision_digest: str
    root_binding_refs: tuple[str, ...] = ()
    repository_id: str | None = None
    external_locator: str | None = None


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
    # ``None`` means the main Agent selected the complete bound root.  A tuple
    # is an explicit relative-path allow-list and is never widened by a worker.
    scope_paths: tuple[str, ...] | None = None
    scope_digest: str | None = None
    scope_roots: tuple[dict[str, Any], ...] = ()


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
    scope_paths: tuple[str, ...] | None = None
    scope_digest: str | None = None
    root_observations: tuple[dict[str, Any], ...] = ()


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
    submitted_by: str | None = None
    observed_at: int | None = None
    evidence_level: str = "agent_asserted"
    validation_metadata: tuple[dict[str, Any], ...] = ()
    scope_paths: tuple[str, ...] | None = None
    scope_digest: str | None = None
    patch_artifact_domain: str | None = None
    patch_artifact_owner: str | None = None
    root_observations: tuple[dict[str, Any], ...] = ()


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
        self, *, task_id: str, scope_revision: int, driver_kind: str,
        input_snapshot: dict[str, Any], hard_constraints: set[str],
        evidence_refs: list[dict[str, Any]], decided_by: str,
        root_binding_refs: tuple[str, ...] = (), repository_id: str | None = None,
        external_locator: str | None = None,
    ) -> IsolationDecision:
        candidates = {item.kind for item in self.list_driver_candidates(hard_constraints)}
        if driver_kind not in candidates:
            raise ValueError("driver_does_not_meet_hard_constraints")
        input_digest = canonical_digest(input_snapshot)
        body = {
            "task_id": task_id, "scope_revision": scope_revision, "driver_kind": driver_kind,
            "root_binding_refs": root_binding_refs, "repository_id": repository_id, "external_locator": external_locator,
            "input_digest": input_digest, "hard_constraints": sorted(hard_constraints),
            "evidence_refs": evidence_refs, "decided_by": decided_by,
        }
        decision = IsolationDecision(
            new_id(), task_id, scope_revision,
            1 + max((item.revision for item in self.decisions.values() if item.task_id == task_id), default=0),
            driver_kind, input_digest,
            tuple(sorted(hard_constraints)), tuple(evidence_refs), decided_by, canonical_digest(body),
            root_binding_refs, repository_id, external_locator,
        )
        self.decisions[decision.decision_id] = decision
        return decision

    def request_workspace(
        self, decision_id: str, *, attempt_id: str, root_binding_refs: list[str], repository_id: str | None = None,
        external_locator: str | None = None, current_main_id: str | None = None,
        scope_paths: list[str] | tuple[str, ...] | None = None,
        expected_scope_digest: str | None = None,
        scope_roots: list[dict[str, Any]] | None = None,
    ) -> Workspace:
        decision = self.decisions[decision_id]
        if decision.driver_kind == "worktree" and (repository_id is None or len(root_binding_refs) != 1):
            raise ValueError("worktree_requires_single_repository_root")
        normalised_scope = _normalise_scope_paths(scope_paths)
        calculated_scope_digest = canonical_digest(scope_roots) if scope_roots else scope_digest(normalised_scope)
        if expected_scope_digest is not None and expected_scope_digest != calculated_scope_digest:
            raise ValueError("workspace_scope_digest_mismatch")
        workspace = Workspace(
            new_id(), attempt_id, decision_id, decision.driver_kind,
            tuple(root_binding_refs), repository_id, external_locator,
            scope_paths=normalised_scope, scope_digest=calculated_scope_digest,
            scope_roots=tuple(scope_roots or ()),
        )
        self.workspaces[workspace.workspace_id] = workspace
        if decision.driver_kind == "external" and not external_locator:
            raise ValueError("external_locator_required")
        # Git worktrees and external roots are prepared by main before begin.
        # Creating an Attempt must never create a second Git action workflow.
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
        root_observations: list[dict[str, Any]] | None = None,
    ) -> BaselineManifest:
        workspace = self.workspaces[workspace_id]
        if workspace.driver_kind == "worktree" and (dirty or untracked_summary or not head_commit):
            raise ValueError("worktree_baseline_not_clean")
        body = {
            "workspace_id": workspace_id, "head_commit": head_commit, "branch": branch,
            "index_digest": index_digest, "tracked_state_digest": tracked_state_digest,
            "untracked_summary": sorted(untracked_summary), "root_identities": sorted(root_identities),
            "scope_paths": list(workspace.scope_paths) if workspace.scope_paths is not None else "all",
            "scope_digest": workspace.scope_digest or scope_digest(workspace.scope_paths),
            "root_observations": root_observations or [],
        }
        manifest = BaselineManifest(
            new_id(), workspace_id, head_commit, branch, index_digest, tracked_state_digest,
            tuple(sorted(untracked_summary)), tuple(sorted(root_identities)), canonical_digest(body),
            workspace.scope_paths, workspace.scope_digest or scope_digest(workspace.scope_paths),
            tuple(root_observations or ()),
        )
        self.baselines[manifest.manifest_id] = manifest
        workspace.baseline_manifest_id = manifest.manifest_id
        workspace.status = "ready"
        workspace.revision += 1
        return manifest

    def scan_root(
        self, root: str | Path, *, artifact_root: str | Path | None = None,
        allowed_paths: list[str] | tuple[str, ...] | None = None,
        expected_scope_digest: str | None = None,
        include_patch: bool = False,
    ) -> dict[str, Any]:
        """Read a real Git working tree without attributing edits to a writer.

        The scan is deliberately observational: it records current filesystem
        facts and never decides whether a changed path was written by a user or
        an Agent. A binary patch is stored content-addressed when Git can
        produce one, so a result can be retrieved and verified after restart.
        """
        repository = Path(root).expanduser().resolve()
        normalised_scope = _normalise_scope_paths(allowed_paths)
        calculated_scope_digest = scope_digest(normalised_scope)
        if expected_scope_digest is not None and expected_scope_digest != calculated_scope_digest:
            raise ValueError("workspace_scope_digest_mismatch")
        excluded_path: str | None = None
        if artifact_root is not None:
            try:
                excluded_path = Path(artifact_root).resolve().relative_to(repository).as_posix()
            except ValueError:
                pass

        def admitted(path: str) -> bool:
            return (_safe_status_path(path) is not None and _path_in_scope(path, normalised_scope)
                    and not (excluded_path is not None and _path_in_scope(path, (excluded_path,))))

        def git_text(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "--literal-pathspecs", *args],
                cwd=repository, check=check, capture_output=True, text=True,
                encoding="utf-8", errors="surrogateescape", timeout=15,
            )

        probe = git_text(["rev-parse", "--show-toplevel"], check=False)
        git_repository = probe.returncode == 0
        index_entries: list[dict[str, str]] = []
        if git_repository:
            # cwd may be a bound subdirectory of a repository. Git status uses
            # root-relative paths by default, whereas ls-files uses cwd-relative
            # paths. Explicit pathspec plus relative status keeps both local to
            # this bound root without collecting sibling directories.
            status = git_text(["-c", "status.relativePaths=true", "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", "."])
            git_root = Path(probe.stdout.strip()).resolve()
            prefix = repository.relative_to(git_root).as_posix()
            status_records = _status_records(status.stdout)
            if prefix != ".":
                # Porcelain v1 always prints repository-relative paths even
                # when status.relativePaths is set.
                status_records = [(state, path[len(prefix) + 1:]) for state, path in status_records
                                  if path.startswith(prefix + "/")]
            admitted_records = [(state, path) for state, path in status_records if admitted(path)]
            staged = git_text(["ls-files", "--stage", "-z", "--", "."])
            for record in staged.stdout.split("\0"):
                if not record:
                    continue
                metadata, path = record.split("\t", 1)
                index_mode, blob, stage = metadata.split(" ")
                if admitted(path):
                    index_entries.append({"path": path, "mode": index_mode, "blob": blob, "stage": stage})
            observed_paths = {entry["path"] for entry in index_entries}
            observed_paths.update(path for _, path in admitted_records)
            head = git_text(["rev-parse", "--verify", "HEAD"], check=False).stdout.strip() or None
            branch = git_text(["branch", "--show-current"], check=False).stdout.strip() or None
        else:
            observed_paths = set()
            for directory, directories, files in os.walk(repository, followlinks=False):
                directory_path = Path(directory)
                for name in list(directories):
                    candidate = directory_path / name
                    relative = candidate.relative_to(repository).as_posix()
                    safe = _safe_status_path(relative)
                    in_scope = safe is not None and (admitted(relative) or any(
                        _path_in_scope(allowed, (relative,)) for allowed in normalised_scope or ()
                    ))
                    if not in_scope or (excluded_path is not None and _path_in_scope(relative, (excluded_path,))):
                        directories.remove(name)
                    elif candidate.is_symlink() or (
                        getattr(candidate.lstat(), "st_file_attributes", 0) & stat_module.FILE_ATTRIBUTE_REPARSE_POINT
                    ):
                        directories.remove(name)
                        if admitted(relative):
                            observed_paths.add(relative)
                observed_paths.update(
                    relative for name in files
                    if admitted(relative := (directory_path / name).relative_to(repository).as_posix())
                )
            admitted_records = [("??", path) for path in sorted(observed_paths)]
            head = branch = None
        changed_paths = {path for _, path in admitted_records}
        untracked = {path for state, path in admitted_records if state == "??"}
        # Include unchanged tracked files as well as status entries. Otherwise
        # two clean commits or two different staged blobs could share a digest.
        content_entries: list[dict[str, Any]] = []
        for path in sorted(observed_paths):
            candidate = repository / path
            try:
                file_stat = candidate.lstat()
            except FileNotFoundError:
                content_entries.append({"path": path, "kind": "missing"})
                continue
            except OSError:
                content_entries.append({"path": path, "kind": "unreadable"})
                continue
            mode = stat_module.S_IMODE(file_stat.st_mode)
            if candidate.is_symlink():
                try:
                    target = os.readlink(candidate)
                except OSError:
                    content_entries.append({"path": path, "kind": "unreadable", "mode": mode})
                    continue
                content_entries.append({
                    "path": path, "kind": "symlink", "target_sha256": hashlib.sha256(target.encode("utf-8", "surrogateescape")).hexdigest(),
                    "target_size": len(target), "mode": mode,
                })
                continue
            try:
                resolved = candidate.resolve(strict=False)
                resolved_relative = resolved.relative_to(repository).as_posix()
                safely_resolved = admitted(resolved_relative)
            except (OSError, ValueError, RuntimeError):
                safely_resolved = False
            if not safely_resolved:
                # Junctions/reparse points must not let an observational scan
                # read outside the bound root.
                content_entries.append({"path": path, "kind": "link_outside", "mode": mode})
                continue
            if not stat_module.S_ISREG(file_stat.st_mode):
                content_entries.append({"path": path, "kind": "special", "mode": mode})
                continue
            try:
                content = candidate.read_bytes()
            except OSError:
                content_entries.append({"path": path, "kind": "unreadable", "mode": mode})
                continue
            content_entries.append({
                "path": path, "kind": "file", "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content), "mode": mode,
            })
        untracked.intersection_update(changed_paths)
        tracked_state_digest = canonical_digest({"entries": content_entries})
        index_entries.sort(key=lambda entry: (entry["path"], entry["stage"]))
        index_digest = canonical_digest({"entries": index_entries})
        patch_paths = sorted(item["path"] for item in content_entries
                             if item["path"] in changed_paths and item["kind"] in {"file", "missing"})
        patch = (self._patch_bytes(repository, patch_paths, untracked, git_repository=git_repository)
                 if include_patch or artifact_root is not None else b"")
        patch_ref = None
        if patch and artifact_root is not None:
            digest = "sha256:" + hashlib.sha256(patch).hexdigest()
            destination = Path(artifact_root) / (digest.replace(":", "_") + ".patch")
            _atomic_artifact_write(destination, patch)
            patch_ref = digest
        observation: dict[str, Any] = {
            "head_commit": head,
            "branch": branch,
            "index_digest": index_digest,
            "tracked_state_digest": tracked_state_digest,
            "untracked_summary": sorted(untracked),
            "changed_paths": sorted(changed_paths),
            "patch_artifact_ref": patch_ref,
            "dirty": bool(admitted_records),
            "scope_paths": list(normalised_scope) if normalised_scope is not None else None,
            "scope_digest": calculated_scope_digest,
            "content_entries": content_entries,
            "index_entries": index_entries,
        }
        if include_patch:
            observation["patch_bytes"] = patch
        return observation

    @staticmethod
    def _patch_bytes(
        repository: Path, paths: list[str], untracked_paths: set[str], *, git_repository: bool = True,
    ) -> bytes:
        if not paths:
            return b""
        chunks: list[bytes] = []
        # The patch uses the same admitted paths as the digest. A global diff
        # would re-introduce tracked private state even after scan filtering.
        git_diff = [
            "git", "--no-optional-locks", "-c", "core.fsmonitor=false", "--literal-pathspecs",
            "diff", "--no-ext-diff", "--no-textconv", "--binary",
        ]
        commands = ([*git_diff, "--cached", "--", *paths], [*git_diff, "--", *paths]) if git_repository else ()
        for args in commands:
            result = subprocess.run(args, cwd=repository, check=True, capture_output=True, timeout=15)
            if result.stdout:
                chunks.append(result.stdout)
        for path in paths:
            if path not in untracked_paths:
                continue
            result = subprocess.run(
                ["git", "--no-optional-locks", "diff", "--no-ext-diff", "--no-textconv", "--no-index", "--binary", "--", "/dev/null", path],
                cwd=repository, check=False, capture_output=True, timeout=15,
            )
            if result.returncode not in {0, 1}:
                raise ValueError("workspace_patch_failed")
            if result.stdout:
                chunks.append(result.stdout)
        return b"\n".join(chunks)

    def record_result(
        self, workspace_id: str, *, attempt_id: str, baseline_digest: str,
        commit_refs: list[str], patch_artifact_ref: str | None, changed_paths: list[str],
        untracked_summary: list[str], validation_refs: list[str],
        observed_state_digest: str | None = None, baseline_conflict: bool = False,
        submitted_by: str | None = None, evidence_level: str = "agent_asserted",
        validation_metadata: list[dict[str, Any]] | None = None,
        observed_validation_metadata: list[dict[str, Any]] | None = None,
        root_observations: list[dict[str, Any]] | None = None,
    ) -> ResultManifest:
        workspace = self.workspaces[workspace_id]
        baseline = self.baselines.get(workspace.baseline_manifest_id or "")
        if baseline is None or baseline.digest != baseline_digest or workspace.attempt_id != attempt_id:
            raise ValueError("workspace_baseline_or_attempt_mismatch")
        observation_only: set[str] = set()
        for root in root_observations or ():
            prefix = root["root_id"] + "/" if len(root_observations or ()) > 1 else ""
            observation_only.update(prefix + entry["path"] for entry in root.get("content_entries", ())
                                    if entry["kind"] in {"symlink", "link_outside", "special", "unreadable"})
        if (not commit_refs and patch_artifact_ref is None and changed_paths
                and not set(changed_paths).issubset(observation_only)):
            raise ValueError("uncommitted_result_requires_patch_artifact")
        if patch_artifact_ref is not None and (not isinstance(patch_artifact_ref, str) or not patch_artifact_ref):
            raise ValueError("invalid_patch_artifact_ref")
        normalised_paths = tuple(sorted({_normalise_relative_path(path) for path in changed_paths}))
        if any(not _path_in_scope(path, workspace.scope_paths) for path in normalised_paths):
            raise PermissionError("workspace_scope_denied")
        normalised_untracked = tuple(sorted({_normalise_relative_path(path) for path in untracked_summary}))
        if any(not _path_in_scope(path, workspace.scope_paths) for path in normalised_untracked):
            raise PermissionError("workspace_scope_denied")
        if evidence_level not in EVIDENCE_LEVELS:
            raise ValueError("invalid_evidence_level")
        safe_validation = _normalise_validation_metadata(validation_metadata)
        safe_observed_validation = _normalise_validation_metadata(
            observed_validation_metadata, allow_stronger=True,
        )
        all_validation = safe_validation + safe_observed_validation
        body = {
            "workspace_id": workspace_id, "attempt_id": attempt_id, "baseline_digest": baseline_digest,
            "commit_refs": commit_refs, "patch_artifact_ref": patch_artifact_ref,
            "changed_paths": list(normalised_paths), "untracked_summary": list(normalised_untracked),
            "validation_refs": sorted(validation_refs), "observed_state_digest": observed_state_digest,
            "baseline_conflict": baseline_conflict,
            "submitted_by": submitted_by, "evidence_level": evidence_level,
            "validation_metadata": list(all_validation),
            "scope_paths": list(workspace.scope_paths) if workspace.scope_paths is not None else "all",
            "scope_digest": workspace.scope_digest or scope_digest(workspace.scope_paths),
            "patch_artifact_domain": f"workspace/{workspace_id}" if patch_artifact_ref else None,
            "patch_artifact_owner": submitted_by if patch_artifact_ref else None,
            "root_observations": root_observations or [],
        }
        result = ResultManifest(
            new_id(), workspace_id, attempt_id, baseline_digest, tuple(commit_refs), patch_artifact_ref,
            normalised_paths, normalised_untracked, tuple(sorted(validation_refs)), canonical_digest(body),
            observed_state_digest, baseline_conflict, submitted_by, now_ms(), evidence_level,
            all_validation, workspace.scope_paths, workspace.scope_digest or scope_digest(workspace.scope_paths),
            f"workspace/{workspace_id}" if patch_artifact_ref else None,
            submitted_by if patch_artifact_ref else None,
            tuple(root_observations or ()),
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

    def request_integration(
        self, *, source_result_ref: str, target_repository_id: str,
        target_baseline_digest: str, plan_digest: str, reason: str,
        actor_main_id: str,
    ) -> GitActionRequest:
        """Record a Main-owned local integration request.

        The domain records the exact source result and target baseline so a
        host-side Git operation can be checked before it mutates the target.
        It deliberately creates a pending request only: the daemon never
        performs a push, and the caller must later attach Main-owned evidence.
        """
        if not source_result_ref or not target_repository_id or not target_baseline_digest:
            raise ValueError("integration_reference_required")
        result = self.results.get(source_result_ref)
        if result is None:
            result = next((item for item in self.results.values() if item.digest == source_result_ref), None)
        if result is None:
            raise KeyError("source_result_not_found")
        workspace = self.workspaces.get(result.workspace_id)
        if workspace is None or workspace.result_manifest_id != result.manifest_id:
            raise ValueError("source_result_workspace_mismatch")
        exact_input_digest = canonical_digest({
            "source_result_ref": source_result_ref,
            "source_result_digest": result.digest,
            "target_repository_id": target_repository_id,
            "target_baseline_digest": target_baseline_digest,
            "plan_digest": plan_digest,
            "reason": reason,
        })
        request = GitActionRequest(
            new_id(), workspace.workspace_id, target_repository_id, "integrate",
            actor_main_id, exact_input_digest,
            {
                "source_result_ref": source_result_ref,
                "source_result_digest": result.digest,
                "target_baseline_digest": target_baseline_digest,
                "plan_digest": plan_digest,
                "reason": reason,
                "push_allowed": False,
            },
        )
        self.git_requests[request.request_id] = request
        return request

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
