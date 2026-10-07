"""领活被契约门拒绝时，要说清**是哪个契约、什么状态、下一步谁去做什么**。

2026-10-07 实测：W1/W2 领活时撞上 `required_contract_not_accepted:<id>`，只拿到一个契约 id ——
不知道契约现在是什么状态、缺哪个槽、该谁去接受，于是只能升级去问 main（那一轮因此多出
31 条消息、17 次领取的协商成本）。这里把"指名"钉住。
"""

from __future__ import annotations

from typing import Any

from tsunagou.application.workflows.task_execution import (
    contract_refusal_detail,
    self_referential_contract_note,
)


def test_the_refusal_says_which_contract_and_what_to_do_next() -> None:
    detail = contract_refusal_detail("3a59b7e6-0000-0000-0000-000000000000", "proposed")

    assert detail["proposal_id"] == "3a59b7e6-0000-0000-0000-000000000000"
    assert detail["status"] == "proposed", "契约当前状态必须写出来"
    assert detail["next"], "要有下一步：谁去接受、或去哪看还差谁"
    assert "proposed" in detail["next"] or "接受" in detail["next"]


def test_a_missing_contract_is_told_apart_from_an_unaccepted_one() -> None:
    """"这个契约根本不存在"与"存在但还没被接受"是两回事，两句话不能一样。"""

    missing: dict[str, Any] = contract_refusal_detail("gone", None)
    unaccepted = contract_refusal_detail("there", "proposed")

    assert missing["status"] == "missing"
    assert missing["next"] != unaccepted["next"]


def test_a_contract_whose_slot_belongs_to_the_assignee_is_flagged() -> None:
    """自指形状要在**下达计划那一刻**就说出来。

    2026-10-07 实测：任务要求的契约，参与者槽正好是**这个任务的执行者** —— 它领活时会等契约变成
    accepted，而契约要等它自己先接受槽位。没人说出来，那一步就变成了 31 条消息的协商。
    不是拒绝（main 可以用 contract.accept_proxy 兜 ✓），而是当场提示"先让它接受槽位"。
    """

    participants = [
        {"slot": "owner", "agent_id": "main-1", "required": True},
        {"slot": "verify", "agent_id": "w-3", "required": True},
    ]

    note = self_referential_contract_note("c-1", participants, "w-3", "WS-TESTS")

    assert note, "槽位归执行者自己时必须给出一句提示"
    assert "verify" in note and "w-3" in note and "WS-TESTS" in note
    assert "accept_proxy" in note or "接受" in note, "要说清怎么办"


def test_a_contract_whose_slots_belong_to_others_is_not_flagged() -> None:
    participants = [{"slot": "owner", "agent_id": "main-1", "required": True}]

    assert self_referential_contract_note("c-1", participants, "w-3", "WS-TESTS") is None
