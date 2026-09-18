"""Preflight and task execution orchestration without a second domain store."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tsunagou.modules.cognition import CognitionService
from tsunagou.modules.resources import ResourceService
from tsunagou.modules.tasks import TaskResult, TaskService, TaskStateError
from tsunagou.modules.workspaces import WorkspaceService
from tsunagou.shared_kernel.digests import canonical_digest


@dataclass(frozen=True, slots=True)
class PreflightResult:
    task_id: str
    attempt_id: str
    scope_revision: int
    evidence: dict[str, Any]
    input_digest: str
    blockers: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.blockers


class TaskExecutionWorkflow:
    def __init__(
        self, *, tasks: TaskService, cognition: CognitionService,
        resources: ResourceService, workspaces: WorkspaceService,
    ) -> None:
        self.tasks = tasks
        self.cognition = cognition
        self.resources = resources
        self.workspaces = workspaces

    def preflight(self, task_id: str) -> PreflightResult:
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
                proposal.digest for proposal in self.cognition.proposals.values()
                if proposal.status == "accepted"
            ),
            "workspace_status": self._workspace_status(attempt.attempt_id),
            "lease_ids": sorted(
                lease.lease_set_id for lease in self.resources.lease_sets.values()
                if lease.attempt_id == attempt.attempt_id and lease.status == "active"
            ),
        }
        blockers: list[str] = []
        if task.status not in {"claimed", "running"}:
            blockers.append("task_not_claimed")
        if attempt.status not in {"claimed", "running"}:
            blockers.append("attempt_not_preparable")
        if evidence["workspace_status"] not in {None, "ready", "result_recorded"}:
            blockers.append("workspace_not_ready")
        return PreflightResult(
            task_id, attempt.attempt_id, task.scope_revision, evidence,
            canonical_digest(evidence), tuple(blockers),
        )

    def start(self, preflight: PreflightResult, *, agent_id: str) -> None:
        current = self.preflight(preflight.task_id)
        if current.input_digest != preflight.input_digest or not current.valid:
            raise TaskStateError("stale_or_blocked_preflight")
        self.tasks.start(preflight.task_id, agent_id)

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
