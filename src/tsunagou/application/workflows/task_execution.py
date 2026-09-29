"""Task execution invariants composed inside the existing command UoW."""

from __future__ import annotations

from typing import Any

from tsunagou.modules.cognition import CognitionService
from tsunagou.modules.tasks import Attempt, Task, TaskResult, TaskService, TaskStateError
from tsunagou.shared_kernel.errors import RevisionConflict


class TaskExecutionWorkflow:
    def __init__(
        self, *, tasks: TaskService, cognition: CognitionService,
    ) -> None:
        self.tasks = tasks
        self.cognition = cognition

    def validate_begin(self, task_id: str, agent_id: str, expected_revision: int) -> Task:
        task = self.tasks.tasks[task_id]
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise ValueError("expected_task_revision_required")
        if task.revision != expected_revision:
            raise RevisionConflict("task_revision_conflict")
        attempt = self.tasks.attempts.get(task.current_attempt_id or "")
        if task.status == "running":
            if attempt is None or attempt.status != "running" or attempt.owner_agent_id != agent_id:
                raise PermissionError("attempt_owner_required")
        elif task.status not in {"open", "blocked"}:
            raise TaskStateError("task_not_beginable")
        elif attempt is not None and attempt.status in {"claimed", "running"}:
            raise TaskStateError("attempt_still_active")
        for prerequisite in task.blocks:
            dependency = self.tasks.tasks.get(prerequisite)
            if dependency is None or dependency.status != "completed":
                raise TaskStateError("task_dependency_pending:" + prerequisite)
        for proposal_id in task.required_contract_ids:
            proposal = self.cognition.proposals.get(proposal_id)
            if proposal is None or proposal.status != "accepted":
                raise TaskStateError("required_contract_not_accepted:" + proposal_id)
        return task

    def begin_attempt(self, task_id: str, agent_id: str, expected_revision: int) -> Attempt:
        task = self.validate_begin(task_id, agent_id, expected_revision)
        if task.status == "running":
            return self.tasks._current_attempt(task)
        return self.tasks.claim(task_id, agent_id)

    def validate_submit(self, task_id: str, agent_id: str, attempt_id: str) -> Attempt:
        task = self.tasks.tasks[task_id]
        attempt = self.tasks._current_attempt(task)
        if attempt.attempt_id != attempt_id or attempt.owner_agent_id != agent_id:
            raise PermissionError("attempt_owner_required")
        if task.status != "running" or attempt.status != "running":
            raise TaskStateError("attempt_not_running")
        return attempt

    def submit(
        self, task_id: str, agent_id: str, payload: dict[str, Any], *, attempt_id: str,
    ) -> TaskResult:
        self.validate_submit(task_id, agent_id, attempt_id)
        return self.tasks.submit(task_id, agent_id, payload)
