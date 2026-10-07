"""Task execution invariants composed inside the existing command UoW."""

from __future__ import annotations

from typing import Any

from tsunagou.modules.cognition import CognitionService
from tsunagou.modules.tasks import Attempt, Task, TaskResult, TaskService, TaskStateError
from tsunagou.shared_kernel.errors import CommandRefused, RevisionConflict


def contract_refusal_detail(proposal_id: str, status: str | None) -> dict[str, Any]:
    """领活被契约门拒绝时要说清的三件事：是哪个契约、现在什么状态、下一步谁去做什么。

    ``status`` 传 ``None`` 表示**这个契约在本项目里根本不存在** —— 与"存在但还没被接受"是两回事
    （两种错、两种修法）。2026-10-07 实测：只回一个契约 id 时，撞墙的 agent 只能升级去问 main，
    那一轮三条任务因此多出 31 条消息 / 17 次领取 / 11 次回复的协商成本。
    """

    if status is None:
        return {
            "proposal_id": proposal_id,
            "status": "missing",
            "next": (
                f"任务要求的契约 {proposal_id} 在本项目里不存在：请 main 核对 required_contract_ids，"
                "改用一个已经存在的契约；发布任务前先把契约结清。"
            ),
        }
    return {
        "proposal_id": proposal_id,
        "status": status,
        "next": (
            f"契约 {proposal_id} 现在是 {status}，还不能领活：等它的参与者接受各自槽位"
            "（或由 main 用 contract.accept_proxy 代接受），变成 accepted 后再 task.begin；"
            "去 contract 出口看还差哪个槽、归谁。"
        ),
    }


def self_referential_contract_note(
    contract_id: str, participants: Any, worker_id: str, title: str,
) -> str | None:
    """任务要求的契约里有一个槽位归**这个任务的执行者**自己 —— 自指形状。

    它领活时会等契约变成 accepted，而契约要等它自己先接受那个槽位。**不是错误**（main 可以用
    ``contract.accept_proxy`` 代接受 ✓），但要在**下达计划那一刻**就说出来，而不是等它撞墙升级：
    2026-10-07 实测那次没人说，这一步变成 31 条消息 / 17 次领取的协商。
    """

    for participant in participants or ():
        if isinstance(participant, dict):
            agent_id, slot = participant.get("agent_id"), participant.get("slot")
        else:
            agent_id, slot = getattr(participant, "agent_id", None), getattr(participant, "slot", None)
        if str(agent_id or "") == str(worker_id or ""):
            return (
                f"任务「{title}」要求的契约 {contract_id} 有一个槽位归它自己（{slot}）：它领活时会等这个"
                f"契约变成 accepted，所以先让它（{worker_id}）接受 {slot} 槽位，或在它卡住时由你用 "
                "contract.accept_proxy 代接受。"
            )
    return None


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
                # 指名（哪个契约、什么状态、下一步）—— 代码保留 <id> 后缀，既有匹配照旧。
                raise CommandRefused(
                    "required_contract_not_accepted:" + proposal_id,
                    contract_refusal_detail(proposal_id, getattr(proposal, "status", None)),
                )
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
