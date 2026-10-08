"""``contract_id`` 在真 daemon 上端到端成立：提案、发布、被引用、开工。

2026-10-08 实测的那条断链（main 给契约起了名字、把名字填进 ``required_contract_ids``、
``task.begin`` 被拒 4 次）在这里被钉成三件事：给了 `contract_id` 它就是这个提案的 id、
任务引用它就能开工；库里没有的 id 被拒时当场列出**现有**的契约 id；重名当场拒绝，
不会悄悄换一个 id 让人继续引用错的那个。
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from tests.integration.test_execution_begin import begin, published
from tests.integration.test_state_integrity import runtime as _runtime_fixture


@pytest.fixture(name="runtime")
def contract_runtime(tmp_path, monkeypatch):
    yield from _runtime_fixture.__wrapped__(tmp_path, monkeypatch)


def _propose(call, main, worker, **extra):
    return call("contract.propose", {
        "contract_kind": "interface", "payload": {"decision": "shared"},
        "participants_required": [{"slot": "implementation", "agent_id": worker["agent_id"]}],
        **extra,
    }, main)


def test_a_task_can_begin_on_a_caller_supplied_contract_id(runtime):
    app, call, main, worker = runtime
    proposed = _propose(call, main, worker, contract_id="library-api-v1")

    assert proposed["proposal_id"] == proposed["contract_id"] == "library-api-v1"
    assert "library-api-v1" in app.state.state_runtime.cognition.proposals

    task = published(call, main, required_contract_ids=["library-api-v1"])
    with pytest.raises(HTTPException) as refused:
        begin(call, task, worker)
    assert refused.value.detail["code"] == "required_contract_not_accepted:library-api-v1"

    call("contract.accept", {
        "proposal_id": "library-api-v1", "participant_slot": "implementation",
        "proposal_digest": proposed["digest"],
    }, worker)
    assert begin(call, task, worker)["status"] == "running"


def test_the_refusal_hands_back_the_contract_ids_that_exist(runtime):
    """填了一个库里没有的 id（实测里填的是自己起的标签）时，拒绝要当场给出能照抄的清单。"""

    app, call, main, worker = runtime
    _propose(call, main, worker, contract_id="library-api-v1")
    task = published(call, main, required_contract_ids=["library-api-v1-typo"])

    with pytest.raises(HTTPException) as refused:
        begin(call, task, worker)

    detail = refused.value.detail
    assert detail["task_id"] == task["task_id"], "拒绝要能归到具体任务上"
    assert detail["status"] == "missing"
    assert detail["existing_contract_ids"] == ["library-api-v1"]
    assert "library-api-v1" in detail["next"]


def test_a_contract_that_exists_but_is_not_accepted_says_which_state_it_is_in(runtime):
    """与"根本不存在"分开报：存在但没被接受，修法是去接受槽位，不是改 id。"""

    app, call, main, worker = runtime
    _propose(call, main, worker, contract_id="library-api-v1")
    task = published(call, main, required_contract_ids=["library-api-v1"])

    with pytest.raises(HTTPException) as refused:
        begin(call, task, worker)

    detail = refused.value.detail
    assert detail["status"] == "proposed"
    assert "existing_contract_ids" not in detail, "存在时不必列清单：id 本身就对"
    assert "接受" in detail["next"]


def test_a_second_contract_cannot_take_a_live_id(runtime):
    app, call, main, worker = runtime
    _propose(call, main, worker, contract_id="library-api-v1")

    with pytest.raises(HTTPException) as refused:
        _propose(call, main, worker, contract_id="library-api-v1")

    assert refused.value.detail["code"] == "contract_id_taken"
    assert len(app.state.state_runtime.cognition.proposals) == 1
