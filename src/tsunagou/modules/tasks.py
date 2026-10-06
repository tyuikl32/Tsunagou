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
ATTEMPT_TERMINAL = {"submitted", "completed", "cancelled", "failed", "orphaned"}


@dataclass(slots=True)
class SuspensionSnapshot:
    task_id: str
    attempt_id: str | None
    reason: str
    checkpoint_summary: dict[str, Any] = field(default_factory=dict)
    dependency_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    captured_at: float = field(default_factory=time.time)


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
    execution_scope: dict[str, Any] = field(default_factory=dict)
    required_contract_ids: tuple[str, ...] = ()
    # "什么算合格"。2026-10-05 那轮最贵的返工就是工单上没有这一栏：管理员端交来错误业务域与
    # mock 实现，只有在集成之后才被人发现。它跟着任务走，Worker 在自己的上下文里就能读到。
    acceptance: str = ""
    # 被哪条任务替代了。2026-10-05 的做法是"取消旧的 + 新建替代的"，那条旧任务于是在看板上
    # 永远算"没做完"，也没人能从记录里看出它是被谁替代的（事件 E012/E014）。
    superseded_by: str = ""
    # 主 Agent 声明的"这条任务跨模块交界"。声明了就**必须**同时给出契约（在计划时强制），
    # 因为实测里最贵的语义冲突不重叠任何文件；这里记下来，是为了事后能看出到底声明过没有。
    cross_module: bool = False
    block_reason: str | None = None
    orphan_reason: str | None = None
    suspension_snapshot: SuspensionSnapshot | None = None


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


@dataclass(frozen=True, slots=True)
class PreflightResult:
    preflight_id: str
    task_id: str
    attempt_id: str
    status: str
    evidence_refs: tuple[str, ...]
    input_digest: str = ""
    blockers: tuple[str, ...] = ()
    task_revision: int = 0
    scope_revision: int = 0
    attempt_revision: int = 0
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return not self.blockers


@dataclass(frozen=True, slots=True)
class ProgressRecord:
    progress_id: str
    task_id: str
    attempt_id: str
    summary: str
    evidence_refs: tuple[str, ...]
    recorded_at: float


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
        self.preflights: dict[str, PreflightResult] = {}
        self.progress_records: dict[str, ProgressRecord] = {}

    def create_task(
        self, title: str, objective: str, *, parent_task_id: str | None = None,
        blocks: set[str] | None = None, execution_scope: dict[str, Any] | None = None,
        required_contract_ids: tuple[str, ...] = (), acceptance: str = "", cross_module: bool = False,
    ) -> Task:
        with self._lock:
            if parent_task_id is not None and parent_task_id not in self.tasks:
                raise KeyError(parent_task_id)
            task = Task(
                new_id(), title, objective, parent_task_id=parent_task_id,
                blocks=set(blocks or ()), execution_scope=dict(execution_scope or {}),
                required_contract_ids=required_contract_ids, acceptance=acceptance, cross_module=cross_module,
            )
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

    def remove_block(self, task_id: str, blocking_task_id: str) -> Task:
        with self._lock:
            task = self._task(task_id)
            task.blocks.discard(blocking_task_id)
            task.revision += 1
            return task

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

    def update_plan(
        self, task_id: str, *, title: str | None = None, objective: str | None = None,
        required_contract_ids: tuple[str, ...] | None = None, acceptance: str | None = None,
    ) -> Task:
        with self._lock:
            task = self._task(task_id)
            attempt = self.attempts.get(task.current_attempt_id or "")
            if (task.status not in {"draft", "ready", "open", "blocked", "changes_requested"}
                    or (attempt is not None and attempt.status in {"claimed", "running"})):
                raise TaskStateError("task_plan_not_editable")
            if title is not None:
                task.title = title
            if objective is not None:
                task.objective = objective
            if required_contract_ids is not None:
                task.required_contract_ids = required_contract_ids
            if acceptance is not None:
                task.acceptance = acceptance
            task.revision += 1
            return task

    def request_cancel(self, task_id: str, reason: str) -> Task:
        with self._lock:
            task = self._task(task_id)
            if task.status in TASK_TERMINAL:
                raise TaskStateError("terminal_task")
            attempt = self.attempts.get(task.current_attempt_id or "")
            if attempt is not None and attempt.status in {"claimed", "running"}:
                task.status = "cancel_requested"
            else:
                task.status = "cancelled"
                if attempt is not None and attempt.status == "blocked":
                    attempt.status = "cancelled"
                    attempt.ended_at = time.time()
                    attempt.revision += 1
            task.block_reason = reason
            task.revision += 1
            return task

    def supersede(self, task_id: str, *, superseded_by_task_id: str, reason: str) -> Task:
        """记下"这条任务被另一条替代了"，并让它退出领取队列。

        RLock 可重入，所以直接复用 ``request_cancel`` 的取消语义，不必抄一遍。已经是终态时
        （例如调用者先取消了它）只补记录 —— 那一步不该让承接关系变得无法追溯。
        """

        with self._lock:
            task = self._task(task_id)
            if superseded_by_task_id == task_id:
                raise ValueError("task_cannot_supersede_itself")
            if superseded_by_task_id not in self.tasks:
                raise KeyError(superseded_by_task_id)
            if task.status not in TASK_TERMINAL:
                self.request_cancel(task_id, reason)
            task.superseded_by = superseded_by_task_id
            task.revision += 1
            return task

    def fail(self, task_id: str, agent_id: str, *, attempt_id: str, reason: str) -> Task:
        with self._lock:
            task = self._task(task_id)
            attempt = self._current_attempt(task)
            if attempt.attempt_id != attempt_id or attempt.owner_agent_id != agent_id:
                raise TaskStateError("attempt_owner_required")
            if attempt.status in ATTEMPT_TERMINAL:
                raise TaskStateError("attempt_not_failible")
            attempt.status = "failed"
            attempt.ended_at = time.time()
            attempt.revision += 1
            task.status = "failed"
            task.block_reason = reason
            task.revision += 1
            return task

    def claim(self, task_id: str, agent_id: str) -> Attempt:
        with self._lock:
            task = self._task(task_id)
            # A suspension is a task state, not an execution lease. Once the
            # previous Attempt has been detached, any later eligible Agent may
            # claim the task; joining time must not determine task ownership.
            if task.status not in {"open", "blocked", "orphaned"}:
                raise TaskStateError("task_not_claimable")
            current = self.attempts.get(task.current_attempt_id or "")
            if current is not None and current.status not in ATTEMPT_TERMINAL | {"blocked"}:
                raise TaskStateError("task_not_claimable")
            if current is not None and current.status == "blocked":
                current.status = "orphaned"
                current.ended_at = time.time()
                current.revision += 1
            attempt = Attempt(new_id(), task_id, agent_id)
            self.attempts[attempt.attempt_id] = attempt
            task.current_attempt_id = attempt.attempt_id
            task.status = "claimed"
            task.block_reason = None
            task.orphan_reason = None
            task.revision += 1
            return attempt

    def resume(self, task_id: str, agent_id: str) -> Attempt:
        with self._lock:
            task = self._task(task_id)
            if task.status != "blocked":
                raise TaskStateError("task_not_resumable")
            current = self.attempts.get(task.current_attempt_id or "")
            suspended_id = task.suspension_snapshot.attempt_id if task.suspension_snapshot else None
            suspended = self.attempts.get(suspended_id or "")
            owner = current or suspended
            if owner is None or owner.owner_agent_id != agent_id:
                raise TaskStateError("attempt_owner_required")
            if current is None or current.status in ATTEMPT_TERMINAL:
                current = Attempt(new_id(), task_id, agent_id)
                self.attempts[current.attempt_id] = current
                task.current_attempt_id = current.attempt_id
            current.status = "claimed"
            current.revision += 1
            task.status = "claimed"
            task.block_reason = None
            task.revision += 1
            return current

    def clear_blocker(self, task_id: str, expected_reason: str) -> Task:
        """Clear one resolved blocker while preserving the task's suspension state."""
        with self._lock:
            task = self._task(task_id)
            if task.block_reason != expected_reason:
                raise TaskStateError("blocker_revision_conflict")
            task.block_reason = None
            task.revision += 1
            return task

    def preflight(
        self, task_id: str, agent_id: str, *, attempt_id: str | None = None,
        evidence_refs: tuple[str, ...] = (), input_digest: str = "",
        blockers: tuple[str, ...] = (), evidence: dict[str, Any] | None = None,
    ) -> PreflightResult:
        with self._lock:
            task = self._task(task_id)
            attempt = self._current_attempt(task)
            if attempt.owner_agent_id != agent_id:
                raise TaskStateError("attempt_owner_required")
            if task.status != "claimed":
                raise TaskStateError("task_not_preflightable")
            if attempt_id is not None and attempt_id != attempt.attempt_id:
                raise TaskStateError("attempt_id_mismatch")
            preflight = PreflightResult(
                new_id(), task_id, attempt.attempt_id, "preflighted", evidence_refs,
                input_digest, blockers, task.revision, task.scope_revision,
                attempt.revision, dict(evidence or {}),
            )
            self.preflights[preflight.preflight_id] = preflight
            return preflight

    def start(
        self, task_id: str, agent_id: str, *, workspace_ready: bool = True,
        lease_valid: bool = True, contract_ready: bool = True, report_ready: bool = True,
        preflight_id: str | None = None, require_preflight: bool = False,
    ) -> Attempt:
        with self._lock:
            task = self._task(task_id)
            attempt = self._current_attempt(task)
            if attempt.owner_agent_id != agent_id:
                raise TaskStateError("attempt_owner_required")
            if attempt.status != "claimed" or task.status != "claimed":
                raise TaskStateError("attempt_not_startable")
            if require_preflight and preflight_id is None:
                raise TaskStateError("preflight_required")
            if preflight_id is not None:
                preflight = self.preflights.get(preflight_id)
                if preflight is None or preflight.task_id != task_id or preflight.attempt_id != attempt.attempt_id:
                    raise TaskStateError("preflight_id_mismatch")
            missing = [name for name, value in {
                "workspace": workspace_ready, "lease": lease_valid,
                "contract": contract_ready, "report": report_ready,
            }.items() if not value]
            if missing:
                previous_attempt_id = attempt.attempt_id
                attempt.status = "blocked"
                attempt.revision += 1
                task.status = "blocked"
                task.revision += 1
                task.block_reason = "start_blocked:" + ",".join(missing)
                task.suspension_snapshot = SuspensionSnapshot(
                    task_id=task_id, attempt_id=previous_attempt_id,
                    reason=task.block_reason,
                )
                raise TaskStateError("start_blocked:" + ",".join(missing))
            attempt.status = "running"
            attempt.started_at = time.time()
            attempt.revision += 1
            task.status = "running"
            task.revision += 1
            return attempt

    def progress(
        self, task_id: str, agent_id: str, *, attempt_id: str | None = None,
        summary: str = "", evidence_refs: tuple[str, ...] = (),
    ) -> ProgressRecord:
        with self._lock:
            task = self._task(task_id)
            attempt = self._current_attempt(task)
            if attempt.owner_agent_id != agent_id or attempt.status != "running" or task.status != "running":
                raise TaskStateError("attempt_owner_or_running_required")
            if attempt_id is not None and attempt_id != attempt.attempt_id:
                raise TaskStateError("attempt_id_mismatch")
            record = ProgressRecord(
                new_id(), task_id, attempt.attempt_id, summary, evidence_refs, time.time()
            )
            self.progress_records[record.progress_id] = record
            return record

    def block(
        self, task_id: str, reason: str, *, checkpoint_summary: dict[str, Any] | None = None,
        dependency_refs: tuple[str, ...] = (), evidence_refs: tuple[str, ...] = (),
    ) -> Task:
        with self._lock:
            task = self._task(task_id)
            if task.status in TASK_TERMINAL:
                raise TaskStateError("terminal_task")
            previous_attempt_id = task.current_attempt_id
            previous_attempt = self.attempts.get(previous_attempt_id or "")
            if previous_attempt is not None and previous_attempt.status not in ATTEMPT_TERMINAL:
                previous_attempt.status = "blocked"
                previous_attempt.revision += 1
            # The blocked task remains durable and claimable. The old Attempt
            # remains resumable by its owner, but holds no execution lease.
            task.status = "blocked"
            task.revision += 1
            task.block_reason = reason
            task.suspension_snapshot = SuspensionSnapshot(
                task_id=task_id, attempt_id=previous_attempt_id, reason=reason,
                checkpoint_summary=dict(checkpoint_summary or {}),
                dependency_refs=tuple(dependency_refs), evidence_refs=tuple(evidence_refs),
            )
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
                attempt.revision += 1
            task.revision += 1
            return task

    def acknowledge_cancel(self, task_id: str, agent_id: str, *, attempt_id: str) -> Task:
        with self._lock:
            task = self._task(task_id)
            attempt = self._current_attempt(task)
            if task.status != "cancel_requested":
                raise TaskStateError("cancel_not_requested")
            if attempt.attempt_id != attempt_id or attempt.owner_agent_id != agent_id:
                raise TaskStateError("attempt_owner_required")
            task.status = "cancelled"
            attempt.status = "cancelled"
            attempt.ended_at = time.time()
            attempt.revision += 1
            task.revision += 1
            return task

    def orphan(self, task_id: str, reason: str = "lease_expired") -> Task:
        with self._lock:
            task = self._task(task_id)
            attempt = self.attempts.get(task.current_attempt_id or "")
            if attempt is not None:
                attempt.status = "orphaned"
                attempt.ended_at = time.time()
                attempt.revision += 1
            # Resource expiry fences only the old execution. It must not turn
            # the durable task into a lease that requires the same Agent to
            # return before another Agent can claim it.
            task.current_attempt_id = None
            # Lease expiry fences only the old execution attempt. The durable
            # task returns to the public queue and does not require the old
            # Agent, bridge, or conversation to come back.
            task.status = "open"
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

    def reject_scope(self, request_id: str, *, approver: str) -> dict[str, Any]:
        with self._lock:
            request = self.scope_requests[request_id]
            if request["status"] != "pending":
                raise TaskStateError("scope_request_closed")
            request.update({"status": "rejected", "approver": approver})
            return request

    def recover(self, task_id: str, *, expected_attempt_id: str, disposition: str) -> Task:
        with self._lock:
            task = self._task(task_id)
            if task.status in TASK_TERMINAL:
                raise TaskStateError("terminal_task")
            attempt = self.attempts.get(expected_attempt_id)
            if attempt is None or attempt.task_id != task_id:
                raise TaskStateError("attempt_not_found")
            if task.current_attempt_id is not None and task.current_attempt_id != expected_attempt_id:
                raise TaskStateError("attempt_id_mismatch")
            if disposition == "reopen":
                if task.current_attempt_id is None and attempt.status in ATTEMPT_TERMINAL:
                    # Nothing is owned and the named attempt has already ended, so this
                    # recovery already happened. Re-applying it would mint a new revision
                    # for a state change that did not occur, which silently invalidates
                    # every other agent's expected revision.
                    raise TaskStateError("attempt_already_recovered")
                if task.status not in {"open", "claimed", "running", "blocked", "orphaned", "cancel_requested", "changes_requested"}:
                    raise TaskStateError("task_not_recoverable")
                if attempt.status not in {"claimed", "running", "blocked", "orphaned", "failed", "cancelled"}:
                    raise TaskStateError("attempt_not_recoverable")
                if attempt.status not in ATTEMPT_TERMINAL:
                    attempt.status = "orphaned"
                    attempt.ended_at = time.time()
                    attempt.revision += 1
                task.current_attempt_id = None
                task.status = "open"
                task.block_reason = None
                task.orphan_reason = None
                task.revision += 1
                return task
            if disposition == "cancel":
                task.status = "cancelled"
                if attempt.status not in ATTEMPT_TERMINAL:
                    attempt.status = "cancelled"
                    attempt.ended_at = time.time()
                    attempt.revision += 1
                task.revision += 1
                return task
            if disposition == "fail":
                task.status = "failed"
                if attempt.status not in ATTEMPT_TERMINAL:
                    attempt.status = "failed"
                    attempt.ended_at = time.time()
                    attempt.revision += 1
                task.revision += 1
                return task
            raise ValueError("invalid_recovery_disposition")

    def approve_scope(
        self, request_id: str, *, approved_scope: dict[str, Any], approver: str,
        revoke_grants: Callable[[str], None] | None = None,
    ) -> Task:
        with self._lock:
            request = self.scope_requests[request_id]
            if request["status"] != "pending":
                raise TaskStateError("scope_request_closed")
            task = self._task(request["task_id"])
            if task.status in {"claimed", "running", "cancel_requested"} | TASK_TERMINAL:
                raise TaskStateError("scope_change_requires_stopped_task")
            request.update({"status": "approved", "approved_scope": approved_scope, "approver": approver})
            task.execution_scope = dict(approved_scope)
            task.scope_revision += 1
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

    def open_work_for(self, agent_id: str) -> list[dict[str, Any]]:
        """这个 Agent 手上还压着的活：占着 Attempt，或者任务还没收尾。

        退役要拒绝的是"把活悄悄搁下"：调用方把这份清单摆给人看，让人自己决定先收尾还是
        先把活交出去 —— 第一版不做自动收敛（那牵扯任务状态机，风险不是一个量级）。
        """

        held: list[dict[str, Any]] = []
        for task in self.tasks.values():
            attempt = self.attempts.get(task.current_attempt_id or "")
            owns_attempt = (
                attempt is not None and attempt.owner_agent_id == agent_id
                and attempt.status not in ATTEMPT_TERMINAL
            )
            if not owns_attempt or task.status in TASK_TERMINAL:
                continue
            held.append({
                "task_id": task.task_id, "title": task.title, "status": task.status,
                "attempt_id": attempt.attempt_id if attempt else None,
                "attempt_status": attempt.status if attempt else None,
            })
        return sorted(held, key=lambda item: str(item["task_id"]))

    def describe_task(self, task_id: str) -> dict[str, Any]:
        task = self._task(task_id)
        attempt = self.attempts.get(task.current_attempt_id or "")
        scope = task.execution_scope if isinstance(task.execution_scope, dict) else {}
        declared = scope.get("resources")
        resources: list[Any] = declared if isinstance(declared, list) else []
        # 这个任务要不要工作区：资源请求里有 `path` 那一行就是"要碰文件"。说出来是为了让人和 Agent
        # **在开工之前**就知道 —— 远端那台机器没报代码副本时接不了它（D191/D192），别白跑一趟。
        requires_workspace = bool(scope.get("roots")) or any(
            isinstance(row, dict) and row.get("kind") == "path" for row in resources
        )
        return {
            "task_id": task.task_id, "title": task.title, "objective": task.objective,
            "status": task.status, "revision": task.revision, "scope_revision": task.scope_revision,
            "execution_scope": task.execution_scope, "required_contract_ids": list(task.required_contract_ids),
            "blocks": sorted(task.blocks), "current_attempt_id": task.current_attempt_id,
            "owner_agent_id": attempt.owner_agent_id if attempt is not None else None,
            "block_reason": task.block_reason,
            "acceptance": task.acceptance,
            "superseded_by": task.superseded_by,
            "cross_module": task.cross_module,
            "requires_workspace": requires_workspace,
        }

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
