"""降级之后怎么"自己重新体检"。

会话降级后不能干活（业务命令要求 `status == "ready"`），可 `session.reconnect` 过去也
要求 ready —— 于是"修好"只剩一条路：找人重新发一张入席票。多出来的这条门
（`api/auth.py: authenticate_reconnect_refresh`）只做一件事：让一条**还握着当前凭据**
的降级会话，带着一份**新的能力报告**回来被重判一次。

三个不变量，这个文件就是钉它们的：

* 报告必须真的带来（空的 `probe_payload` 一律 401）——"我想被重判"不等于"我重判通过"；
* 判的人还是准入那条共享规则（`shared_kernel.baseline`），所以这条门自己升不了谁；
* 那一击在总路径上留下的是**当时**的现场：`session_status` + `missing_admission`。
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException
from tests.unit.test_trace_audit import Runtime
from tests.unit.test_trace_audit import runtime as runtime  # noqa: F401  (夹具按名字取用)

from tsunagou.shared_kernel.baseline import ADMISSION_CAPABILITIES

MISSING_ADMISSION = ("identity.continuity_evidence", "command.typed_tools")
PROVEN_ADMISSION = tuple(name for name in ADMISSION_CAPABILITIES if name not in MISSING_ADMISSION)


def _baseline(*names: str) -> dict[str, Any]:
    return {"baseline": {
        name: {"status": "supported", "evidence_refs": [f"fixture:{name}"]} for name in names
    }}


def _enroll(runtime: Runtime, conversation: str, baseline: dict[str, Any]) -> dict[str, Any]:
    identity = {
        "installation_id": conversation,
        "conversation_evidence": {"conversation_id": conversation},
    }
    ticket = runtime.call("agent.ticket.create.user", identity)["secret"]
    return runtime.call("agent.enroll", {**identity, "probe_payload": baseline}, ticket=ticket)


def _degraded(runtime: Runtime, conversation: str) -> dict[str, Any]:
    receipt = _enroll(runtime, conversation, _baseline(*PROVEN_ADMISSION))
    assert receipt["baseline_status"] == "degraded"
    assert receipt["missing_admission"] == sorted(MISSING_ADMISSION)
    return receipt


def _reconnect_payload(receipt: dict[str, Any], baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "reconnect_nonce": receipt["reconnect_nonce"],
        "expected_connection_epoch": receipt["connection_epoch"],
    }
    return {**payload, "probe_payload": baseline} if baseline is not None else payload


def test_a_degraded_session_comes_back_only_with_a_better_report(runtime: Runtime) -> None:
    receipt = _degraded(runtime, "worker")

    with pytest.raises(HTTPException) as closed:
        runtime.call("context.project_read", {}, receipt)
    assert closed.value.status_code == 401
    assert closed.value.detail == {"code": "authentication_failed"}

    # 同一份残缺报告不算"修好"：结论照旧，业务命令还是关着。
    unchanged = runtime.call("session.reconnect", _reconnect_payload(receipt, _baseline(*PROVEN_ADMISSION)), receipt)
    assert unchanged["baseline_status"] == "degraded"
    assert unchanged["missing_admission"] == sorted(MISSING_ADMISSION)
    with pytest.raises(HTTPException) as still_closed:
        runtime.call("context.project_read", {}, unchanged)
    assert still_closed.value.status_code == 401

    # 补上缺的准入项再回来：这一次才是 ready，而 ready 是**判**出来的不是自称的。
    healed = runtime.call("session.reconnect", _reconnect_payload(unchanged, _baseline(*ADMISSION_CAPABILITIES)), unchanged)
    assert healed["baseline_status"] == "ready"
    assert healed["missing_admission"] == []
    runtime.call("context.project_read", {}, healed)


def test_an_empty_reconnect_from_a_degraded_session_stays_shut(runtime: Runtime) -> None:
    """没有报告就不叫重判 —— 否则"我想回来"本身成了一张通行证。"""

    receipt = _degraded(runtime, "worker")

    for payload, credentials in (
        (_reconnect_payload(receipt), receipt),                              # 什么报告都不带
        (_reconnect_payload(receipt, {}), receipt),                          # 带了个空壳
        (_reconnect_payload(receipt, _baseline(*ADMISSION_CAPABILITIES)), {  # 报告没问题，代次过期
            **receipt, "connection_epoch": receipt["connection_epoch"] + 1,
        }),
        (_reconnect_payload(receipt, _baseline(*ADMISSION_CAPABILITIES)), {  # 报告没问题，凭据不对
            **receipt, "secret_token": "not-the-token",
        }),
    ):
        with pytest.raises(HTTPException) as refused:
            runtime.call("session.reconnect", payload, credentials)
        assert refused.value.status_code == 401
        assert refused.value.detail == {"code": "authentication_failed"}


def test_a_ready_session_is_judged_by_whatever_it_hands_in(runtime: Runtime) -> None:
    """报告是把双刃剑：ready 的会话交上一份差的，也会被如实降级。

    这正是桥接端只在"上一次已知状态不是 ready"时才带报告的原因（
    `packages/bridge-server/src/credential-handoff.ts`）：启动时探针偶发抖动，
    不该把一条正在干活的会话打下去。服务端不做这个判断 —— 谁交报告谁挨判。
    """

    receipt = _enroll(runtime, "worker", _baseline(*ADMISSION_CAPABILITIES))
    assert receipt["baseline_status"] == "ready"

    downgraded = runtime.call("session.reconnect", _reconnect_payload(receipt, _baseline(*PROVEN_ADMISSION)), receipt)

    assert downgraded["baseline_status"] == "degraded"
    assert downgraded["missing_admission"] == sorted(MISSING_ADMISSION)
    with pytest.raises(HTTPException):
        runtime.call("context.project_read", {}, downgraded)


def test_the_path_remembers_what_was_missing_at_that_moment(runtime: Runtime) -> None:
    """总路径上那两行就是"降级那刻缺什么、恢复那刻全通过"的证据。"""

    receipt = _degraded(runtime, "worker")
    enrolled = next(item for item in runtime.page()["items"] if item["action"] == "agent.enroll")
    assert enrolled["session_status"] == "degraded"
    assert enrolled["missing_admission"] == sorted(MISSING_ADMISSION)

    healed = runtime.call("session.reconnect", _reconnect_payload(receipt, _baseline(*ADMISSION_CAPABILITIES)), receipt)
    assert healed["baseline_status"] == "ready"
    reconnected = next(item for item in runtime.page()["items"] if item["action"] == "session.reconnect")
    assert reconnected["session_status"] == "ready"
    assert reconnected["missing_admission"] == []

    # 别的命令不做会话判定，所以这两个字段一直是"没有"—— 总路径不会到处挂上会话状态。
    runtime.call("agent.ticket.create.user", {
        "installation_id": "another-ide",
        "conversation_evidence": {"conversation_id": "another-ide"},
    })
    plain = next(item for item in runtime.page()["items"] if item["action"] == "agent.ticket.create.user")
    assert plain["session_status"] is None
    assert plain["missing_admission"] == []
