"""拒绝账本必须给**最新**的拒绝，而不是最旧的一批（2026-10-10 审计发现的真库缺陷）。

原来的实现写的是"``list_events`` 是升序；多读几条再取尾部就是最新的"—— 但那条查询是
``ORDER BY event_seq ASC LIMIT n``：拒绝超过 n 条之后，返回的是最旧的那批，取尾部取到的还是
最旧的。于是 main 每回合读到的是一块**冻结的旧证据**，而它下面那句"同一个 code 拒到第二次
就要停下"恰恰指向它现在看不见的那个阻塞。

既有单测没抓到它，因为那里的 store 是个**不看排序**的替身（返回全部、由调用方切片）。所以
这一条用真库写：造 70 条拒绝，确认第 70 条出现、且顺序是从新到旧。
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.integration.test_state_integrity import runtime as _runtime_fixture


@pytest.fixture(name="runtime")
def denial_runtime(tmp_path, monkeypatch):
    yield from _runtime_fixture.__wrapped__(tmp_path, monkeypatch)


def _append_denial(app: Any, index: int) -> None:
    database = app.state.project_database
    state = app.state.state_runtime
    with database.transaction("test-denials") as uow:
        uow.append_event(
            lineage_id=state.lineage_id, event_type="command.task.begin.denied",
            aggregate_ref=f"task/task-{index:02d}", actor_ref="worker",
            payload={"command_kind": "task.begin", "code": "task_revision_conflict",
                     "task_id": f"task-{index:02d}", "detail": {"code": "task_revision_conflict"}},
            subject_ref=f"task/task-{index:02d}", reason_code="task_revision_conflict",
        )


def test_the_denial_ledger_answers_with_the_newest_refusals(runtime) -> None:
    app, call, main, worker = runtime
    for index in range(70):
        _append_denial(app, index)

    view = call("context.project_read", {}, main)
    denied = view["coordination"]["denied"]

    assert denied, "有拒绝就该有条目"
    task_ids = [row["task_id"] for row in denied]
    assert "task-69" in task_ids, "最新的一条必须在里面（旧实现只给最旧的 54 条）"
    assert task_ids[0] == "task-69", "最新的一次排在最前"
    assert len(task_ids) == len(set(task_ids)), "同一任务只聚合成一条"
