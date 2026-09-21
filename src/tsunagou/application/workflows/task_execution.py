"""Preflight and task execution orchestration without a second domain store."""

from __future__ import annotations

from typing import Any

from tsunagou.modules.cognition import CognitionService
from tsunagou.modules.resources import ResourceService
from tsunagou.modules.tasks import PreflightResult, TaskResult, TaskService, TaskStateError
from tsunagou.modules.workspaces import WorkspaceService
from tsunagou.shared_kernel.digests import canonical_digest


class TaskExecutionWorkflow:
    def __init__(
        self, *, tasks: TaskService, cognition: CognitionService,
        resources: ResourceService, workspaces: WorkspaceService,
        strict_runtime: bool = False,
    ) -> None:
        self.tasks = tasks
        self.cognition = cognition
        self.resources = resources
        self.workspaces = workspaces
        self.strict_runtime = strict_runtime

    def preflight(
        self, task_id: str, agent_id: str | None = None, *,
        attempt_id: str | None = None, evidence_refs: tuple[str, ...] = (),
    ) -> PreflightResult:
        task = self.tasks.tasks[task_id]
        attempt = self.tasks._current_attempt(task)
        owner = agent_id or attempt.owner_agent_id
        evidence: dict[str, Any] = {
            "task_revision": task.revision,
            "scope_revision": task.scope_revision,
            "attempt_revision": attempt.revision,
            "attempt_status": attempt.status,
            "reports": sorted(
                report.digest for report in self.cognition.reports.values()
                if report.task_id == task_id and report.attempt_id == attempt.attempt_id
            ),
            "contracts": sorted(
                f"{proposal.digest}:{proposal.status}"
                for proposal in self.cognition.proposals.values()
            ),
            "workspace_status": self._workspace_status(attempt.attempt_id),
            "lease_ids": sorted(
                lease.lease_set_id for lease in self.resources.lease_sets.values()
                if lease.attempt_id == attempt.attempt_id and lease.status == "active"
            ),
        }
        blockers: list[str] = []
        if attempt.owner_agent_id != owner:
            raise TaskStateError("attempt_owner_required")
        if task.status not in {"claimed", "running"}:
            blockers.append("task_not_claimed")
        if attempt.status not in {"claimed", "running"}:
            blockers.append("attempt_not_preparable")
        if evidence["workspace_status"] not in {None, "ready", "result_recorded"}:
            blockers.append("workspace_not_ready")
        if self.strict_runtime:
            if not evidence["lease_ids"]:
                blockers.append("resource_lease_required")
            if evidence["workspace_status"] != "ready":
                blockers.append("workspace_ready_required")
            linked_contracts = [
                proposal for proposal in self.cognition.proposals.values()
                if isinstance(proposal.payload, dict)
                and proposal.payload.get("task_id") == task_id
            ]
            if any(proposal.status != "accepted" for proposal in linked_contracts):
                blockers.append("contract_not_accepted")
        digest = canonical_digest(evidence)
        return self.tasks.preflight(
            task_id, owner, attempt_id=attempt_id or attempt.attempt_id,
            evidence_refs=evidence_refs, input_digest=digest,
            blockers=tuple(dict.fromkeys(blockers)), evidence=evidence,
        )

    def start(self, preflight: PreflightResult, *, agent_id: str) -> None:
        current = self._current_evidence(preflight.task_id)
        if current["digest"] != preflight.input_digest or preflight.blockers:
            raise TaskStateError("stale_or_blocked_preflight")
        attempt = self.tasks.start(
            preflight.task_id, agent_id, preflight_id=preflight.preflight_id,
            require_preflight=True,
        )
        if attempt.attempt_id != preflight.attempt_id:
            raise TaskStateError("attempt_id_mismatch")

    def block(self, task_id: str, reason: str) -> PreflightResult:
        self.tasks.block(task_id, reason)
        return self.preflight(task_id)

    def resume(self, task_id: str, agent_id: str) -> PreflightResult:
        self.tasks.resume(task_id, agent_id)
        return self.preflight(task_id)

    def submit(self, task_id: str, agent_id: str, payload: dict[str, Any]) -> TaskResult:
        task = self.tasks.tasks[task_id]
        attempt = self.tasks._current_attempt(task)
        lease_ids = [
            lease.lease_set_id for lease in self.resources.lease_sets.values()
            if lease.attempt_id == attempt.attempt_id and lease.status == "active"
        ]
        result = self.tasks.submit(task_id, agent_id, payload)
        self.resources.release_for_attempt(attempt.attempt_id, reason="attempt_submitted")
        if not lease_ids:
            return result
        return result

    def _workspace_status(self, attempt_id: str) -> str | None:
        statuses = [workspace.status for workspace in self.workspaces.workspaces.values() if workspace.attempt_id == attempt_id]
        return statuses[-1] if statuses else None

    def _current_evidence(self, task_id: str) -> dict[str, Any]:
        task = self.tasks.tasks[task_id]
        attempt = self.tasks._current_attempt(task)
        evidence: dict[str, Any] = {
            "task_revision": task.revision,
            "scope_revision": task.scope_revision,
            "attempt_revision": attempt.revision,
            "attempt_status": attempt.status,
            "reports": sorted(
                report.digest for report in self.cognition.reports.values()
                if report.task_id == task_id and report.attempt_id == attempt.attempt_id
            ),
            "contracts": sorted(
                f"{proposal.digest}:{proposal.status}"
                for proposal in self.cognition.proposals.values()
            ),
            "workspace_status": self._workspace_status(attempt.attempt_id),
            "lease_ids": sorted(
                lease.lease_set_id for lease in self.resources.lease_sets.values()
                if lease.attempt_id == attempt.attempt_id and lease.status == "active"
            ),
        }
        return {"digest": canonical_digest(evidence), **evidence}
