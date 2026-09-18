"""Task/Attempt ownership and acceptance state machines."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from tsunagou.shared_kernel.digests import canonical_digest
from tsunagou.shared_kernel.ids import new_id

TASK_TERMINAL = {"completed", "failed", "cancelled"}
ATTEMPT_TERMINAL = {"submitted", "completed", "cancelled", "orphaned"}


@dataclass(slots=True)
class Task:
    task_id: str
    title: str
    objective: str
    status: str = "draft"
    parent_task_id: str | None = None
    blocks: set[str] = field(default_factory=set)
    current_attempt_id: str | None = None
    revision: int = 1
    scope_revision: int = 1
    block_reason: str | None = None
    orphan_reason: str | None = None


@dataclass(slots=True)
class Attempt:
    attempt_id: str
    task_id: str
    owner_agent_id: str
    status: str = "claimed"
    execution_epoch: int = 1
    revision: int = 1
    started_at: float | None = None
    ended_at: float | None = None


@dataclass(frozen=True, slots=True)
class TaskResult:
    result_id: str
    task_id: str
    attempt_id: str
    payload: dict[str, Any]
    digest: str
    submitted_by: str


@dataclass(frozen=True, slots=True)
class ReviewRound:
    round_no: int
    result_id: str
    reviewer_agent_id: str
    decision: str
    reason: str | None = None


class TaskStateError(ValueError):
    pass


class TaskService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.tasks: dict[str, Task] = {}
        self.attempts: dict[str, Attempt] = {}
        self.results: dict[str, TaskResult] = {}
        self.reviews: dict[tuple[str, int], ReviewRound] = {}
        self.scope_requests: dict[str, dict[str, Any]] = {}

    def create_task(
        self, title: str, objective: str, *, parent_task_id: str | None = None,
        blocks: set[str] | None = None,
    ) -> Task:
        with self._lock:
            if parent_task_id is not None and parent_task_id not in self.tasks:
                raise KeyError(parent_task_id)
            task = Task(new_id(), title, objective, parent_task_id=parent_task_id, blocks=set(blocks or ()))
            self.tasks[task.task_id] = task
            self._validate_dag()
            return task

    def add_block(self, task_id: str, blocking_task_id: str) -> None:
        with self._lock:
            task = self._task(task_id)
            if task_id == blocking_task_id or blocking_task_id not in self.tasks:
                raise TaskStateError("invalid_block_edge")
            task.blocks.add(blocking_task_id)
            try:
                self._validate_dag()
            except Exception:
                task.blocks.remove(blocking_task_id)
                raise

    def ready(self, task_id: str) -> Task:
        with self._lock:
            task = self._task(task_id)
            self._transition(task, {"draft", "changes_requested"}, "ready")
            return task

    def publish(self, task_id: str) -> Task:
        with self._lock:
            task = self._task(task_id)
            self._transition(task, {"ready"}, "open")
            return task

    def claim(self, task_id: str, agent_id: str) -> Attempt:
        with self._lock:
            task = self._task(task_id)
            if task.status != "open" or task.current_attempt_id is not None:
                raise TaskStateError("task_not_claimable")
            attempt = Attempt(new_id(), task_id, agent_id)
            self.attempts[attempt.attempt_id] = attempt
            task.current_attempt_id = attempt.attempt_id
            task.status = "claimed"
            task.revision += 1
            return attempt

    def resume(self, task_id: str, agent_id: str) -> Attempt:
        with self._lock:
            task = self._task(task_id)
            if task.status not in {"blocked", "orphaned"}:
                raise TaskStateError("task_not_resumable")
            current = self.attempts.get(task.current_attempt_id or "")
            if current is None or current.status in ATTEMPT_TERMINAL or current.owner_agent_id != agent_id:
                current = Attempt(new_id(), task_id, agent_id)
                self.attempts[current.attempt_id] = current
                task.current_attempt_id = current.attempt_id
            current.status = "claimed"
            current.revision += 1
            task.status = "claimed"
            task.revision += 1
            return current

    def start(
        self, task_id: str, agent_id: str, *, workspace_ready: bool = True,
        lease_valid: bool = True, contract_ready: bool = True, report_ready: bool = True,
    ) -> Attempt:
        with self._lock:
            task = self._task(task_id)
            attempt = self._current_attempt(task)
            if attempt.owner_agent_id != agent_id:
                raise TaskStateError("attempt_owner_required")
            if attempt.status != "claimed" or task.status != "claimed":
                raise TaskStateError("attempt_not_startable")
            missing = [name for name, value in {
                "workspace": workspace_ready, "lease": lease_valid,
                "contract": contract_ready, "report": report_ready,
            }.items() if not value]
            if missing:
                task.status = "blocked"
                task.revision += 1
                raise TaskStateError("start_blocked:" + ",".join(missing))
            attempt.status = "running"
            attempt.started_at = time.time()
            attempt.revision += 1
            task.status = "running"
            task.revision += 1
            return attempt

    def block(self, task_id: str, reason: str) -> Task:
        with self._lock:
            task = self._task(task_id)
            if task.status in TASK_TERMINAL:
                raise TaskStateError("terminal_task")
            task.status = "blocked"
            task.revision += 1
            task.block_reason = reason
            return task

    def submit(self, task_id: str, agent_id: str, payload: dict[str, Any]) -> TaskResult:
        with self._lock:
            task = self._task(task_id)
            attempt = self._current_attempt(task)
            if attempt.owner_agent_id != agent_id or attempt.status != "running" or task.status != "running":
                raise TaskStateError("attempt_owner_or_running_required")
            result = TaskResult(new_id(), task_id, attempt.attempt_id, payload, canonical_digest(payload), agent_id)
            self.results[result.result_id] = result
            attempt.status = "submitted"
            attempt.ended_at = time.time()
            attempt.revision += 1
            task.status = "submitted"
            task.revision += 1
            return result

    def review(
        self, task_id: str, reviewer_agent_id: str, result_id: str, *, decision: str,
        round_no: int = 1, reason: str | None = None,
    ) -> ReviewRound:
        if decision not in {"accepted", "changes_requested", "rejected"}:
            raise ValueError("invalid_review_decision")
        with self._lock:
            task = self._task(task_id)
            result = self.results.get(result_id)
            if result is None or result.task_id != task_id:
                raise TaskStateError("result_task_mismatch")
            if task.status != "submitted":
                raise TaskStateError("task_not_submitted")
            key = (result_id, round_no)
            if key in self.reviews:
                raise TaskStateError("review_round_exists")
            review = ReviewRound(round_no, result_id, reviewer_agent_id, decision, reason)
            self.reviews[key] = review
            attempt = self._current_attempt(task)
            if decision == "accepted":
                task.status = "completed"
                attempt.status = "completed"
            elif decision in {"changes_requested", "rejected"}:
                task.status = "changes_requested"
                attempt.status = "orphaned"
                task.current_attempt_id = None
            task.revision += 1
            return review

    def cancel(self, task_id: str, *, actor: str) -> Task:
        del actor
        with self._lock:
            task = self._task(task_id)
            if task.status in TASK_TERMINAL:
                raise TaskStateError("terminal_task")
            task.status = "cancelled"
            attempt = self.attempts.get(task.current_attempt_id or "")
            if attempt and attempt.status not in ATTEMPT_TERMINAL:
                attempt.status = "cancelled"
                attempt.ended_at = time.time()
            task.revision += 1
            return task

    def orphan(self, task_id: str, reason: str = "lease_expired") -> Task:
        with self._lock:
            task = self._task(task_id)
            attempt = self._current_attempt(task)
            attempt.status = "orphaned"
            attempt.revision += 1
            task.status = "orphaned"
            task.revision += 1
            task.orphan_reason = reason
            return task

    def request_scope(self, task_id: str, requested_scope: dict[str, Any], requester: str) -> str:
        with self._lock:
            request_id = new_id()
            self.scope_requests[request_id] = {
                "task_id": task_id, "requested_scope": requested_scope,
                "requester": requester, "status": "pending",
            }
            return request_id

    def approve_scope(
        self, request_id: str, *, approved_scope: dict[str, Any], approver: str,
        revoke_grants: Callable[[str], None] | None = None,
    ) -> Task:
        with self._lock:
            request = self.scope_requests[request_id]
            if request["status"] != "pending":
                raise TaskStateError("scope_request_closed")
            task = self._task(request["task_id"])
            request.update({"status": "approved", "approved_scope": approved_scope, "approver": approver})
            task.scope_revision += 1
            if task.status == "running":
                task.status = "blocked"
                if revoke_grants is not None:
                    revoke_grants(task.task_id)
            task.revision += 1
            return task

    def restore_open(self, task_ids: list[str]) -> list[Task]:
        with self._lock:
            tasks = [self._task(task_id) for task_id in task_ids]
            if any(task.status not in {"ready", "changes_requested"} for task in tasks):
                raise TaskStateError("restore_open_batch_failed")
            for task in tasks:
                task.status = "open"
                task.revision += 1
            return tasks

    def parent_chain(self, task_id: str) -> list[str]:
        chain: list[str] = []
        current = self._task(task_id)
        while current.parent_task_id is not None:
            chain.append(current.parent_task_id)
            current = self._task(current.parent_task_id)
        return chain

    def _task(self, task_id: str) -> Task:
        if task_id not in self.tasks:
            raise KeyError(task_id)
        return self.tasks[task_id]

    def _current_attempt(self, task: Task) -> Attempt:
        if task.current_attempt_id is None or task.current_attempt_id not in self.attempts:
            raise TaskStateError("no_current_attempt")
        return self.attempts[task.current_attempt_id]

    @staticmethod
    def _transition(task: Task, allowed: set[str], target: str) -> None:
        if task.status not in allowed:
            raise TaskStateError(f"invalid_transition:{task.status}->{target}")
        task.status = target
        task.revision += 1

    def _validate_dag(self) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise TaskStateError("blocks_cycle")
            if task_id in visited:
                return
            visiting.add(task_id)
            for blocked in self.tasks[task_id].blocks:
                visit(blocked)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in self.tasks:
            visit(task_id)
