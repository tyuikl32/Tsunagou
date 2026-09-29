"""消息那一栏的「状态」是**派生**的，而且由后端派生。

消息本身没有 status 字段（`modules/messaging.py`）：它有一条投递记录，以及"发件方要了答复"
时才有的回应义务。页面上那一列要的是短中文（已答复 / 等待中 / 无需答复），而"没有义务"
与"还等着"是两件不同的事 —— 所以判决在出口里下，页面读 `status` 与 `obligations` 就够了，
不用从空数组里猜。
"""

from __future__ import annotations

from tests.unit.test_trace_audit import Runtime
from tests.unit.test_trace_audit import runtime as runtime  # noqa: F401  (夹具按名字取用)

from tsunagou.bootstrap.container import message_status


def _messages(runtime: Runtime) -> list[dict[str, object]]:
    endpoint = runtime.endpoint("/api/v1/projects/{project_id}/messages")
    return endpoint(runtime.project_id)["items"]


def test_the_verdict_is_a_function_of_the_obligation_rows() -> None:
    assert message_status([]) == "none"
    assert message_status([{"status": "open"}]) == "pending"
    assert message_status([{"status": "responded"}]) == "answered"
    # 豁免 / 作废同样是"不再欠答复"，不能算成还在等。
    assert message_status([{"status": "waived"}]) == "answered"
    assert message_status([{"status": "superseded"}]) == "answered"
    # 一条已闭、一条还开着：按最保守的那个说。
    assert message_status([{"status": "responded"}, {"status": "open"}]) == "pending"


def test_a_notice_owes_nothing_and_a_request_waits(runtime: Runtime) -> None:
    main, _ = runtime.enroll("main")
    worker, _ = runtime.enroll("worker")
    runtime.call(
        "message.send",
        {"recipient_agent_id": worker["agent_id"], "summary": "通知：无需回复"},
        main,
    )
    request = runtime.call(
        "message.send",
        {"recipient_agent_id": worker["agent_id"], "summary": "请给出字段草案",
         "response_contract": {"required": True}},
        main,
    )

    by_id = {str(item["message_id"]): item for item in _messages(runtime)}

    assert by_id[request["message_id"]]["status"] == "pending"
    obligations = by_id[request["message_id"]]["obligations"]
    assert [row["status"] for row in obligations] == ["open"]
    assert obligations[0]["obligation_id"]
    notice = next(item for item in by_id.values() if item["summary"] == "通知：无需回复")
    assert notice["status"] == "none"
    assert notice["obligations"] == []


def test_answering_the_obligation_turns_the_message_answered(runtime: Runtime) -> None:
    main, _ = runtime.enroll("main")
    worker, _ = runtime.enroll("worker")
    request = runtime.call(
        "message.send",
        {"recipient_agent_id": worker["agent_id"], "summary": "请给出字段草案",
         "response_contract": {"required": True}},
        main,
    )
    sent = next(item for item in _messages(runtime) if item["message_id"] == request["message_id"])
    obligation_id = sent["obligations"][0]["obligation_id"]
    reply = runtime.call(
        "message.send",
        {"recipient_agent_id": main["agent_id"], "summary": "草案在这里",
         "in_reply_to": request["message_id"]},
        worker,
    )

    runtime.call(
        "message.respond",
        {"obligation_id": obligation_id, "response_message_id": reply["message_id"]},
        worker,
    )

    answered = next(item for item in _messages(runtime) if item["message_id"] == request["message_id"])
    assert answered["status"] == "answered"
    assert [row["status"] for row in answered["obligations"]] == ["responded"]
