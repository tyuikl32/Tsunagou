"""Resolve task-authorized roots and compose observational workspace evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tsunagou.modules.projects import ProjectRegistry, physical_identity
from tsunagou.modules.tasks import Task
from tsunagou.modules.workspaces import Workspace, WorkspaceService
from tsunagou.shared_kernel.digests import canonical_digest


class WorkspaceEvidence:
    def __init__(self, service: WorkspaceService, registry: ProjectRegistry | None, project_root: str) -> None:
        self.service = service
        self.registry = registry
        self.project_root = Path(project_root).resolve()

    def resolve_scope(self, task: Task, requested_roots: list[str]) -> list[dict[str, Any]]:
        scope = task.execution_scope
        permissions: dict[str, list[str] | None] = {}
        if "resources" in scope:
            if not isinstance(scope["resources"], list) or any(not isinstance(r, dict) for r in scope["resources"]):
                raise ValueError("invalid_task_execution_scope")
            for resource in scope["resources"]:
                if resource.get("kind") != "path":
                    continue
                root_id = resource.get("root_id")
                if not isinstance(root_id, str) or not root_id:
                    raise ValueError("invalid_task_execution_scope")
                segments = resource.get("segments", [])
                if not isinstance(segments, list) or any(
                    not isinstance(part, str) or not part or part in {".", ".."} or "/" in part or "\\" in part
                    for part in segments
                ):
                    raise ValueError("invalid_task_execution_scope")
                if not segments:
                    permissions[root_id] = None
                elif root_id not in permissions:
                    permissions[root_id] = ["/".join(segments)]
                elif permissions[root_id] is not None:
                    permissions[root_id].append("/".join(segments))  # type: ignore[union-attr]
        elif "roots" in scope:
            if not isinstance(scope["roots"], list) or any(not isinstance(r, str) or not r for r in scope["roots"]):
                raise ValueError("invalid_task_execution_scope")
            permissions = {str(root_id): None for root_id in scope["roots"]}
        elif scope:
            raise ValueError("invalid_task_execution_scope")
        else:
            # An unconstrained task inherits the registered project roots. A
            # worker still cannot introduce a new root or local absolute path.
            permissions = {root_id: None for root_id in (
                self.registry.project.roots if self.registry and self.registry.project else {}
            )}
            if not permissions:
                permissions = {"coordination": None}
        selected = sorted(set(requested_roots) if requested_roots else permissions)
        if not selected or any(root_id not in permissions for root_id in selected):
            raise PermissionError("workspace_task_scope_denied")
        result: list[dict[str, Any]] = []
        project = self.registry.project if self.registry else None
        for root_id in selected:
            binding = self._binding(root_id)
            paths = permissions[root_id]
            result.append({
                "root_id": root_id, "paths": sorted(set(paths)) if paths is not None else None,
                "binding_revision": binding["binding_revision"],
                "physical_identity": binding["physical_identity"],
                "task_scope_revision": task.scope_revision,
                "task_scope_digest": canonical_digest(scope),
                "project_id": project.project_id if project else None,
                "lineage_id": project.current_lineage_id if project else None,
            })
        return result

    def _binding(self, root_id: str) -> dict[str, Any]:
        if root_id == "coordination" and not (self.registry and self.registry.local_bindings.get(root_id)):
            return {"absolute_path": str(self.project_root), "binding_revision": 0,
                    "physical_identity": physical_identity(self.project_root)}
        binding = self.registry.local_bindings.get(root_id) if self.registry else None
        if binding is None or binding.get("status") != "bound":
            raise PermissionError("workspace_root_unbound")
        path = Path(binding["absolute_path"])
        if not path.is_dir() or physical_identity(path) != binding["physical_identity"]:
            raise PermissionError("workspace_root_identity_changed")
        return binding

    @staticmethod
    def virtual_paths(roots: list[dict[str, Any]]) -> list[str] | None:
        if len(roots) == 1:
            return roots[0]["paths"]  # type: ignore[no-any-return]
        return [
            root["root_id"] + ("/" + path if path else "")
            for root in roots for path in (root["paths"] or [""])
        ]

    def scan(self, workspace: Workspace, task: Task, *, include_patch: bool = False) -> dict[str, Any]:
        current = self.resolve_scope(task, list(workspace.root_binding_refs))
        if canonical_digest(current) != workspace.scope_digest:
            raise PermissionError("workspace_scope_changed_reprepare_required")
        roots: list[dict[str, Any]] = []
        changed: list[str] = []
        untracked: list[str] = []
        chunks: list[bytes] = []
        for root in current:
            observed = self.service.scan_root(
                self._binding(root["root_id"])["absolute_path"],
                allowed_paths=root["paths"], include_patch=include_patch,
            )
            prefix = root["root_id"] + "/" if len(current) > 1 else ""
            changed.extend(prefix + path for path in observed["changed_paths"])
            untracked.extend(prefix + path for path in observed["untracked_summary"])
            patch = observed.pop("patch_bytes", b"")
            if patch:
                chunks.append((f"# tsunagou-root {root['root_id']}\n".encode() if len(current) > 1 else b"") + patch)
            roots.append({"root_id": root["root_id"], **observed})
        return {
            "head_commit": roots[0]["head_commit"] if len(roots) == 1 else None,
            "branch": roots[0]["branch"] if len(roots) == 1 else None,
            "index_digest": canonical_digest([{r["root_id"]: r["index_digest"]} for r in roots]),
            "tracked_state_digest": canonical_digest([{r["root_id"]: r["tracked_state_digest"]} for r in roots]),
            "changed_paths": sorted(changed), "untracked_summary": sorted(untracked),
            "dirty": any(r["dirty"] for r in roots), "patch_bytes": b"\n".join(chunks),
            "root_identities": [r["physical_identity"] for r in current],
            "root_observations": roots,
        }
