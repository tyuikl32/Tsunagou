""""有人停下来"必须有人知道 —— 2026-10-10 审计里那类"静默"的回归测试。

三个具体事实：

1. ``task.block`` 之后 main 一定**收得到一条会唤醒它的消息**。以前它只改状态、谁也不通知，
   而 ``blocked`` 又不在看门狗候选里（那是"它主动停下来"的诚实表达）⇒ 一个 Agent 明确说
   "我卡住了"却没有任何人接手。实测那轮结束时 main 手上还留着 6 条未读。
2. ``task.review.request_changes`` 之后 main 也被通知，并且 ``next`` 说的话是对的
   （**一次** ``task.publish`` 就够；发布本身是静默的）。以前它只说"先 ready 再 publish"，
   还把"这条通知会唤醒对方"当成解决方案 —— 而对方醒来后什么也做不了。
3. worker 在 ``task.begin`` 撞版本冲突时，这次拒绝要进 main 的拒绝账本。以前 ``RevisionConflict``
   只回 409，不落 ``command.<kind>.denied``，于是"有人在 begin 撞版本"这件事永远看不见。
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException
from tests.integration.test_state_integrity import runtime as _runtime_fixture


@pytest.fixture(name="runtime")
def visibility_runtime(tmp_path, monkeypatch):
    yield from _runtime_fixture.__wrapped__(tmp_path, monkeypatch)


def _worker_task(app: Any, call: Any, main: dict[str, Any], worker: dict[str, Any]) -> dict[str, Any]:
    created = call("task.create", {"title": "一件事", "objective": "做完", "execution_scope": {}}, main)
    call("task.update_plan", {"task_id": created["task_id"], "acceptance": "跑得起来"}, main)
    published = call("task.publish", {"task_id": created["task_id"]}, main)
    begun = call("task.begin", {"task_id": created["task_id"],
                                "expected_task_revision": published["revision"]}, worker)
    return {"task_id": created["task_id"], "attempt_id": begun["attempt_id"], "revision": published["revision"]}


def test_a_blocked_task_sends_main_a_wake_worthy_message(runtime) -> None:
    app, call, main, worker = runtime
    task = _worker_task(app, call, main, worker)

    blocked = call("task.block", {"task_id": task["task_id"], "attempt_id": task["attempt_id"],
                                  "reason_code": "waiting_for_api_key"}, worker)

    assert blocked["status"] == "blocked"
    assert "main" in blocked["next"], "调用方要被告知球在谁那边"
    messages = call("inbox.claim", {"limit": 20, "with_payload": True}, main)["messages"]
    (notice,) = [item for item in messages if item["kind"] == "task.blocked"]
    assert notice["subject_ref"] == "task/" + task["task_id"]
    assert "waiting_for_api_key" in notice["summary"], "原因要写在摘要里，而不是让 main 去查"
    with app.state.project_database._connect() as conn:
        (row,) = conn.execute(
            "SELECT 1 FROM outbox o JOIN events e ON o.project_id=e.project_id AND o.event_seq=e.event_seq "
            "WHERE o.kind='host_wake' AND o.target_ref=?", ("message/" + notice["message_id"],),
        ).fetchone()
    assert row == 1, "这条消息要进自动唤醒通道，否则 main 也不会被叫起来"


def test_a_rework_tells_main_and_says_the_right_next_step(runtime) -> None:
    app, call, main, worker = runtime
    task = _worker_task(app, call, main, worker)
    submitted = call("task.submit", {"task_id": task["task_id"], "attempt_id": task["attempt_id"],
                                     "summary": "done"}, worker)

    outcome = call("task.review.request_changes", {
        "task_id": task["task_id"], "result_id": submitted["result_id"],
        "result_digest": submitted["digest"], "reason": "再改一版",
    }, main)

    assert "先 task.ready" not in outcome["next"], "一次 publish 就够，不该再教两段式"
    assert "一次" in outcome["next"] and "静默" in outcome["next"]
    # main 自己就是评审：它刚刚做了这件事，不该再收到一条"有人退回了"的消息（那是噪音）。
    # 需要留言的是**别的**评审者退回的场合 —— 那条路在下面这个分支里。
    messages = call("inbox.claim", {"limit": 20, "with_payload": True}, main)["messages"]
    back_to_main = [item for item in messages
                    if item["kind"] == "task.reviewed"
                    and (item.get("payload") or {}).get("decision") == "changes_requested"]
    assert not back_to_main, "评审者自己就是 main 时不重复通知"


def test_a_revision_conflict_at_begin_lands_in_the_denial_ledger(runtime) -> None:
    app, call, main, worker = runtime
    task = _worker_task(app, call, main, worker)

    with pytest.raises(HTTPException) as refused:
        call("task.begin", {"task_id": task["task_id"],
                            "expected_task_revision": task["revision"] + 99}, worker)
    assert "task_revision_conflict" in str(refused.value.detail)

    with app.state.project_database._connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='command.task.begin.denied'",
        ).fetchone()[0]
    assert count == 1, "撞版本也要落拒绝事件，否则 main 的账本里永远看不到它"
    (view,) = [item for item in [call("context.project_read", {}, main)]]
    assert view["coordination"]["denied"], "拒绝要出现在 main 每回合读的那份清单里"
