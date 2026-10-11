"""2026-10-10 实测之后的读路径与摩擦修复。

主 Agent 的清单里，最贵的两条是"结果里不带证据"和"读取放大"：验收只能人肉重建，想知道一条任务
的现状就得读整个项目。这里钉住补上的那条路 —— 读单条任务、读一次交付的可重放证据、越界改动随
结果一起给出 —— 以及三个小摩擦：``publish`` 隐含 ``ready``、``request_changes`` 之后一次
``publish`` 就能重新领取、普通消息可以**显式**要求唤醒。
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.integration.test_state_integrity import runtime as _runtime_fixture


@pytest.fixture(name="runtime")
def evidence_runtime(tmp_path, monkeypatch):
    yield from _runtime_fixture.__wrapped__(tmp_path, monkeypatch)


def _file_task(app: Any, call: Any, main: dict[str, Any], *, segments: list[str], worker: dict[str, Any]) -> dict[str, Any]:
    """一条声明了路径范围的文件任务：登记根、建任务、选工作区、发布、开工。"""

    fixture = app.state.state_runtime.project_registry.repository
    call("root.register", {"name": "coordination", "kind": "directory", "required": False,
                           "binding_request": {"absolute_path": str(fixture)}}, main)
    (root_id,) = list(app.state.project_registry.project.roots)
    created = call("task.create", {
        "title": "evidence", "objective": "写一个文件",
        "execution_scope": {"resources": [{"kind": "path", "root_id": root_id,
                                           "segments": segments, "mode": "exclusive_write"}]},
    }, main)
    call("workspace.select", {"task_id": created["task_id"], "driver_kind": "shared"}, main)
    call("task.ready", {"task_id": created["task_id"]}, main)
    task = call("task.publish", {"task_id": created["task_id"]}, main)
    started = call("task.begin", {"task_id": task["task_id"],
                                  "expected_task_revision": task["revision"]}, worker)
    return {"task_id": task["task_id"], "attempt_id": started["attempt_id"]}


def test_task_get_answers_one_task_without_reading_the_whole_project(runtime) -> None:
    """读单条任务：不用为了一个 revision 去读全部 assignment。"""

    app, call, main, worker = runtime
    prepared = _file_task(app, call, main, segments=["demo.txt"], worker=worker)

    view = call("task.get", {"task_id": prepared["task_id"]}, main)
    assert view["status"] == "running" and view["attempt"]["owner_agent_id"] == worker["agent_id"]
    assert view["attempt"]["status"] == "running"
    assert view["execution_scope"]["resources"][0]["segments"] == ["demo.txt"]
    assert view["required_contract_ids"] == []
    assert "next" in view and view["next"]
    assert view["latest_result"] is None

    refused = pytest.raises(Exception)
    with refused as caught:
        call("task.get", {"task_id": "nope"}, main)
    assert "task_not_found" in str(caught.value)


def test_task_result_get_returns_the_replayable_evidence(runtime) -> None:
    """验收方读一次交付的证据，而不是自己写探针重建（2026-10-10 最大单项成本）。"""

    app, call, main, worker = runtime
    prepared = _file_task(app, call, main, segments=["demo.txt"], worker=worker)
    (app.state.project_registry.repository / "demo.txt").write_text("hello\n", encoding="utf-8")
    submitted = call("task.submit", {
        "task_id": prepared["task_id"], "attempt_id": prepared["attempt_id"], "summary": "done",
        "validation_metadata": [
            {"command": "python -m pytest -q", "exit_code": 0},
            {"command": "python -m ruff check", "exit_code": 0,
             "started_at": "2026-10-10T10:00:00Z", "finished_at": "2026-10-10T10:00:03Z",
             "tool": "ruff", "tool_version": "0.6", "workspace_digest": "sha256:" + "a" * 64},
        ],
    }, worker)

    evidence = call("task.result.get", {"task_id": prepared["task_id"],
                                        "result_id": submitted["result_id"]}, main)
    assert evidence["result_digest"] == submitted["digest"]
    manifest = evidence["workspace_result"]
    assert manifest["manifest_id"]
    assert [item["command"] for item in manifest["validation_metadata"]] == [
        "python -m pytest -q", "python -m ruff check",
    ]
    assert "demo.txt" in manifest["changed_paths"]
    assert manifest["scope_paths"] == ["demo.txt"] and manifest["scope_violations"] == []
    assert manifest["environment_digest"], "环境指纹要在证据里（#5：依赖被动过要看得见）"
    assert manifest["evidence_level"] == "system_verified"

    # 缺省取最近一次：不传 result_id 也拿得到同一份。
    latest = call("task.result.get", {"task_id": prepared["task_id"]}, main)
    assert latest["result_id"] == submitted["result_id"]


def test_a_change_outside_the_declared_scope_is_reported_with_the_result(runtime) -> None:
    """声明范围之外的改动随结果一起给出（#8：此前只能靠 git status 自己发现）。"""

    app, call, main, worker = runtime
    prepared = _file_task(app, call, main, segments=["demo.txt"], worker=worker)
    repository = app.state.project_registry.repository
    (repository / "demo.txt").write_text("hello\n", encoding="utf-8")
    (repository / "outside.txt").write_text("sneaky\n", encoding="utf-8")
    call("task.submit", {
        "task_id": prepared["task_id"], "attempt_id": prepared["attempt_id"], "summary": "done",
    }, worker)

    evidence = call("task.result.get", {"task_id": prepared["task_id"]}, main)["workspace_result"]
    assert evidence["scope_violations"] == ["outside.txt"]
    # 通知里也带着它：验收方读一条消息就知道有越界，不必先去看证据全文。
    inbox = call("inbox.claim", {"limit": 20}, main)
    (notice,) = [item for item in inbox["messages"] if item["kind"] == "task.submitted"]
    summary = call("inbox.fetch", {"message_id": notice["message_id"]}, main)["payload"]["evidence"]
    assert summary["scope_violations"] == ["outside.txt"]


def test_publish_implies_ready_and_reopens_a_changes_requested_task(runtime) -> None:
    """一个意图一次调用（#7）：publish 隐含 ready；退回之后一次 publish 就能重新领取。"""

    app, call, main, worker = runtime
    created = call("task.create", {"title": "one call", "objective": "写一段", "execution_scope": {}}, main)
    published = call("task.publish", {"task_id": created["task_id"]}, main)
    assert published["status"] == "open", "draft 任务直接 publish 就该进领取队列"

    begun = call("task.begin", {"task_id": created["task_id"],
                                "expected_task_revision": published["revision"]}, worker)
    submitted = call("task.submit", {"task_id": created["task_id"],
                                     "attempt_id": begun["attempt_id"], "summary": "done"}, worker)
    call("task.review.request_changes", {
        "task_id": created["task_id"], "result_id": submitted["result_id"],
        "result_digest": submitted["digest"], "reason": "再改一版",
    }, main)
    reopened = call("task.publish", {"task_id": created["task_id"]}, main)
    assert reopened["status"] == "open", "退回之后一次 publish 就该重新可领"


def test_a_plain_message_can_be_sent_with_an_explicit_wake(runtime) -> None:
    """普通消息也能**显式**要求唤醒（#4）：不必把它升级成任务事件。"""

    app, call, main, worker = runtime
    sent = call("message.send", {
        "recipient_agent_id": worker["agent_id"], "summary": "口径澄清：请按 D1 规避",
        "wake": True,
    }, main)
    assert sent["wake_requested"] is True
    assert "wake=true" in sent["next"]
    with app.state.project_database._connect() as conn:
        (row,) = conn.execute("SELECT target_ref FROM outbox WHERE kind='host_wake'").fetchall()
    assert row[0] == "message/" + sent["message_id"]

    # 不带 wake 时照旧惰性，并且提示告诉我们**下次**该怎么发。
    plain = call("message.send", {"recipient_agent_id": worker["agent_id"], "summary": "只是记一笔"}, main)
    assert plain["wake_requested"] is False
    assert "下次" in plain["next"]


def test_inbox_claim_can_skip_what_was_already_read_and_ack_is_forgiving(runtime) -> None:
    """#10：读过的可以过滤掉；ACK 幂等且不因为副本漂移而失败。"""

    app, call, main, worker = runtime
    sent = call("message.send", {"recipient_agent_id": worker["agent_id"], "summary": "一件事"}, main)
    first = call("inbox.claim", {"limit": 20}, worker)
    assert [item["message_id"] for item in first["messages"]] == [sent["message_id"]]
    call("inbox.presented", {"message_id": sent["message_id"], "evidence_digest": "sha256:" + "b" * 64}, worker)

    # 租约是 30 秒（claim 会租下它）；这里把租约推到期，模拟"过了一会再看"。
    delivery = app.state.state_runtime.messages.deliveries[sent["message_id"]]
    delivery.lease_until = 0
    # 已经展示过的：unread 过滤掉它，不带 unread 时仍然看得到（默认行为没变）。
    assert call("inbox.claim", {"limit": 20, "unread": True}, worker)["messages"] == []
    assert [item["message_id"] for item in call("inbox.claim", {"limit": 20}, worker)["messages"]] == [
        sent["message_id"],
    ]

    call("inbox.ack", {"message_id": sent["message_id"]}, worker)
    again = call("inbox.ack", {"message_id": sent["message_id"]}, worker)
    assert again["acked"] is True, "重复 ACK 是幂等的，不该要求重新 claim"

    # 一批可以一次确认（实测一批消息原来是 claim→fetch→presented→ack 四次往返）。
    second = call("message.send", {"recipient_agent_id": worker["agent_id"], "summary": "第二件"}, main)
    third = call("message.send", {"recipient_agent_id": worker["agent_id"], "summary": "第三件"}, main)
    batch = call("inbox.ack", {"message_ids": [second["message_id"], third["message_id"]]}, worker)
    assert batch["acked"] is True and batch["count"] == 2
    assert call("inbox.claim", {"limit": 20, "unread": True}, worker)["messages"] == [], "两条都确认掉了"

    # 摘要里也能直接拿到 payload（省掉"先 claim 再逐条 fetch"）：task.submitted 的 result_digest
    # 就在 payload 里，而验收要的正是它。
    call("message.send", {"recipient_agent_id": worker["agent_id"], "summary": "带 payload",
                          "payload": {"result_digest": "sha256:" + "c" * 64}}, main)
    with_payload = call("inbox.claim", {"limit": 5, "with_payload": True}, worker)
    assert with_payload["with_payload"] is True
    assert any((item.get("payload") or {}).get("result_digest") for item in with_payload["messages"]), \
        "with_payload 必须真的把 payload 带上来"

    # 副本漂移（投递行带着旧 agent_id）时以**消息**为准：属于你的消息仍能确认。
    state = app.state.state_runtime
    state.messages.deliveries[sent["message_id"]].recipient_agent_id = "someone-else"
    assert call("inbox.ack", {"message_id": sent["message_id"]}, worker)["acked"] is True
    # 但别人的消息依旧拒绝。
    other = call("message.send", {"recipient_agent_id": main["agent_id"], "summary": "给 main"}, worker)
    with pytest.raises(Exception) as caught:
        call("inbox.ack", {"message_id": other["message_id"]}, worker)
    assert "inbox_access_denied" in str(caught.value)
