"""所有人都停了、又没人有事可做时，得有人叫一声（待改 23；续跑那一半见 待改 22-⑨）。

**为什么需要。** DSH 上的唤醒永远由某个 Agent 显式调用（``coordination.wake``）才会发生，
而"没人动 ⇒ 没人叫"正好闭在最需要它的那一步：worker 等任务、main 等消息、用户等结果。
用户报告的现象就是"所有 Agent 都静默、又没有完工提案"，项目停在那里直到他自己发现。

前置验证已经做过（2026-10-10，四份会话归档）：**空闲会话能被唤醒** —— 21 次 ``turn/end``
之后的注入都起了新回合（其中 11 次就是 Tsunagou 自己的唤醒插件）。所以缺的不是投递能力，
而是**没有人造出那条消息**。看门狗的角色是消息制造者，不是新的投递机制。

**两个条件，各自独立**：

* ``deadlock``（P1）：活还在、没有任何在跑的 attempt、没有可领的任务、没有已交付待验收的
  结果、没有待确认的完工提案、**没有未决的用户决定**（球在用户手上时"静默"是正确的），
  并且安静了足够久。
* ``auto_continue``（P2，待改 22-⑨）：main 手上有活（有待验收的结果、或有发给它的未读消息），
  而别人都停了 —— "交活→验收"这一跳以前每次都要等一个人，这是实测里最贵的一段等待。

**硬约束（比判定式更关键）**：只要还有任何一个会话在活动，就**不叫**。2026-10-10 实测里
main 的 51 分钟"静默"期间 worker 正以 48–154 次调用的强度干活 —— 那时叫 main 是纯噪音。
"活动"的证据是已认证会话调用（桥每 30 秒一次便宜读取，见 ``api/liveness.py``），
再加上"最近一条事件也没动过 ``IDLE_SECONDS``"这道更保守的闸：两者都要成立才叫。

**不新增任何命令字段**：消息种类不是命令字段，判定与动作都在 daemon 内部 ⇒ 协议与
``schema_bundle_digest`` 不变。开关直接复用项目设置里的 ``auto_wake_multi_agent``。
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

#: 全静默多久才算"死了"，以及 P2 的安静窗口。二者都比心跳间隔（30 秒）大一个数量级：
#: 只有"连事件都没有"才叫，宁可少叫一次，也不往正在干活的项目里塞噪音。
IDLE_SECONDS = 600.0
CONTINUE_SECONDS = 120.0
#: daemon 里那个周期任务多久跳一次。判定本身很便宜（几次数值读 + 一次定长事件查询）。
WATCHDOG_INTERVAL_SECONDS = 30.0
#: 叫过之后至少等这么久再叫第二次（防循环）。
COOLDOWN_SECONDS = 1800.0
#: 连续叫了这么多次还是没人动，就停下来交给用户（人永远是最后一道）。
MAX_ATTEMPTS = 3
#: 看门狗发给 main 的消息种类。两种都在 ``WAKE_WORTHY_KINDS`` 里，所以落库时会被排进
#: ``outbox(kind='host_wake')`` —— 投递走的是既有的自动通道，不是新机制。
DEADLOCK_MESSAGE_KIND = "coordination.stalled"
WAITING_MESSAGE_KIND = "coordination.waiting"
#: 交还用户的决定种类（控制台"待用户决定"那一节按 kind 显示）。
STALLED_DECISION_KIND = "coordination.stalled"
#: 运行层写的事件名（没有对应的命令）：控制台的命令名表里有一条中文。
WATCHDOG_EVENT_KIND = "coordination.idle_watchdog"


@dataclass(frozen=True)
class WatchdogFacts:
    """判定式的全部输入。每一项都是**读到的事实**，不是推断。"""

    lifecycle: str
    automatic_wake: bool
    online_sessions: int
    running_attempts: int
    claimable_tasks: int          # open / ready：还有活可领
    submitted_tasks: int          # 已交付待验收：main 有事可做
    pending_completion: bool      # 已经有一条待用户确认的完工提案
    pending_user_decision: bool   # 任何未决的用户决定：球在用户手上
    main_agent_id: str | None
    main_waiting_messages: int
    seconds_since_event: float | None

    def as_event_payload(self) -> dict[str, Any]:
        return {
            "lifecycle": self.lifecycle, "automatic_wake": self.automatic_wake,
            "online_sessions": self.online_sessions, "running_attempts": self.running_attempts,
            "claimable_tasks": self.claimable_tasks, "submitted_tasks": self.submitted_tasks,
            "pending_completion": self.pending_completion, "pending_user_decision": self.pending_user_decision,
            "main_waiting_messages": self.main_waiting_messages,
            "seconds_since_event": None if self.seconds_since_event is None else round(self.seconds_since_event),
        }


def idle_verdict(
    facts: WatchdogFacts, *, idle_seconds: float = IDLE_SECONDS,
    continue_seconds: float = CONTINUE_SECONDS,
) -> str | None:
    """``"deadlock"`` / ``"auto_continue"`` / ``None``。纯函数：全部判据都在这里，可单独测。"""

    if not facts.automatic_wake or facts.lifecycle != "active" or facts.main_agent_id is None:
        return None
    # 硬约束：任何会话还在活动就不叫。宁可漏一次，也不往正在干活的项目里喊人。
    if facts.online_sessions > 0:
        return None
    # 球在用户手上（未决决定 / 待确认完工）：静默是正确的，叫 main 也没用。
    if facts.pending_user_decision or facts.pending_completion:
        return None
    # 还有人在跑：不是"没人动"，是"有人正在动"。
    if facts.running_attempts > 0:
        return None
    quiet = facts.seconds_since_event
    if facts.submitted_tasks > 0 or facts.main_waiting_messages > 0:
        # main 有活干，而别人都停了 —— 交活→验收这一跳不该吃一个人的回合。
        return "auto_continue" if quiet is not None and quiet >= continue_seconds else None
    if facts.claimable_tasks > 0:
        # 还有可领的活：等 worker 来领（空闲 worker 也叫一下是后续的事，见 待改 23 的范围）。
        return None
    # 一条事件都没有（新项目）：没有证据就不叫 —— 宁可漏一次，也不凭空断言"都停了"。
    if quiet is None:
        return None
    return "deadlock" if quiet >= idle_seconds else None


@dataclass
class WatchdogLedger:
    """这次运行里叫过几次、最后一次是什么时候。重启后重新开始数（判据本身不依赖它）。"""

    attempts: int = 0
    last_at: float | None = None
    last_verdict: str | None = None
    history: list[tuple[float, str]] = field(default_factory=list)

    def record(self, verdict: str, now: float) -> None:
        self.attempts += 1
        self.last_at = now
        self.last_verdict = verdict
        self.history.append((now, verdict))

    def cooling(self, now: float, *, cooldown: float = COOLDOWN_SECONDS) -> bool:
        return self.last_at is not None and (now - self.last_at) < cooldown


def _projects_want_automatic_wake(project: Any) -> bool:
    return bool(project is not None and getattr(project, "automatic_wake_enabled", False))


class WatchdogFactsReader:
    """把判定式要的每一项从**持有状态的那一方**读出来。只读，不改任何东西。"""

    def __init__(
        self, *, database: Any, tasks: Any, messages: Any, authority: Any,
        lifecycle: Any, liveness: Any, project_registry: Any, clock: Any = time.time,
    ) -> None:
        self.database = database
        self.tasks = tasks
        self.messages = messages
        self.authority = authority
        self.lifecycle = lifecycle
        self.liveness = liveness
        self.project_registry = project_registry
        self.clock = clock

    def read(self) -> WatchdogFacts:
        project = self.project_registry.project if self.project_registry is not None else None
        statuses = [task.status for task in self.tasks.tasks.values()]
        decisions = list(self.lifecycle.decisions.values()) if self.lifecycle is not None else []
        main = getattr(self.authority, "main_agent_id", None)
        waiting = self.messages.waiting(main) if isinstance(main, str) and main else []
        return WatchdogFacts(
            lifecycle=str(getattr(project, "lifecycle", "unknown")),
            automatic_wake=_projects_want_automatic_wake(project),
            online_sessions=self._online_sessions(),
            running_attempts=len([item for item in self.tasks.attempts.values()
                                  if item.status in {"claimed", "running"}]),
            claimable_tasks=len([status for status in statuses if status in {"open", "ready"}]),
            submitted_tasks=len([status for status in statuses if status == "submitted"]),
            pending_completion=any(item.kind == "project.complete" and item.status == "pending"
                                   for item in decisions),
            pending_user_decision=any(item.status == "pending" for item in decisions),
            main_agent_id=main if isinstance(main, str) and main else None,
            main_waiting_messages=len(waiting),
            seconds_since_event=self._seconds_since_event(),
        )

    def _online_sessions(self) -> int:
        """心跳还热着的会话数。桥每 30 秒做一次便宜读取，那些调用就是"我还在"。"""

        if self.authority is None or self.liveness is None:
            return 0
        count = 0
        for session in self.authority.sessions.values():
            if not getattr(session, "active", False):
                continue
            if self.liveness.online(session.session_id, session.status):
                count += 1
        return count

    def _seconds_since_event(self) -> float | None:
        """最后一条事件到现在多久。没有事件（新项目）时给 ``None``：那种情况不叫。"""

        if self.database is None:
            return None
        try:
            with self.database._connect() as conn:
                row = conn.execute(
                    "SELECT occurred_at FROM events WHERE project_id=? ORDER BY event_seq DESC LIMIT 1",
                    (self.database.project_id,),
                ).fetchone()
        except Exception:
            return None
        if row is None or row[0] is None:
            return None
        return max(0.0, self.clock() - (int(row[0]) / 1000.0))


class IdleWatchdog:
    """判定 + 动作。判定本身是纯函数（``idle_verdict``），这里只负责读事实、做冷却与落痕。"""

    def __init__(
        self, *, reader: WatchdogFactsReader, database: Any, messages: Any, authority: Any,
        lifecycle: Any, state_runtime: Any, clock: Any = time.time,
        idle_seconds: float = IDLE_SECONDS, continue_seconds: float = CONTINUE_SECONDS,
        cooldown_seconds: float = COOLDOWN_SECONDS, max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        self.reader = reader
        self.database = database
        self.messages = messages
        self.authority = authority
        self.lifecycle = lifecycle
        self.state_runtime = state_runtime
        self.clock = clock
        self.idle_seconds = idle_seconds
        self.continue_seconds = continue_seconds
        self.cooldown_seconds = cooldown_seconds
        self.max_attempts = max_attempts
        self.ledger = WatchdogLedger()
        self.escalated = False

    def tick(self) -> dict[str, Any] | None:
        """跑一次判定；命中就动一次手。任何异常都不该让 daemon 的周期任务死掉。"""

        try:
            return self._tick()
        except Exception:
            return None

    def _tick(self) -> dict[str, Any] | None:
        facts = self.reader.read()
        verdict = idle_verdict(facts, idle_seconds=self.idle_seconds,
                              continue_seconds=self.continue_seconds)
        if verdict is None:
            return None
        now = self.clock()
        if self.ledger.cooling(now, cooldown=self.cooldown_seconds):
            return None
        if self.ledger.attempts >= self.max_attempts:
            # 叫够次数了还不动：停手，交给用户（人永远是最后一道）。只交一次。
            if not self.escalated:
                self.escalate(facts)
                self.escalated = True
            return None
        return self.act(verdict, facts, now)

    def act(self, verdict: str, facts: WatchdogFacts, now: float) -> dict[str, Any]:
        """给 main 发一条**自解释**的消息，并在同一个事务里留下这次判定的全部输入。

        消息种类在 ``WAKE_WORTHY_KINDS`` 里 ⇒ ``state_runtime.persist`` 会把它排进
        ``outbox(kind='host_wake')``，由既有的自动通道投递（DSH 那条见 待改 12）。
        通道不可用时它仍然躺在 main 的收件箱里，控制台的时间线也照旧看得到这次判定。
        """

        project = self.reader.project_registry.project
        project_id = str(getattr(project, "project_id", "local-project"))
        if verdict == "deadlock":
            kind = DEADLOCK_MESSAGE_KIND
            summary = (
                f"协作停住了：{int((facts.seconds_since_event or 0) // 60)} 分钟没有任何事件，"
                "没有在跑的尝试、没有可领的任务、也没有待确认的完工提案 —— 检查一下是不是都停了，"
                "然后接手、让 worker 继续，或者提请完工。"
            )
        else:
            kind = WAITING_MESSAGE_KIND
            summary = (
                "有活等你处理，而其他人都停了："
                f"待验收 {facts.submitted_tasks} 条，收件箱里 {facts.main_waiting_messages} 条未读；"
                "验收、发布或回复之后这条协作才会继续动。"
            )
        with self.database.transaction() as uow:
            message = self.messages.send(
                command_id=f"idle-watchdog:{verdict}:{int(now)}",
                sender_agent_id="runtime", recipient_agent_id=str(facts.main_agent_id),
                kind=kind, subject_ref="project/" + project_id, summary=summary,
                payload={"verdict": verdict, "watchdog": facts.as_event_payload()},
            )
            self._commit(uow, verdict, facts, {"message_id": message.message_id,
                                               "attempt": self.ledger.attempts + 1})
            self._stage_wake(uow, message)
        self.ledger.record(verdict, now)
        return {"verdict": verdict, "message_id": message.message_id,
                "attempt": self.ledger.attempts, "facts": facts.as_event_payload()}

    def escalate(self, facts: WatchdogFacts) -> dict[str, Any] | None:
        """叫不动就交给用户：控制台"待用户决定"那一节是既有通道，不新造一个通知面。"""

        if self.lifecycle is None:
            return None
        project = self.reader.project_registry.project
        project_id = str(getattr(project, "project_id", "local-project"))
        with self.database.transaction() as uow:
            decision = self.lifecycle.request_decision(
                kind=STALLED_DECISION_KIND, subject_ref="project/" + project_id,
                payload={
                    "summary": (
                        f"协作停住了：空闲看门狗叫了 {self.ledger.attempts} 次，main 一直没有动。"
                        "要不要继续等它自己醒来，或者你去看一眼？"
                    ),
                    "choices": ["继续等", "我去看看"],
                    "watchdog": facts.as_event_payload(),
                },
                expected_revision=int(getattr(project, "policy_revision", 1)),
            )
            self._commit(uow, "escalated", facts,
                         {"decision_id": decision.decision_id, "attempts": self.ledger.attempts})
        return {"decision_id": decision.decision_id}

    def _commit(self, uow: Any, verdict: str, facts: WatchdogFacts,
                result: dict[str, Any]) -> int:
        """写下这次判定的全部输入，并把改过的模块状态落库。

        这一条事件是**运行层**写的（没有对应的命令），所以它自己带全判定式的各项值：
        事后问"当时为什么叫"时不必再去别处拼答案。
        """

        project = self.reader.project_registry.project
        project_id = str(getattr(project, "project_id", "local-project"))
        captured = self.state_runtime.capture()
        for module, state in captured.items():
            encoded = json.dumps(state, ensure_ascii=False, sort_keys=True)
            row = uow.conn.execute(
                "SELECT payload_json FROM module_state WHERE project_id=? AND module=?",
                (uow.project_id, module),
            ).fetchone()
            if row is None or row[0] != encoded:
                uow.put_module_state(module, encoded)
        return uow.append_event(
            lineage_id=str(getattr(project, "current_lineage_id", "") or "local-lineage"),
            event_type=WATCHDOG_EVENT_KIND, aggregate_ref="project/" + project_id,
            subject_ref="project/" + project_id, actor_ref="runtime",
            payload={"verdict": verdict, "attempt": self.ledger.attempts + 1,
                     **facts.as_event_payload(), **result},
        )

    def _stage_wake(self, uow: Any, message: Any) -> None:
        """唤醒的排程与其它消息走**同一条**路（``host_wake`` outbox）。

        白名单里的种类才排：这条消息的全部意义就是让 main 动起来。排进 outbox 之后，
        投递由既有的自动通道负责（DSH 那条见 待改 12）；通道不可用时消息仍在收件箱里，
        控制台的时间线也照旧看得到这次判定 —— 看门狗只负责造出那条消息。
        """

        from tsunagou.modules.messaging import WAKE_WORTHY_KINDS as _wake_worthy

        if message.kind not in _wake_worthy:
            return        uow.stage_outbox(kind="host_wake", target_ref="message/" + message.message_id, payload={
            "message_id": message.message_id, "recipient_agent_id": message.recipient_agent_id,
        })


async def run_idle_watchdog(watchdog: IdleWatchdog, *, interval_seconds: float = 30.0) -> None:
    """daemon lifespan 里的周期任务。一跳一次，异常不外抛（周期任务不该带着整个 daemon 死）。"""

    while True:
        await asyncio.sleep(interval_seconds)
        watchdog.tick()

