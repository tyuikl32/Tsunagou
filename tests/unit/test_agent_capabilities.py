"""Agent 管理页那两栏（基础能力 4 项 / 运营能力 7 项）是**当前状态**，不是档案。

会话在准入时留下宿主的那份自报（`authority.baseline_rows` 收成有界的行），agents 出口再按
`shared_kernel.baseline` 里的那条规则算出"缺哪几项" —— 与准入闸门用的是同一条规则，
所以页面上的绿勾不会和"这个会话到底 ready 不 ready"两说。没有活动会话的 Agent
一律四个字段都是 null：不拿"不知道"冒充"都没有"。
"""

from __future__ import annotations

from typing import Any

from tests.unit.test_trace_audit import Runtime
from tests.unit.test_trace_audit import runtime as runtime  # noqa: F401  (夹具按名字取用)

from tsunagou.bootstrap.container import _agent_features
from tsunagou.shared_kernel.baseline import (
    ADMISSION_CAPABILITIES,
    BASELINE_CAPABILITIES,
    OPERATIONAL_CAPABILITIES,
)

MISSING_ADMISSION = ("identity.continuity_evidence", "command.typed_tools")


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


def _agent_row(runtime: Runtime, agent_id: str) -> dict[str, Any]:
    endpoint = runtime.endpoint("/api/v1/projects/{project_id}/agents")
    return next(
        item for item in endpoint(runtime.project_id)["items"] if item["agent_id"] == agent_id
    )


def test_a_session_that_proved_everything_owes_nothing(runtime: Runtime) -> None:
    receipt = _enroll(runtime, "main", _baseline(*BASELINE_CAPABILITIES))

    row = _agent_row(runtime, receipt["agent_id"])

    assert row["session_status"] == "ready"
    assert row["connection_epoch"] == receipt["connection_epoch"]
    assert row["missing_admission"] == []
    assert row["missing_operational"] == []


def test_a_ready_session_still_owes_the_operational_seven(runtime: Runtime) -> None:
    """准入过了不等于活干过：那 7 项只能由真干活证明。"""
    receipt = _enroll(runtime, "worker", _baseline(*ADMISSION_CAPABILITIES))

    row = _agent_row(runtime, receipt["agent_id"])

    assert row["session_status"] == "ready"
    assert row["missing_admission"] == []
    assert row["missing_operational"] == sorted(OPERATIONAL_CAPABILITIES)


def test_a_degraded_session_names_exactly_what_is_missing(runtime: Runtime) -> None:
    proven = tuple(name for name in ADMISSION_CAPABILITIES if name not in MISSING_ADMISSION)
    receipt = _enroll(runtime, "degraded", _baseline(*proven))

    row = _agent_row(runtime, receipt["agent_id"])

    assert row["session_status"] == "degraded"
    assert row["missing_admission"] == sorted(MISSING_ADMISSION)
    assert row["missing_operational"] == sorted(OPERATIONAL_CAPABILITIES)


def test_an_agent_without_a_session_gets_no_verdict(runtime: Runtime) -> None:
    _enroll(runtime, "alone", _baseline(*BASELINE_CAPABILITIES))

    features = _agent_features(runtime.app.state.state_runtime.authority, "not-an-agent")

    assert features == {
        "session_status": None, "connection_epoch": None,
        "missing_admission": None, "missing_operational": None,
    }
