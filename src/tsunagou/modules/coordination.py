"""Main-authored assignments; task execution and host delivery have their own owners."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from tsunagou.shared_kernel.ids import new_id
from tsunagou.shared_kernel.time import now_ms


@dataclass(frozen=True, slots=True)
class CoordinationEvent:
    event_id: str
    kind: str
    actor_id: str | None = None
    assignment_id: str | None = None
    task_id: str | None = None
    summary: str = ""
    important: bool = False
    created_at: int = field(default_factory=now_ms)


@dataclass(slots=True)
class CoordinationAssignment:
    assignment_id: str
    plan_id: str
    task_id: str
    assigned_worker_id: str
    dependencies: tuple[str, ...] = ()
    acceptance_conditions: dict[str, Any] = field(default_factory=dict)
    workspace: dict[str, Any] = field(default_factory=dict)
    auto_wake: bool = False
    message_id: str | None = None
    takeover_agent_id: str | None = None
    takeover_reason: str | None = None


@dataclass(slots=True)
class CoordinationPlan:
    plan_id: str
    main_agent_id: str
    objective: str
    auto_wake: bool
    assignment_ids: tuple[str, ...]
    created_at: int = field(default_factory=now_ms)


class CoordinationService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.plans: dict[str, CoordinationPlan] = {}
        self.assignments: dict[str, CoordinationAssignment] = {}
        self.events: list[CoordinationEvent] = []
        self._task_index: dict[str, str] = {}

    def record_event(self, kind: str, *, actor_id: str | None = None, assignment_id: str | None = None,
                     task_id: str | None = None, summary: str = "", important: bool = False) -> CoordinationEvent:
        event = CoordinationEvent(new_id(), kind, actor_id, assignment_id, task_id, summary, important)
        self.events.append(event)
        return event

    def create_plan(self, *, main_agent_id: str, objective: str, assignments: list[dict[str, Any]],
                    auto_wake: bool = False) -> CoordinationPlan:
        if not objective or not assignments:
            raise ValueError("coordination_plan_requires_objective_and_assignments")
        task_ids = [row.get("task_id") for row in assignments]
        if any(not row.get("task_id") or not row.get("assigned_worker_id") for row in assignments):
            raise ValueError("assignment_task_and_worker_required")
        if len(set(task_ids)) != len(task_ids) or any(task_id in self._task_index for task_id in task_ids):
            raise ValueError("duplicate_assignment_task")
        plan_id = new_id()
        created = [CoordinationAssignment(
            new_id(), plan_id, row["task_id"], row["assigned_worker_id"],
            tuple(row.get("dependencies") or ()), dict(row.get("acceptance_conditions") or {}),
            dict(row.get("workspace") or {}), bool(row.get("auto_wake", auto_wake)),
        ) for row in assignments]
        plan = CoordinationPlan(plan_id, main_agent_id, objective, auto_wake, tuple(row.assignment_id for row in created))
        self.plans[plan_id] = plan
        for row in created:
            self.assignments[row.assignment_id] = row
            self._task_index[row.task_id] = row.assignment_id
        return plan

    def assignment_for_task(self, task_id: str) -> CoordinationAssignment | None:
        return self.assignments.get(self._task_index.get(task_id, ""))

    def assignment(self, assignment_id: str) -> CoordinationAssignment:
        return self.assignments[assignment_id]

    def require_assigned_worker(self, task_id: str, worker_id: str) -> CoordinationAssignment | None:
        assignment = self.assignment_for_task(task_id)
        if assignment is not None and worker_id != (assignment.takeover_agent_id or assignment.assigned_worker_id):
            raise PermissionError("assignment_worker_mismatch")
        return assignment

    def takeover(self, assignment_id: str, *, main_agent_id: str, reason: str) -> CoordinationAssignment:
        if not reason.strip():
            raise ValueError("takeover_reason_required")
        assignment = self.assignment(assignment_id)
        assignment.takeover_agent_id, assignment.takeover_reason = main_agent_id, reason
        return assignment

    def coverage(self, task_statuses: dict[str, str], plan_id: str | None = None) -> dict[str, Any]:
        selected = [row for row in self.assignments.values() if plan_id is None or row.plan_id == plan_id]
        counts: dict[str, int] = {}
        for row in selected:
            status = task_statuses[row.task_id]
            counts[status] = counts.get(status, 0) + 1
        return {"plan_id": plan_id, "total": len(selected), "by_status": counts,
                "assigned_worker_ids": sorted({row.assigned_worker_id for row in selected})}
