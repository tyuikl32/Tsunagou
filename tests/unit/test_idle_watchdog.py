"""空闲看门狗：判据是纯函数，动作要留下能被复查的痕迹（待改 23 与 22-⑨）。

判据的每一条守卫都要能单独验（在线会话、未决决定、待确认完工、在跑的尝试、还能领的活、
开关、项目状态）；动作那一半要证明三件事：给 main 的消息真的发出来了、这次判定进了审计、
冷却与"叫够次数就交给用户"都成立。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from tests.integration.test_state_integrity import events
from tests.integration.test_state_integrity import runtime as _runtime_fixture

from tsunagou.api.liveness import SessionLiveness
from tsunagou.application.idle_watchdog import (
    DEADLOCK_MESSAGE_KIND,
    WATCHDOG_EVENT_KIND,
    IdleWatchdog,
    WatchdogFacts,
    WatchdogFactsReader,
    idle_verdict,
)


def _facts(**overrides: Any) -> WatchdogFacts:
    base: dict[str, Any] = {
        "lifecycle": "active", "automatic_wake": True, "online_sessions": 0,
        "running_attempts": 0, "claimable_tasks": 0, "submitted_tasks": 0,
        "pending_completion": False, "pending_user_decision": False,
        "main_agent_id": "main", "main_waiting_messages": 0, "seconds_since_event": 10_000.0,
    }
    return WatchdogFacts(**{**base, **overrides})


def test_a_project_nobody_can_move_is_recognised_as_a_deadlock() -> None:
    assert idle_verdict(_facts()) == "deadlock"


@pytest.mark.parametrize("override", [
    {"online_sessions": 1},          # 硬约束：任何会话还在活动就不叫（2026-10-10：worker 正在干活）
    {"pending_user_decision": True},  # 球在用户手上：静默是正确的
    {"pending_completion": True},     # 已经有一条待确认的完工提案：等用户
    {"running_attempts": 1},          # 有人在跑
    {"claimable_tasks": 2},           # 还有活可领：等 worker 来领
    {"lifecycle": "completed"},
    {"automatic_wake": False},
    {"main_agent_id": None},
    {"seconds_since_event": 10.0},    # 还没安静够
    {"seconds_since_event": None},    # 一条事件都没有：没有证据就不叫
])
def test_every_guard_holds_on_its_own(override: dict[str, Any]) -> None:
    assert idle_verdict(_facts(**override)) is None


def test_main_having_work_is_what_auto_continuation_is_for() -> None:
    """交活→验收这一跳不该吃一个人的回合（待改 22-⑨ / C1）。"""

    assert idle_verdict(_facts(submitted_tasks=1, seconds_since_event=300.0)) == "auto_continue"
    assert idle_verdict(_facts(main_waiting_messages=2, seconds_since_event=300.0)) == "auto_continue"
    # 刚交完活、还没安静够：那一跳本来就该由交活的人唤，看门狗别抢。
    assert idle_verdict(_facts(submitted_tasks=1, seconds_since_event=5.0)) is None
    # 有人还在跑：那不是"main 可以接手"，是"有人正在做"。
    assert idle_verdict(_facts(submitted_tasks=1, running_attempts=1, seconds_since_event=300.0)) is None


@pytest.fixture(name="runtime")
def watchdog_runtime(tmp_path, monkeypatch):
    yield from _runtime_fixture.__wrapped__(tmp_path, monkeypatch)


def _watchdog(app: Any, **kwargs: Any) -> IdleWatchdog:
    state = app.state.state_runtime
    reader = WatchdogFactsReader(
        database=app.state.project_database, tasks=state.tasks, messages=state.messages,
        authority=state.authority, lifecycle=state.lifecycle,
        liveness=SessionLiveness(), project_registry=app.state.project_registry,
    )
    # 阈值归零：这几条用例要验的是动作与冷却，不是"等够 10 分钟"。
    return IdleWatchdog(
        reader=reader, database=app.state.project_database, messages=state.messages,
        authority=state.authority, lifecycle=state.lifecycle, state_runtime=state,
        idle_seconds=0.0, continue_seconds=0.0, **kwargs,
    )


def test_the_watchdog_wakes_main_and_leaves_the_evidence(runtime) -> None:
    app, call, main, worker = runtime
    watchdog = _watchdog(app)
    fired = watchdog.tick()
    assert fired is not None and fired["verdict"] == "deadlock"

    inbox = call("inbox.claim", {"limit": 20}, main)
    (notice,) = [item for item in inbox["messages"] if item["kind"] == DEADLOCK_MESSAGE_KIND]
    assert "停住了" in notice["summary"], "消息要自解释，而不是一句'看看项目'"
    assert notice["sender_agent_id"] == "runtime"

    (recorded,) = [event for event in events(app) if event["event_type"] == WATCHDOG_EVENT_KIND]
    payload = json.loads(recorded["payload_json"])
    assert payload["verdict"] == "deadlock"
    assert payload["online_sessions"] == 0, "判定当时的各项值要留在事件里，事后可复查"
    assert payload["seconds_since_event"] is not None
    assert watchdog.tick() is None, "冷却期内不重复叫"


def test_calling_main_enough_times_hands_the_project_back_to_the_user(runtime) -> None:
    app, call, main, worker = runtime
    watchdog = _watchdog(app, cooldown_seconds=0.0, max_attempts=2)
    assert watchdog.tick() is not None
    assert watchdog.tick() is not None
    assert watchdog.tick() is None, "叫够次数就不再叫 main"

    (decision,) = [item for item in app.state.state_runtime.lifecycle.decisions.values()
                   if item.kind == "coordination.stalled"]
    assert "看门狗" in str(decision.payload.get("summary"))
    assert decision.payload.get("choices"), "要给出可选答复，用户才知道怎么回"
    assert app.state.state_runtime.lifecycle.decisions[decision.decision_id].status == "pending"
    assert watchdog.tick() is None, "交还用户只做一次"
