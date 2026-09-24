"""Durable coordination plans, worker assignments, and host wake state.

The coordination module stores mechanical facts about a Main-created plan.  It
does not decide how a task should be split or what a worker should implement;
those remain Main/LLM responsibilities.  In particular, a wake is only an
accepted host turn until the worker sends ``worker.ready``.  Execution leases
must not be acquired before that second acknowledgement.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from tsunagou.shared_kernel.digests import canonical_digest
from tsunagou.shared_kernel.ids import new_id

WAKE_STATES = {"pending", "host_accepted", "ready", "failed", "expired", "takeover"}
DEFAULT_WAKE_DEADLINE_SECONDS = 60.0
DEFAULT_MAX_WAKE_ATTEMPTS = 3
ASSIGNMENT_STATES = {
    "planned", "waking", "host_accepted", "ready", "claimed", "running",
    "submitted", "blocked", "failed", "takeover", "completed",
}


@dataclass(frozen=True, slots=True)
class CoordinationEvent:
    event_id: str
    kind: str
    actor_id: str | None = None
    assignment_id: str | None = None
    task_id: str | None = None
    summary: str = ""
    important: bool = False
    created_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class WakeAttempt:
    wake_attempt_id: str
    assignment_id: str
    task_id: str
    worker_id: str
    wake_id: str
    retry_count: int = 0
    deadline: float | None = None
    host_accepted: bool = False
    host_turn_id: str | None = None
    worker_ready: bool = False
    status: str = "pending"
    failure_reason: str | None = None
    previous_attempt_id: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class CoordinationAssignment:
    assignment_id: str
    plan_id: str
    task_id: str
    assigned_worker_id: str
    dependencies: tuple[str, ...] = ()
    acceptance_conditions: dict[str, Any] = field(default_factory=dict)
    workspace: dict[str, Any] = field(default_factory=dict)
    resource_intent: dict[str, Any] = field(default_factory=dict)
    auto_wake: bool = False
    status: str = "planned"
    wake_attempt_id: str | None = None
    ready_at: float | None = None
    claimed_attempt_id: str | None = None
    started_at: float | None = None
    submitted_at: float | None = None
    takeover_agent_id: str | None = None
    takeover_reason: str | None = None


@dataclass(slots=True)
class CoordinationPlan:
    plan_id: str
    main_agent_id: str
    objective: str
    auto_wake: bool
    assignment_ids: tuple[str, ...]
    status: str = "active"
    created_at: float = field(default_factory=time.time)


class CoordinationService:
    """In-memory domain store captured by :class:`ServiceStateRuntime`."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.plans: dict[str, CoordinationPlan] = {}
        self.assignments: dict[str, CoordinationAssignment] = {}
        self.wake_attempts: dict[str, WakeAttempt] = {}
        self.events: list[CoordinationEvent] = []
        self._task_index: dict[str, str] = {}

    def record_event(
        self, kind: str, *, actor_id: str | None = None,
        assignment_id: str | None = None, task_id: str | None = None,
        summary: str = "", important: bool = False,
    ) -> CoordinationEvent:
        event = CoordinationEvent(
            event_id=new_id(), kind=kind, actor_id=actor_id,
            assignment_id=assignment_id, task_id=task_id,
            summary=summary, important=important,
        )
        with self._lock:
            self.events.append(event)
        return event

    def create_plan(
        self, *, main_agent_id: str, objective: str,
        assignments: list[dict[str, Any]], auto_wake: bool = False,
        wake_deadline_seconds: float = 60.0,
    ) -> CoordinationPlan:
        if not objective or not assignments:
            raise ValueError("coordination_plan_requires_objective_and_assignments")
        if wake_deadline_seconds <= 0:
            raise ValueError("invalid_wake_deadline")
        task_ids = [str(item.get("task_id") or "") for item in assignments]
        worker_ids = [str(item.get("assigned_worker_id") or "") for item in assignments]
        if any(not value for value in task_ids + worker_ids):
            raise ValueError("assignment_task_and_worker_required")
        if len(set(task_ids)) != len(task_ids):
            raise ValueError("duplicate_assignment_task")
        if len(set(worker_ids)) != len(worker_ids):
            raise ValueError("duplicate_assignment_worker")
        now = time.time()
        with self._lock:
            plan_id = new_id()
            created: list[CoordinationAssignment] = []
            for item in assignments:
                assignment = CoordinationAssignment(
                    assignment_id=new_id(), plan_id=plan_id,
                    task_id=str(item["task_id"]),
                    assigned_worker_id=str(item["assigned_worker_id"]),
                    dependencies=tuple(str(value) for value in item.get("dependencies") or ()),
                    acceptance_conditions=dict(item.get("acceptance_conditions") or {}),
                    workspace=dict(item.get("workspace") or {}),
                    resource_intent=dict(item.get("resource_intent") or {}),
                    auto_wake=bool(item.get("auto_wake", auto_wake)),
                    status="waking" if bool(item.get("auto_wake", auto_wake)) else "planned",
                )
                created.append(assignment)
            plan = CoordinationPlan(
                plan_id, main_agent_id, objective, bool(auto_wake),
                tuple(item.assignment_id for item in created),
                created_at=now,
            )
            self.plans[plan_id] = plan
            for assignment in created:
                self.assignments[assignment.assignment_id] = assignment
                self._task_index[assignment.task_id] = assignment.assignment_id
                if assignment.auto_wake:
                    wake = WakeAttempt(
                        wake_attempt_id=new_id(), assignment_id=assignment.assignment_id,
                        task_id=assignment.task_id, worker_id=assignment.assigned_worker_id,
                        wake_id=new_id(), deadline=now + wake_deadline_seconds,
                    )
                    self.wake_attempts[wake.wake_attempt_id] = wake
                    assignment.wake_attempt_id = wake.wake_attempt_id
            return plan

    def assignment_for_task(self, task_id: str) -> CoordinationAssignment | None:
        with self._lock:
            assignment_id = self._task_index.get(task_id)
            return self.assignments.get(assignment_id or "")

    def assignment(self, assignment_id: str) -> CoordinationAssignment:
        try:
            return self.assignments[assignment_id]
        except KeyError as exc:
            raise KeyError("assignment_not_found") from exc

    def wake(self, assignment_id: str) -> WakeAttempt:
        assignment = self.assignment(assignment_id)
        if assignment.wake_attempt_id is None:
            raise ValueError("wake_not_configured")
        return self.wake_attempts[assignment.wake_attempt_id]

    @staticmethod
    def _wake_is_due(wake: WakeAttempt, now: float) -> bool:
        """Return whether a still-open wake has crossed its host deadline."""
        return (
            wake.deadline is not None
            and now >= wake.deadline
            and not wake.worker_ready
            and wake.status in {"pending", "host_accepted"}
        )

    @staticmethod
    def _wake_deadline_window(wake: WakeAttempt) -> float:
        """Recover the configured deadline window from a durable attempt."""
        if wake.deadline is not None and wake.created_at:
            window = wake.deadline - wake.created_at
            if window > 0:
                return window
        return DEFAULT_WAKE_DEADLINE_SECONDS

    def _create_wake_retry_locked(
        self, assignment: CoordinationAssignment, current: WakeAttempt, *,
        now: float, deadline_seconds: float,
    ) -> WakeAttempt:
        """Create the next host wake while the coordination lock is held."""
        retry = WakeAttempt(
            wake_attempt_id=new_id(), assignment_id=assignment.assignment_id,
            task_id=current.task_id, worker_id=current.worker_id,
            wake_id=new_id(), retry_count=current.retry_count + 1,
            deadline=now + deadline_seconds, previous_attempt_id=current.wake_attempt_id,
            created_at=now, updated_at=now,
        )
        self.wake_attempts[retry.wake_attempt_id] = retry
        assignment.wake_attempt_id = retry.wake_attempt_id
        assignment.status = "waking"
        self.record_event(
            "wake.retry", assignment_id=assignment.assignment_id,
            task_id=assignment.task_id,
            summary=f"retry {retry.retry_count}", important=True,
        )
        return retry

    def _expire_wake_locked(
        self, assignment: CoordinationAssignment, current: WakeAttempt, *,
        now: float, max_attempts: int, deadline_seconds: float,
    ) -> WakeAttempt | None:
        """Expire one attempt and, when allowed, schedule its next attempt.

        This method only mutates wake/assignment state.  In particular it does
        not acquire, renew, or release an execution Lease.  Historical wake
        attempts remain ``expired`` so a query can explain why a retry exists.
        """
        current.status = "expired"
        current.failure_reason = "wake_deadline_expired"
        current.updated_at = now
        self.record_event(
            "wake.expired", assignment_id=assignment.assignment_id,
            task_id=assignment.task_id,
            summary="wake deadline expired", important=True,
        )
        if current.retry_count < max_attempts - 1:
            return self._create_wake_retry_locked(
                assignment, current, now=now, deadline_seconds=deadline_seconds,
            )
        assignment.status = "blocked"
        self.record_event(
            "wake.failed", assignment_id=assignment.assignment_id,
            task_id=assignment.task_id,
            summary="wake deadline expired after retry limit", important=True,
        )
        return None

    def reconcile_wake_deadlines(
        self, *, now: float | None = None,
        max_attempts: int = DEFAULT_MAX_WAKE_ATTEMPTS,
        deadline_seconds: float | None = None,
    ) -> int:
        """Advance every due WakeAttempt and return the number processed.

        Runtime maintenance calls this narrow reconciliation method.  It only
        deals with host wake state: no execution Lease is created, renewed, or
        released here.  A retry is a new durable WakeAttempt with a fresh
        deadline; at most ``max_attempts`` total attempts are allowed,
        including the initial attempt.
        """
        if max_attempts < 1:
            raise ValueError("invalid_wake_max_attempts")
        if deadline_seconds is not None and deadline_seconds <= 0:
            raise ValueError("invalid_wake_deadline")
        current_time = time.time() if now is None else float(now)
        processed = 0
        with self._lock:
            for assignment in list(self.assignments.values()):
                if not assignment.auto_wake or assignment.status in {"completed", "takeover"}:
                    continue
                current = self.wake_attempts.get(assignment.wake_attempt_id or "")
                if current is None or not self._wake_is_due(current, current_time):
                    continue
                self._expire_wake_locked(
                    assignment, current, now=current_time,
                    max_attempts=max_attempts,
                    deadline_seconds=(
                        deadline_seconds
                        if deadline_seconds is not None
                        else self._wake_deadline_window(current)
                    ),
                )
                processed += 1
        return processed

    def record_host_accepted(
        self, assignment_id: str, *, host_turn_id: str | None = None,
        wake_attempt_id: str | None = None,
    ) -> WakeAttempt:
        with self._lock:
            if not isinstance(wake_attempt_id, str) or not wake_attempt_id:
                raise ValueError("wake_attempt_id_required")
            assignment = self.assignment(assignment_id)
            wake = self.wake(assignment_id)
            if wake_attempt_id != wake.wake_attempt_id:
                raise ValueError("stale_wake_attempt")
            now = time.time()
            if self._wake_is_due(wake, now):
                self._expire_wake_locked(
                    assignment, wake, now=now,
                    max_attempts=DEFAULT_MAX_WAKE_ATTEMPTS,
                    deadline_seconds=self._wake_deadline_window(wake),
                )
                raise ValueError("wake_deadline_expired")
            if wake.status in {"failed", "expired", "takeover"}:
                raise ValueError("wake_attempt_closed")
            wake.host_accepted = True
            wake.host_turn_id = host_turn_id
            wake.status = "host_accepted"
            wake.updated_at = now
            if assignment.status == "waking":
                assignment.status = "host_accepted"
            return wake

    def record_worker_ready(
        self, assignment_id: str, *, worker_id: str,
        wake_attempt_id: str | None = None,
    ) -> WakeAttempt:
        with self._lock:
            if not isinstance(wake_attempt_id, str) or not wake_attempt_id:
                raise ValueError("wake_attempt_id_required")
            assignment = self.assignment(assignment_id)
            if assignment.assigned_worker_id != worker_id:
                raise PermissionError("assignment_worker_mismatch")
            wake = self.wake(assignment_id)
            if wake_attempt_id != wake.wake_attempt_id:
                raise ValueError("stale_wake_attempt")
            now = time.time()
            if self._wake_is_due(wake, now):
                self._expire_wake_locked(
                    assignment, wake, now=now,
                    max_attempts=DEFAULT_MAX_WAKE_ATTEMPTS,
                    deadline_seconds=self._wake_deadline_window(wake),
                )
                raise ValueError("wake_deadline_expired")
            if assignment.auto_wake and not wake.host_accepted:
                raise ValueError("host_acceptance_required")
            if wake.status in {"failed", "expired", "takeover"}:
                raise ValueError("wake_attempt_closed")
            wake.worker_ready = True
            wake.status = "ready"
            wake.updated_at = now
            assignment.status = "ready"
            assignment.ready_at = now
            return wake

    def retry_wake(
        self, assignment_id: str, *, max_attempts: int = DEFAULT_MAX_WAKE_ATTEMPTS,
        deadline_seconds: float | None = None,
    ) -> WakeAttempt:
        with self._lock:
            if max_attempts < 1:
                raise ValueError("invalid_wake_max_attempts")
            if deadline_seconds is not None and deadline_seconds <= 0:
                raise ValueError("invalid_wake_deadline")
            assignment = self.assignment(assignment_id)
            current = self.wake(assignment_id)
            if current.worker_ready:
                raise ValueError("worker_already_ready")
            # retry_count is zero for the initial attempt.  Three total host
            # attempts therefore permit retry_count values 0, 1, and 2.
            if max_attempts < 1 or current.retry_count >= max_attempts - 1:
                raise ValueError("wake_retry_limit_exceeded")
            current.status = "failed"
            current.failure_reason = "wake_retry"
            now = time.time()
            current.updated_at = now
            retry = self._create_wake_retry_locked(
                assignment, current, now=now,
                deadline_seconds=(
                    deadline_seconds
                    if deadline_seconds is not None
                    else self._wake_deadline_window(current)
                ),
            )
            return retry

    def mark_wake_failed(self, assignment_id: str, *, reason: str, expired: bool = False) -> WakeAttempt:
        with self._lock:
            wake = self.wake(assignment_id)
            wake.status = "expired" if expired else "failed"
            wake.failure_reason = reason
            wake.updated_at = time.time()
            assignment = self.assignment(assignment_id)
            assignment.status = "blocked"
            self.record_event(
                "wake.failed", assignment_id=assignment.assignment_id,
                task_id=assignment.task_id, summary=reason, important=True,
            )
            return wake

    def require_worker_ready(self, task_id: str, worker_id: str) -> CoordinationAssignment | None:
        with self._lock:
            assignment = self.assignment_for_task(task_id)
            if assignment is None:
                return None
            if worker_id not in {assignment.assigned_worker_id, assignment.takeover_agent_id}:
                raise PermissionError("assignment_worker_mismatch")
            for dependency in assignment.dependencies:
                dependency_assignment = self.assignments.get(dependency) or self.assignment_for_task(dependency)
                if dependency_assignment is not None and dependency_assignment.status != "completed":
                    raise ValueError("coordination_dependency_pending")
            if assignment.auto_wake and assignment.status not in {"ready", "claimed", "running", "submitted", "completed", "takeover"}:
                raise ValueError("worker_ready_required")
            return assignment

    def mark_claimed(self, task_id: str, worker_id: str, attempt_id: str) -> None:
        with self._lock:
            assignment = self.require_worker_ready(task_id, worker_id)
            if assignment is None:
                return
            assignment.status = "claimed"
            assignment.claimed_attempt_id = attempt_id

    def mark_started(self, task_id: str, worker_id: str, attempt_id: str) -> None:
        with self._lock:
            assignment = self.assignment_for_task(task_id)
            if assignment is None:
                return
            if (
                worker_id not in {assignment.assigned_worker_id, assignment.takeover_agent_id}
                or assignment.claimed_attempt_id != attempt_id
            ):
                raise PermissionError("assignment_attempt_mismatch")
            assignment.status = "running"
            assignment.started_at = time.time()

    def mark_lease_expired(self, task_id: str, attempt_id: str) -> bool:
        """Fence an assignment whose execution Lease expired.

        Lease expiry is an execution failure for the claimed attempt.  Keep
        the assignment and its wake history durable for Main, but clear the
        attempt ownership so a later retry cannot be mistaken for the fenced
        execution.  The attempt id check is an important stale-event fence:
        expiry of an old attempt must never block a newer claim on the same
        assignment.

        The method is intentionally idempotent.  A second reconciliation pass
        observes the already-blocked assignment with no claimed attempt and
        therefore emits no duplicate event.
        """
        with self._lock:
            assignment = self.assignment_for_task(task_id)
            if assignment is None or assignment.claimed_attempt_id != attempt_id:
                return False
            if assignment.status in {"claimed", "running"}:
                assignment.status = "blocked"
            elif assignment.status == "blocked":
                # A prior pass may have persisted the status before clearing
                # the attempt metadata.  Finish that cleanup without another
                # state transition or wake attempt.
                pass
            else:
                return False
            assignment.claimed_attempt_id = None
            assignment.started_at = None
            self.record_event(
                "lease.expired", assignment_id=assignment.assignment_id,
                task_id=assignment.task_id,
                summary="resource lease expired; execution fenced",
                important=True,
            )
            return True

    def mark_submitted(self, task_id: str, worker_id: str, attempt_id: str) -> None:
        with self._lock:
            assignment = self.assignment_for_task(task_id)
            if assignment is None:
                return
            if (
                worker_id not in {assignment.assigned_worker_id, assignment.takeover_agent_id}
                or assignment.claimed_attempt_id != attempt_id
            ):
                raise PermissionError("assignment_attempt_mismatch")
            assignment.status = "submitted"
            assignment.submitted_at = time.time()

    def mark_completed(self, task_id: str, worker_id: str, attempt_id: str) -> None:
        with self._lock:
            assignment = self.assignment_for_task(task_id)
            if assignment is None:
                return
            if (
                worker_id not in {assignment.assigned_worker_id, assignment.takeover_agent_id}
                or assignment.claimed_attempt_id != attempt_id
            ):
                raise PermissionError("assignment_attempt_mismatch")
            assignment.status = "completed"

    def mark_blocked(self, task_id: str, worker_id: str) -> None:
        with self._lock:
            assignment = self.assignment_for_task(task_id)
            if assignment is None:
                return
            if worker_id not in {assignment.assigned_worker_id, assignment.takeover_agent_id}:
                raise PermissionError("assignment_worker_mismatch")
            assignment.status = "blocked"

    def mark_failed(self, task_id: str, worker_id: str) -> None:
        with self._lock:
            assignment = self.assignment_for_task(task_id)
            if assignment is None:
                return
            if worker_id not in {assignment.assigned_worker_id, assignment.takeover_agent_id}:
                raise PermissionError("assignment_worker_mismatch")
            assignment.status = "failed"

    def rework(self, assignment_id: str, *, reason: str, wake_deadline_seconds: float = 60.0) -> WakeAttempt | None:
        """Close a reviewed result and create a fresh wake for the same worker."""
        if not reason:
            raise ValueError("rework_reason_required")
        with self._lock:
            assignment = self.assignment(assignment_id)
            assignment.claimed_attempt_id = None
            assignment.started_at = None
            assignment.submitted_at = None
            if not assignment.auto_wake:
                assignment.status = "planned"
                return None
            previous = assignment.wake_attempt_id
            now = time.time()
            wake = WakeAttempt(
                wake_attempt_id=new_id(), assignment_id=assignment.assignment_id,
                task_id=assignment.task_id, worker_id=assignment.assigned_worker_id,
                wake_id=new_id(), retry_count=0, deadline=now + wake_deadline_seconds,
                previous_attempt_id=previous,
            )
            self.wake_attempts[wake.wake_attempt_id] = wake
            assignment.wake_attempt_id = wake.wake_attempt_id
            assignment.status = "waking"
            self.record_event(
                "task.rework", assignment_id=assignment.assignment_id,
                task_id=assignment.task_id, summary=reason, important=True,
            )
            return wake

    def takeover(
        self, assignment_id: str, *, main_agent_id: str, reason: str,
    ) -> CoordinationAssignment:
        if not reason:
            raise ValueError("takeover_reason_required")
        with self._lock:
            assignment = self.assignment(assignment_id)
            if assignment.status in {"completed", "submitted"}:
                raise ValueError("assignment_already_finished")
            if assignment.wake_attempt_id is not None:
                wake = self.wake(assignment_id)
                wake.status = "takeover"
                wake.failure_reason = reason
                wake.updated_at = time.time()
            assignment.status = "takeover"
            assignment.takeover_agent_id = main_agent_id
            assignment.takeover_reason = reason
            return assignment

    def coverage(self, plan_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            assignments = [
                item for item in self.assignments.values()
                if plan_id is None or item.plan_id == plan_id
            ]
            counts = {state: 0 for state in ASSIGNMENT_STATES}
            for item in assignments:
                counts[item.status] = counts.get(item.status, 0) + 1
            return {
                "plan_id": plan_id,
                "total": len(assignments),
                "by_status": counts,
                "assigned_worker_ids": sorted({item.assigned_worker_id for item in assignments}),
                "coverage_digest": canonical_digest({
                    "plan_id": plan_id, "assignments": [
                        (item.assignment_id, item.task_id, item.assigned_worker_id, item.status)
                        for item in assignments
                    ],
                }),
            }

    def invalidate_execution_state(self) -> None:
        """Fence in-flight assignments when a daemon runtime epoch rotates."""
        with self._lock:
            now = time.time()
            for assignment in self.assignments.values():
                if assignment.status not in {"claimed", "running", "host_accepted", "ready"}:
                    continue
                assignment.claimed_attempt_id = None
                assignment.started_at = None
                if not assignment.auto_wake:
                    assignment.status = "planned"
                    continue
                current = self.wake_attempts.get(assignment.wake_attempt_id or "")
                if current is not None and current.status not in {"failed", "expired", "takeover"}:
                    current.status = "failed"
                    current.failure_reason = "runtime_epoch_rotated"
                    current.updated_at = now
                retry_count = (current.retry_count + 1) if current is not None else 0
                replacement = WakeAttempt(
                    wake_attempt_id=new_id(), assignment_id=assignment.assignment_id,
                    task_id=assignment.task_id, worker_id=assignment.assigned_worker_id,
                    wake_id=new_id(), retry_count=retry_count, deadline=now + 60.0,
                    previous_attempt_id=current.wake_attempt_id if current is not None else None,
                )
                self.wake_attempts[replacement.wake_attempt_id] = replacement
                assignment.wake_attempt_id = replacement.wake_attempt_id
                assignment.status = "waking"
