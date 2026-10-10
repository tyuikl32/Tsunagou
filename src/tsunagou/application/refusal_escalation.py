"""同一个任务被同一个错误拒了两次，就要有人知道（待改 18-③）。

一次拒绝是调用方自己的事：它拿到拒绝码、拿到下一步，自己改或自己重试就好 —— 这也正是
``api/app.py`` 把每次拒绝都记成 ``command.<kind>.denied`` 的原因。但**同一个任务反复撞同一堵墙**
是另一件事：任务本身是个坑，还会有别人踩进来，而今天这件事只留在被拒者的返回里。
2026-10-08 实测：同一条任务在 21 秒里被拒 4 次（``required_contract_not_accepted``），main 完全
不知道，最后是三个任务被取消、再建三个。

这里做三件事，都在**拒绝自己的那个独立事务**里（命令的事务已经回滚）：

① 把原因写进任务可见的 ``block_reason``（``refused:<code>``）—— 已经有别人给的更具体理由时
   **不覆盖**（``start_blocked:`` / ``needs_input`` 都比这句话有用）；
② 给 main 发**一条** ``task.refused`` 消息（唤醒白名单里的种类：只有 main 能修"契约没结清 /
   计划写错了"这类事）。只在**第一次**越过阈值时发：再往后每一次都发就变成噪音，而计数仍在
   事件里，main 每回合的拒绝清单也照旧看得到；
③ 返回一份机械事实，由 HTTP 层一起写进那条拒绝事件（``escalation`` 一栏），以及一条
   ``coordination.refusal_repeat`` 事件（经 ``state_runtime.persist``：任务改动有实体变更行、
   消息按白名单排 host_wake）。

判据只有一条：**带 ``task_id`` 的拒绝**，同一个任务、同一个 ``code``，在最近
``DENIAL_EVENT_WINDOW`` 条拒绝里出现到 ``DENIAL_REPEAT_THRESHOLD`` 次。没有任务可归因的拒绝
（例如 ``root_binding_required``）不属于这份职责 —— 那正是"谁老是被拒"清单的边界。
"""

from __future__ import annotations

from typing import Any

from tsunagou.application.handlers import DENIAL_EVENT_WINDOW, DENIAL_REPEAT_THRESHOLD

#: 消息种类。不在 ``WAKE_WORTHY_KINDS`` 里就不会排 host_wake：这条消息的全部意义就是让 main
#: 动起来，所以它必须在白名单里（见 ``modules/messaging.py``）。
REFUSAL_MESSAGE_KIND = "task.refused"
#: 写进 ``block_reason`` 的前缀。带上它才能安全地"只覆盖自己写的那句"。
REFUSAL_NOTE_PREFIX = "refused:"
#: 任务已经到终态就不必回响了：没有下一步可做（``superseded`` 要看的是它的替代者）。
CLOSED_TASK_STATUSES = frozenset({"completed", "cancelled", "superseded"})
#: 这些码说的是**调用方**，不是任务：任务本身可能完全正常，只是叫错了人 / 少了能力 / 传错了字段。
#: 它们照旧进审计与 main 的拒绝清单（那是"谁老是被拒"），但不往任务上盖章、也不叫 main ——
#: 否则一条健康的任务会因为某个人没开工就被标成"开不了工"。2026-10-08 实测的
#: ``task__progress ← capability_denied``（没 begin 就想 progress）正是这一类。
CALLER_SIDE_CODES = frozenset({
    "capability_denied", "principal_kind_denied", "user_only", "attempt_owner_required",
    "inbox_access_denied", "wake_message_access_denied", "participant_slot_denied",
    "unknown_payload_field", "workspace_selection_requires_stopped_task",
    "task_scope_denied", "attempt_scope_denied", "workspace_scope_denied",
    "workspace_task_scope_denied", "wake_message_required",
})
#: 审计事件名。它由运行层写（没有对应的命令），控制台的命令名表里有一条中文。
REFUSAL_EVENT_KIND = "coordination.refusal_repeat"


class RefusalEscalation:
    """Repeated refusals become a visible task note plus one message to main."""

    def __init__(
        self, *, database: Any, tasks: Any, messages: Any, authority: Any, state_runtime: Any,
        window: int = DENIAL_EVENT_WINDOW, threshold: int = DENIAL_REPEAT_THRESHOLD,
    ) -> None:
        self.database = database
        self.tasks = tasks
        self.messages = messages
        self.authority = authority
        self.state_runtime = state_runtime
        self.window = window
        self.threshold = threshold

    def __call__(self, uow: Any, command_kind: str, detail: dict[str, Any]) -> dict[str, Any] | None:
        """Record the repeat and, at the threshold, tell main. Never raises."""

        task_id = str(detail.get("task_id") or "").strip()
        code = str(detail.get("code") or "").strip()
        if not task_id or not code or code in CALLER_SIDE_CODES:
            return None
        task = self.tasks.tasks.get(task_id)
        if task is None or task.status in CLOSED_TASK_STATUSES:
            return None
        count = self._previous_refusals(task_id, code) + 1
        if count < self.threshold:
            return None
        before = self.state_runtime.capture() if self.state_runtime is not None else None
        marked = self._mark(task, code, count)
        notified = self._notify(task, code, count, command_kind, detail) if count == self.threshold else None
        if self.state_runtime is not None:
            self.state_runtime.persist(
                uow, actor_ref="runtime", command_kind=REFUSAL_EVENT_KIND,
                before=before,
                command_payload={"task_id": task_id, "code": code,
                                 "command_kind": command_kind, "refusal_count": count},
                result={"refusal_count": count, "task_status": task.status,
                        "notified_agent_id": notified},
            )
        return {"refusal_count": count, "code": code, "task_marked": marked,
                "notified_agent_id": notified,
                "notified": ("main was told once, when this first crossed the threshold"
                             if count > self.threshold else notified is not None)}

    def _previous_refusals(self, task_id: str, code: str) -> int:
        """How many refusals of this task with this code are already on the record.

        The current refusal's own event is written *after* this call (same transaction), so it
        must not be counted twice — ``list_events`` reads committed rows only.
        """

        if self.database is None:
            return 0
        try:
            events = self.database.list_events(limit=self.window + 4, event_type_like="%.denied")
        except Exception:
            # The ledger is help, not an invariant: never fail a refusal over it.
            return 0
        count = 0
        for event in events[-self.window:]:
            payload = event.get("payload")
            if not isinstance(payload, dict):
                continue
            if str(payload.get("task_id") or "").strip() != task_id:
                continue
            if str(payload.get("code") or "").strip() != code:
                continue
            count += 1
        return count

    def _mark(self, task: Any, code: str, count: int) -> bool:
        note = f"{REFUSAL_NOTE_PREFIX}{code}" + (f"x{count}" if count > self.threshold else "")
        existing = getattr(task, "block_reason", None)
        if existing is not None and not str(existing).startswith(REFUSAL_NOTE_PREFIX):
            # Someone already wrote a more specific reason (``start_blocked:``/``needs_input``).
            # Keep it: this marker is a reminder, not the authoritative explanation.
            return False
        task.block_reason = note
        return True

    def _notify(self, task: Any, code: str, count: int, command_kind: str,
                detail: dict[str, Any]) -> str | None:
        main_agent_id = getattr(self.authority, "main_agent_id", None)
        if not isinstance(main_agent_id, str) or not main_agent_id:
            return None
        summary = (
            f"任务「{task.title}」已 {count} 次开不了工：{code}（最近一次是 {command_kind}）。"
            "拒绝不改变任何状态 —— 照现在这样再试只会再被拒一次；要么按 code 去修"
            "（契约先结清 / 依赖先完成 / 范围先定），要么换一条路（supersedes_task_id 重建）。"
        )
        payload: dict[str, Any] = {
            "task_id": task.task_id, "code": code, "count": count, "command_kind": command_kind,
            "task_status": task.status, "attempted": detail.get("attempted"),
        }
        for key in ("next", "reason", "status", "existing_contract_ids", "proposal_id"):
            value = detail.get(key)
            if value is not None:
                payload[key] = value
        self.messages.send(
            command_id=f"refusal:{task.task_id}:{code}:{count}",
            sender_agent_id="runtime", recipient_agent_id=main_agent_id,
            kind=REFUSAL_MESSAGE_KIND, subject_ref=f"task/{task.task_id}",
            summary=summary, payload=payload,
        )
        return main_agent_id
