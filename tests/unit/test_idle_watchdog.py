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
    WAITING_MESSAGE_KIND,
    WATCHDOG_EVENT_KIND,
    IdleWatchdog,
    WatchdogFacts,
    WatchdogFactsReader,
    idle_verdict,
    resume_targets,
    stalled_waiters,
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


# --- P3：有任务但还没提交 ⇒ 把它自己叫回来（2026-10-10 用户实测报告） -------------


def _resume_facts(**overrides: Any) -> WatchdogFacts:
    entry: dict[str, Any] = {
        "agent_id": "worker", "task_id": "task-1", "attempt_id": "attempt-1",
        "quiet_seconds": 3600.0, "session_state": "idle",
    }
    base: dict[str, Any] = {"unsubmitted": (entry,)}
    return _facts(**{**base, **overrides})


def test_a_task_that_was_never_submitted_is_what_resume_is_for() -> None:
    """判据就一条：有尝试、没提交、而它自己安静够久。别人的忙碌不遮挡它。"""

    assert [item["agent_id"] for item in resume_targets(_resume_facts())] == ["worker"]
    # 别的会话还在忙也不影响：这一条针对的是**某一个**停了的人，不是"大家都停了"。
    assert resume_targets(_resume_facts(online_sessions=3))
    assert resume_targets(_resume_facts(running_attempts=1))


@pytest.mark.parametrize("override", [
    {"automatic_wake": False},                 # 项目关掉了自动唤醒
    {"lifecycle": "completed"},                # 已经收工
    {"unsubmitted": ()},                       # 没有没提交的尝试：提交了就是干完了
    {"unsubmitted": ({"agent_id": "worker", "task_id": "t", "attempt_id": "a",
                      "quiet_seconds": 30.0, "session_state": "idle"},)},   # 才安静 30 秒
    {"unsubmitted": ({"agent_id": "worker", "task_id": "t", "attempt_id": "a",
                      "quiet_seconds": None, "session_state": "idle"},)},   # 没有证据
    {"unsubmitted": ({"agent_id": "worker", "task_id": "t", "attempt_id": "a",
                      "quiet_seconds": 3600.0, "session_state": "running"},)},  # 宿主说它正在跑
    # 宿主不说话时只有 600 秒的保守窗口：安静 120 秒还不够（2026-10-10：分档的依据）。
    {"unsubmitted": ({"agent_id": "worker", "task_id": "t", "attempt_id": "a",
                      "quiet_seconds": 120.0, "session_state": None},)},
    # 球在用户手上：谁都不该被催。
    {"pending_user_decision": True},
    # 它问出去的话还没人答：这种安静是**故意的**。
    {"owed_replies": ("worker",)},
])
def test_every_resume_guard_holds_on_its_own(override: dict[str, Any]) -> None:
    assert resume_targets(_resume_facts(**override)) == []


def test_the_resume_window_depends_on_whether_the_host_will_say() -> None:
    """窗口分两档（2026-10-10 用户的实测要求：等十分钟等于没有）。

    缩短窗口的前提是判据可靠：宿主明确说这条会话不在跑（``idle`` / ``unloaded``）时，
    "它现在真的没在执行任何东西"是事实，90 秒就够；宿主不说话（例如 Codex 那条 lane）时
    唯一的证据是"它连命令都不发了"，而本地写代码本来就不发命令 ⇒ 用 600 秒的保守窗口。
    """

    def entry(quiet: float, state: Any) -> dict[str, Any]:
        return {"agent_id": "worker", "task_id": "t", "attempt_id": "a",
                "quiet_seconds": quiet, "session_state": state}

    assert resume_targets(_resume_facts(unsubmitted=(entry(120.0, "idle"),))), \
        "宿主说它没在跑：两分钟就该叫回来"
    assert resume_targets(_resume_facts(unsubmitted=(entry(120.0, "unloaded"),))), \
        "unloaded 也一样：它没有在执行任何东西"
    assert resume_targets(_resume_facts(unsubmitted=(entry(120.0, None),))) == [], \
        "宿主不说不等于它没在跑：这里要保守"
    assert resume_targets(_resume_facts(unsubmitted=(entry(700.0, None),))), \
        "但十分钟连命令都没有，就足够叫一次了"
    fired = resume_targets(_resume_facts(unsubmitted=(entry(120.0, "idle"),)))[0]
    assert fired["window_seconds"] == 90.0, "用了哪一档要能事后查"


def test_waiting_for_somebody_else_is_not_being_stuck() -> None:
    """用户指出的风险：做一半发现要等 main/别的 Agent 做完 ⇒ 那**不是**停在中途。

    但"别人还在忙"**不是**判据（2026-10-10 修正）：一个几十分钟的实验里，全局安静那道闸
    永远不成立，等于把这条规则关掉 —— 而"别人在忙不代表它没停"正是它存在的理由。真正能
    护住"在等"的事实只有两条：
    1. 它问了别人（``owed_replies``）—— 球在对方手上；
    2. 它自己 ``task.block``（尝试结束 ⇒ 根本不在候选里，另有用例覆盖）。
    """

    waiting_on_a_reply = _resume_facts(owed_replies=("worker",))
    assert resume_targets(waiting_on_a_reply) == []
    # 但这件事不能就这么静着：main 得知道有条答复一直没人给（否则整条协作停在这里，
    # 而 deadlock 也因为它还有在跑的尝试而不成立 —— 那会是个谁都收不到消息的盲区）。
    assert [item["agent_id"] for item in stalled_waiters(waiting_on_a_reply)] == ["worker"]

    # 别人在忙不再免除它：它自己的会话停着，就该被叫回来（这正是用户报的那个场景）。
    others_are_working = _resume_facts(seconds_since_event=45.0, online_sessions=2)
    assert [item["agent_id"] for item in resume_targets(others_are_working)] == ["worker"]

    # 空转的候选（在等答复但项目也没停）同样不叫 main —— main 那条路要的是"整条协作都停了"。
    assert stalled_waiters(_resume_facts(owed_replies=("worker",), seconds_since_event=0.0)) == []


def _begun_attempt(runtime) -> tuple[Any, Any, Any]:
    """把 worker 派上一条任务并真的开工：这就是"有任务、还没提交"的状态。"""

    app, call, main, worker = runtime
    created = call("task.create", {
        "title": "写一段实现", "objective": "把这一部分做完", "execution_scope": {},
    }, main)
    task_id = created["task_id"]
    call("task.ready", {"task_id": task_id}, main)
    published = call("task.publish", {"task_id": task_id}, main)
    call("task.begin", {"task_id": task_id, "expected_task_revision": published["revision"]}, worker)
    return app, task_id, worker


def test_a_resumed_worker_gets_a_real_wake_row(runtime) -> None:
    """用户报告的那个 bug：一个 Agent 做完一部分、输出总结后会话就停了，然后空闲半天。

    这一条同时钉住 ``_stage_wake`` 的**反了的守卫**（2026-10-10 复测发现）：原来消息落库了，
    却从来没有排进 ``host_wake`` —— 等于"叫了但没人被叫"。
    """

    app, task_id, worker = _begun_attempt(runtime)
    watchdog = _watchdog(app, resume_seconds=0.0, resume_unverified_seconds=0.0)

    fired = watchdog.tick()
    assert fired is not None and fired["verdict"] == "resume"
    assert fired["task_id"] == task_id and fired["attempt"] == 1

    inbox = runtime[1]("inbox.claim", {"limit": 20}, worker)
    (notice,) = [item for item in inbox["messages"] if item["kind"] == "task.resume"]
    assert "还没提交" in notice["summary"] and "task.submit" in notice["summary"]
    assert "回合结束" in notice["summary"], "要说清为什么会停：文字回复 = 回合结束"

    # 真的排进了自动通道 —— 这条是那个 bug 的回归测试。
    with app.state.project_database._connect() as conn:
        rows = conn.execute(
            "SELECT o.target_ref, e.payload_json FROM outbox o JOIN events e ON "
            "o.project_id=e.project_id AND o.event_seq=e.event_seq WHERE o.kind='host_wake'"
        ).fetchall()
    assert len(rows) == 1, "看门狗的消息必须排一次 host_wake，否则没人会被叫醒"
    assert rows[0][0] == "message/" + notice["message_id"]
    assert json.loads(rows[0][1])["message_id"] == notice["message_id"]

    payload = json.loads([event for event in events(app)
                          if event["event_type"] == WATCHDOG_EVENT_KIND][0]["payload_json"])
    assert payload["verdict"] == "resume"
    assert payload["unsubmitted"][0]["attempt_id"] == fired["attempt_id"]
    assert watchdog.tick() is None, "冷却期内不重复叫"


def test_a_worker_the_host_calls_running_is_never_nagged(runtime) -> None:
    """别打扰正在干活的人：宿主说 running 就不叫（这是 P3 唯一的"看别人"的判据）。"""

    app, _task_id, _worker = _begun_attempt(runtime)
    reader = WatchdogFactsReader(
        database=app.state.project_database, tasks=app.state.state_runtime.tasks,
        messages=app.state.state_runtime.messages, authority=app.state.state_runtime.authority,
        lifecycle=app.state.state_runtime.lifecycle, liveness=SessionLiveness(),
        project_registry=app.state.project_registry, session_state=lambda agent_id: "running",
        resume_seconds=0.0,
    )
    watchdog = IdleWatchdog(
        reader=reader, database=app.state.project_database, messages=app.state.state_runtime.messages,
        authority=app.state.state_runtime.authority, lifecycle=app.state.state_runtime.lifecycle,
        state_runtime=app.state.state_runtime, resume_seconds=0.0,
    )
    assert watchdog.tick() is None
    with app.state.project_database._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM outbox WHERE kind='host_wake'").fetchone()[0] == 0


def test_calling_a_stopped_worker_enough_times_hands_it_to_main(runtime) -> None:
    """叫不动就交给 main（它是协调者）：催、换人、收回去，都是它权限内的事。"""

    app, task_id, _worker = _begun_attempt(runtime)
    watchdog = _watchdog(app, resume_seconds=0.0, resume_unverified_seconds=0.0,
                         resume_cooldown_seconds=0.0,
                         resume_max_attempts=2)
    assert watchdog.tick() is not None
    assert watchdog.tick() is not None
    assert watchdog.tick() is None, "叫够次数就不再叫 worker"
    assert watchdog.tick() is None, "交给 main 也只做一次"

    app_state = app.state.state_runtime
    main = runtime[2]
    assert app_state.authority.main_agent_id == main["agent_id"]
    inbox = runtime[1]("inbox.claim", {"limit": 20}, main)
    handoff = [item for item in inbox["messages"] if item["kind"] == WAITING_MESSAGE_KIND]
    assert handoff, "叫不动要告诉 main，而不是就此静默"
    assert str(task_id) in handoff[0]["summary"]
    verdicts = [json.loads(event["payload_json"])["verdict"] for event in events(app)
                if event["event_type"] == WATCHDOG_EVENT_KIND]
    assert verdicts.count("resume") == 2 and verdicts.count("resume_handoff") == 1
