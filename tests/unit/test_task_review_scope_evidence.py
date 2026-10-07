"""接受结果时要看工作区产物 —— 用户 2026-10-07 定的口径。

"没有租约等，提交任务时不承认 agent 的改动"这句话，落到能机械判定的那一半是：
**任务声明了改动范围（非空 execution_scope），结果里却没有任何工作区产物** ——
那就不能接受，因为没有东西证明改了什么、基于哪个基线。

空 scope 的任务**拦不住**（系统无从知道它本该改文件），那是发布时要提醒的事
（见 handlers.EMPTY_SCOPE_NEXT）；这里只管可判定的那一半。
"""

from __future__ import annotations

from typing import Any

import pytest

from tsunagou.modules.authority import AuthorityService
from tsunagou.modules.tasks import TaskService
from tsunagou.shared_kernel.baseline import BASELINE_CAPABILITIES

SCOPE: dict[str, Any] = {"resources": [
    {"kind": "path", "root_id": "r", "segments": ["a"], "mode": "exclusive_write"}]}


def _baseline() -> dict[str, Any]:
    return {"baseline": {name: {"status": "supported", "evidence_refs": [f"fixture:{name}"]}
                         for name in BASELINE_CAPABILITIES}}


def _submitted(scope: dict[str, Any], payload: dict[str, Any]) -> tuple[TaskService, Any, Any, Any]:
    authority = AuthorityService(None)
    main = authority.redeem_ticket(
        authority.issue_ticket("m", "mc"), "m", "mc", baseline=_baseline())
    worker = authority.redeem_ticket(
        authority.issue_ticket("w", "wc"), "w", "wc", baseline=_baseline())
    authority.appoint_main(actor_kind="user_control", agent_id=main.agent_id)
    tasks = TaskService()
    task = tasks.create_task("t", "o", execution_scope=scope)
    tasks.ready(task.task_id)
    tasks.publish(task.task_id)
    attempt = tasks.claim(task.task_id, worker.agent_id)
    preflight = tasks.preflight(task.task_id, worker.agent_id, attempt_id=attempt.attempt_id)
    tasks.start(task.task_id, worker.agent_id, preflight_id=preflight.preflight_id,
                require_preflight=True)
    result = tasks.submit(task.task_id, worker.agent_id, payload)
    return tasks, main, task, result


def test_accept_refuses_a_scoped_task_whose_result_has_no_workspace_evidence() -> None:
    tasks, main, task, result = _submitted(SCOPE, {"summary": "done"})

    with pytest.raises(Exception, match="workspace_evidence_required"):
        tasks.review(task.task_id, main.agent_id, result.result_id, decision="accepted")


def test_accept_still_works_when_the_result_names_a_workspace_result() -> None:
    tasks, main, task, result = _submitted(
        SCOPE, {"summary": "done", "workspace_result_ref": "wsr-1"})

    review = tasks.review(task.task_id, main.agent_id, result.result_id, decision="accepted")

    assert review.decision == "accepted"


def test_accept_is_unchanged_for_a_task_that_claims_no_paths() -> None:
    """空 scope 的任务按"不做文件改动"处理（既有口径），这道门不该把它拦下。"""

    tasks, main, task, result = _submitted({}, {"summary": "no files"})

    review = tasks.review(task.task_id, main.agent_id, result.result_id, decision="accepted")

    assert review.decision == "accepted"


def test_requesting_changes_is_never_blocked_by_the_evidence_gate() -> None:
    tasks, main, task, result = _submitted(SCOPE, {"summary": "please fix"})

    review = tasks.review(task.task_id, main.agent_id, result.result_id,
                          decision="changes_requested", reason="no evidence")

    assert review.decision == "changes_requested"
