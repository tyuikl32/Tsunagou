"""所有人都停了、又没人有事可做时，得有人叫一声（待改 23；续跑那一半见 待改 22-⑨）。

**为什么需要。** DSH 上的唤醒永远由某个 Agent 显式调用（``coordination.wake``）才会发生，
而"没人动 ⇒ 没人叫"正好闭在最需要它的那一步：worker 等任务、main 等消息、用户等结果。
用户报告的现象就是"所有 Agent 都静默、又没有完工提案"，项目停在那里直到他自己发现。

前置验证已经做过（2026-10-10，四份会话归档）：**空闲会话能被唤醒** —— 21 次 ``turn/end``
之后的注入都起了新回合（其中 11 次就是 Tsunagou 自己的唤醒插件）。所以缺的不是投递能力，
而是**没有人造出那条消息**。看门狗的角色是消息制造者，不是新的投递机制。

**三个条件，各自独立**：

* ``deadlock``（P1）：活还在、没有任何在跑的 attempt、没有可领的任务、没有已交付待验收的
  结果、没有待确认的完工提案、**没有未决的用户决定**（球在用户手上时"静默"是正确的），
  并且安静了足够久。
* ``auto_continue``（P2，待改 22-⑨）：main 手上有活（有待验收的结果、或有发给它的未读消息），
  而别人都停了 —— "交活→验收"这一跳以前每次都要等一个人，这是实测里最贵的一段等待。
* ``resume``（P3，2026-10-10 用户实测报告）：**某个 Agent 的尝试还没提交**，而它已经安静了
  足够久 —— 把它自己叫回来。用户报告的现象是"一个 Agent 做完一部分工作、输出一段总结之后
  会话就停了，然后空闲了半天"。根因不在 Tsunagou：在宿主里**只输出文字就等于回合结束**
  （DSH 的会话状态词表是 ``running`` / ``idle`` / ``unloaded``），所以 agent 说完话就没人叫它了。
  但 daemon 完全看得出来"它还有没提交的尝试"，而且自动通道现在通了 ⇒ 造一条消息给它。
  这一条是**唯一**不要求"所有人都停了"的条件：别人在忙不代表它没停。

**硬约束（比判定式更关键）**：只要还有任何一个会话在活动，``deadlock``/``auto_continue`` 就
**不叫**。2026-10-10 实测里 main 的 51 分钟"静默"期间 worker 正以 48–154 次调用的强度干活 ——
那时叫 main 是纯噪音。"活动"的证据是已认证会话调用（桥每 30 秒一次便宜读取，见
``api/liveness.py``），再加上"最近一条事件也没动过 ``IDLE_SECONDS``"这道更保守的闸：两者都要
成立才叫。``resume`` 不用这道闸（它针对的是**某一个**停了的人），但要用**它自己**的证据：
宿主明确说这条会话"正在跑"就不打扰，以及它自己安静了 ``RESUME_SECONDS`` 以上。

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
#: ``resume``（P3）自己的窗口：尝试没提交、而它已经安静了这么久，才把它叫回来。
#: **分两档**，因为判据的可靠性不同（2026-10-10 用户实测后的修正：在一个只有几十分钟的测试里，
#: 十分钟的窗口等于没有；而"整个项目都安静"那道闸在活跃实验里永远不成立）：
#:
#: * 宿主**明确说**这条会话不在跑（``idle`` / ``unloaded``）⇒ 用短窗口。那是"它现在真的没在
#:   执行任何东西"，所以短窗口不会打扰在干活的人：一个 agent 在本地跑五分钟构建时，它的回合是
#:   **running**，宿主会直说，我们根本不看窗口。
#: * 宿主不说话（``None``，例如 Codex 那条 lane）⇒ 用长窗口。那时唯一的证据是"它连命令都不发
#:   了"，而本地写代码本来就不发命令，必须保守。
RESUME_SECONDS = 90.0
RESUME_UNVERIFIED_SECONDS = 600.0
#: 同一条尝试两次叫它之间至少隔多久。必须比窗口小一个量级：半小时的冷却意味着一次几十分钟的
#: 测试里"叫过一次就再也不会叫"（实测教训），而这条规则的目的是**把它拉回来继续干**。
RESUME_COOLDOWN_SECONDS = 180.0
#: 同一条尝试最多叫几次；再多就交给 main（它是协调者，由它决定催、换人还是让它阻塞）。
RESUME_MAX_ATTEMPTS = 3
#: 看门狗发给 main 的消息种类。两种都在 ``WAKE_WORTHY_KINDS`` 里，所以落库时会被排进
#: ``outbox(kind='host_wake')`` —— 投递走的是既有的自动通道，不是新机制。
DEADLOCK_MESSAGE_KIND = "coordination.stalled"
WAITING_MESSAGE_KIND = "coordination.waiting"
#: 发给"停在中途的 worker 自己"的消息种类（也在 ``WAKE_WORTHY_KINDS`` 里）。
RESUME_MESSAGE_KIND = "task.resume"
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
    #: 每条**没提交、也没结束**的尝试：``{agent_id, task_id, attempt_id, quiet_seconds,
    #: session_state}``。``session_state`` 是宿主的说法（``running`` / ``idle`` /
    #: ``unloaded``），拿不到就是 ``None`` —— 那时不假装知道，交给 ``quiet_seconds`` 判。
    unsubmitted: tuple[dict[str, Any], ...] = ()
    #: 谁在**等别人的答复**（它发出去的消息还有未结清的回应义务）。这种"安静"是**故意的**，
    #: 不是停在中途 —— 2026-10-10 用户指出的风险：做一半发现要等 main 或别的 Agent 做完
    #: 才能继续，那时催它就是纯噪音。
    owed_replies: tuple[str, ...] = ()

    def as_event_payload(self) -> dict[str, Any]:
        return {
            "lifecycle": self.lifecycle, "automatic_wake": self.automatic_wake,
            "online_sessions": self.online_sessions, "running_attempts": self.running_attempts,
            "claimable_tasks": self.claimable_tasks, "submitted_tasks": self.submitted_tasks,
            "pending_completion": self.pending_completion, "pending_user_decision": self.pending_user_decision,
            "main_waiting_messages": self.main_waiting_messages,
            "seconds_since_event": None if self.seconds_since_event is None else round(self.seconds_since_event),
            "owed_replies": list(self.owed_replies),
            "unsubmitted": [
                {**entry, "quiet_seconds": None if entry.get("quiet_seconds") is None
                 else round(float(entry["quiet_seconds"]))}
                for entry in self.unsubmitted
            ],
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


def resume_targets(
    facts: WatchdogFacts, *, resume_seconds: float = RESUME_SECONDS,
    unverified_seconds: float = RESUME_UNVERIFIED_SECONDS,
) -> list[dict[str, Any]]:
    """谁该被叫回来（P3）：**有任务、但那条尝试还没提交**，而它自己已经安静够久。

    判据（每条都是读到的事实）：

    1. 它有一条**没提交、也没结束**的尝试（``claimed`` / ``running`` / ``orphaned``）——
       提交了就是干完了，等验收是 main 的事；``orphaned`` 是 daemon 重启时留下的"停在中途"，
       正是最该被拉回来的那种。
    2. **宿主没有说它"正在跑"**：正在跑就不打扰。宿主会说 ``idle`` / ``unloaded``（它没在
       执行任何东西）或干脆不说（``None``）。
    3. **它自己安静够了**，窗口按第 2 条的可靠性分档：宿主明确说它没在跑 ⇒
       ``resume_seconds``（短，默认 90 秒）；宿主不说话 ⇒ ``unverified_seconds``（长，默认
       600 秒）。**不再要求"整个项目安静"** —— 2026-10-10 实测：一个几十分钟的协作实验里
       那条闸永远不成立，等于把这条规则关掉；而"别人在忙不代表它没停"本来就是它存在的理由。
    4. 没有未决的用户决定（球在用户手上谁都不催），也没有人在欠它答复（那种安静是故意的）。

    要等别人又不想被当成停在中途，协议里本来就有表达：``task.block`` 会结束这条尝试（于是它
    根本不在候选里），或者回一条消息把球踢出去（第 4 条护住它）。
    """

    if not facts.automatic_wake or facts.lifecycle != "active":
        return []
    if facts.pending_user_decision:
        return []
    targets = []
    for entry in facts.unsubmitted:
        if str(entry.get("agent_id") or "") in facts.owed_replies:
            continue
        state = str(entry.get("session_state") or "").strip()
        if state == "running":
            continue
        window = resume_seconds if state else unverified_seconds
        quiet = entry.get("quiet_seconds")
        if quiet is None or float(quiet) < window:
            continue
        targets.append({**entry, "window_seconds": window})
    return targets


def stalled_waiters(
    facts: WatchdogFacts, *, quiet_seconds: float = RESUME_UNVERIFIED_SECONDS,
) -> list[dict[str, Any]]:
    """有人**在等一个答复**、而整个项目也停了 —— 那件没结清的事得让 main 知道。

    没有这一条会留一个盲区：候选被"它在等人答复"护住之后，``deadlock`` 也因为它还有在跑的
    尝试而不成立 ⇒ 谁都收不到消息。**谁欠的答复**是 main 能处理的事（催、换人、或者判定那条
    依赖不再需要），所以交给它，不交给用户。

    窗口用**长**的那一档（默认 600 秒）：这条是"整个项目都没动"的信号，比"某一条会话停了"
    重得多，早叫只会变成噪音。
    """

    if not facts.automatic_wake or facts.lifecycle != "active" or facts.pending_user_decision:
        return []
    if facts.seconds_since_event is None or facts.seconds_since_event < quiet_seconds:
        return []
    stalled = []
    for entry in facts.unsubmitted:
        if str(entry.get("agent_id") or "") not in facts.owed_replies:
            continue
        quiet = entry.get("quiet_seconds")
        if quiet is None or float(quiet) < quiet_seconds:
            continue
        stalled.append(dict(entry))
    return stalled


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
        session_state: Any = None, resume_seconds: float = RESUME_SECONDS,
    ) -> None:
        self.database = database
        self.tasks = tasks
        self.messages = messages
        self.authority = authority
        self.lifecycle = lifecycle
        self.liveness = liveness
        self.project_registry = project_registry
        self.clock = clock
        # 宿主怎么形容某条会话（``running`` / ``idle`` / ``unloaded``）。拿不到就是 None：
        # 这个读法只用于 ``resume`` 的"别打扰正在干活的人"，缺了它退回保守判据。
        self.session_state = session_state
        #: 到了这个窗口才值得为一条尝试付一次宿主调用（用网络换"它是不是正在跑"）。
        self.resume_seconds = resume_seconds

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
            unsubmitted=self._unsubmitted(),
            owed_replies=self._owed_replies(),
        )

    def _owed_replies(self) -> tuple[str, ...]:
        """谁发出去的消息还挂着**未结清的回应义务** —— 也就是"它问了，别人还没答"。

        这种安静是**故意的**：它在等一个明确问出去的答复，不是在停在中途。事实全在消息那一侧
        （``ResponseObligation.recipient_agent_id`` 是**欠答复**的人，消息的
        ``sender_agent_id`` 才是**在等**的人），所以这里不需要任何新状态。
        """

        if self.messages is None:
            return ()
        owed: list[str] = []
        for obligation in getattr(self.messages, "obligations", {}).values():
            if getattr(obligation, "status", "") != "open":
                continue
            message = getattr(self.messages, "messages", {}).get(getattr(obligation, "message_id", ""))
            sender = str(getattr(message, "sender_agent_id", "") or "") if message is not None else ""
            debtor = str(getattr(obligation, "recipient_agent_id", "") or "")
            if sender and sender != debtor:
                owed.append(sender)
        return tuple(dict.fromkeys(owed))

    def _unsubmitted(self) -> tuple[dict[str, Any], ...]:
        """还没提交、也没结束的尝试 —— ``resume`` 的全部候选。

        只问"它自己安静了多久"，并且**先算安静时间再问宿主**：宿主那一次是网络调用，
        不该为每一条尝试都付。
        """

        entries = []
        for attempt in self.tasks.attempts.values():
            if attempt.status not in {"claimed", "running", "orphaned"}:
                continue
            quiet = self._quiet_seconds(getattr(attempt, "owner_agent_id", ""), attempt)
            entry: dict[str, Any] = {
                "agent_id": str(getattr(attempt, "owner_agent_id", "")),
                "task_id": str(getattr(attempt, "task_id", "")),
                "attempt_id": str(getattr(attempt, "attempt_id", "")),
                "quiet_seconds": quiet,
                "session_state": None,
            }
            if self.session_state is not None and quiet is not None and quiet >= self.resume_seconds:
                entry["session_state"] = self._session_state(entry["agent_id"])
            entries.append(entry)
        return tuple(entries)

    def _session_state(self, agent_id: str) -> str | None:
        if not agent_id or self.session_state is None:
            return None
        try:
            value = self.session_state(agent_id)
        except Exception:
            return None
        return str(value) if value else None

    def _quiet_seconds(self, agent_id: str, attempt: Any) -> float | None:
        """这个 Agent 自己安静了多久。

        用**它自己的**事件（``actor_ref`` 就是 agent_id，见 ``state_runtime.audit_actor``），
        而不是全局最后一条 —— 别人在忙不该把"它停了"盖掉。它一条事件都没有时退回"尝试开始
        了多久"，还是拿不到就不判（``None`` ⇒ 不叫，宁可漏一次）。
        """

        if self.database is None:
            return None
        last: float | None = None
        try:
            with self.database._connect() as conn:
                row = (conn.execute(
                    "SELECT occurred_at FROM events WHERE project_id=? AND actor_ref=? "
                    "ORDER BY event_seq DESC LIMIT 1",
                    (self.database.project_id, agent_id),
                ).fetchone() if agent_id else None)
            if row is not None and row[0] is not None:
                last = int(row[0]) / 1000.0
        except Exception:
            last = None
        if last is None:
            started = getattr(attempt, "started_at", None)
            last = float(started) if isinstance(started, (int, float)) else None
        if last is None:
            return None
        return max(0.0, self.clock() - last)

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
        resume_seconds: float = RESUME_SECONDS,
        resume_unverified_seconds: float = RESUME_UNVERIFIED_SECONDS,
        resume_cooldown_seconds: float = RESUME_COOLDOWN_SECONDS,
        resume_max_attempts: int = RESUME_MAX_ATTEMPTS,
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
        self.resume_seconds = resume_seconds
        self.resume_unverified_seconds = resume_unverified_seconds
        self.resume_cooldown_seconds = resume_cooldown_seconds
        self.resume_max_attempts = resume_max_attempts
        self.ledger = WatchdogLedger()
        self.escalated = False
        #: ``attempt_id -> 上次叫它的时刻``、``attempt_id -> 叫过几次``。``resume`` 是**逐条
        #: 尝试**的：一条尝试冷却不该影响另一条，也不该被 main 那本账的冷却挡住。
        self.resumed_at: dict[str, float] = {}
        self.resume_counts: dict[str, int] = {}
        self.handed_off: dict[str, bool] = {}

    def tick(self) -> dict[str, Any] | None:
        """跑一次判定；命中就动一次手。任何异常都不该让 daemon 的周期任务死掉。"""

        try:
            return self._tick()
        except Exception:
            return None

    def _tick(self) -> dict[str, Any] | None:
        facts = self.reader.read()
        now = self.clock()
        # P3 先跑：它针对的是"某一个停了的人"，与"所有人都停了"（P1）互斥（P1 要求没有
        # 在跑的尝试），与 main 的续跑（P2）可以同跳发生 —— 两个收件人不同，互不遮挡。
        resumed = self.resume_round(facts, now)
        verdict = idle_verdict(facts, idle_seconds=self.idle_seconds,
                              continue_seconds=self.continue_seconds)
        if verdict is None:
            return resumed
        if self.ledger.cooling(now, cooldown=self.cooldown_seconds):
            return resumed
        if self.ledger.attempts >= self.max_attempts:
            # 叫够次数了还不动：停手，交给用户（人永远是最后一道）。只交一次。
            if not self.escalated:
                self.escalate(facts)
                self.escalated = True
            return resumed
        return self.act(verdict, facts, now) or resumed

    def resume_round(self, facts: WatchdogFacts, now: float) -> dict[str, Any] | None:
        """P3：把"有任务、但那条尝试还没提交"的 Agent 叫回来。每跳最多叫一条，防一口气刷屏。"""

        for entry in resume_targets(facts, resume_seconds=self.resume_seconds,
                                   unverified_seconds=self.resume_unverified_seconds):
            attempt_id = str(entry.get("attempt_id") or "")
            if not attempt_id:
                continue
            last = self.resumed_at.get(attempt_id)
            if last is not None and (now - last) < self.resume_cooldown_seconds:
                continue
            count = self.resume_counts.get(attempt_id, 0)
            if count >= self.resume_max_attempts:
                if not self.handed_off.get(attempt_id):
                    self.hand_off(entry, facts, now)
                    self.handed_off[attempt_id] = True
                continue
            return self.act_resume(entry, facts, now)
        # 没人该被叫回来，但有人的候选被"它在等一个答复"护住了、而整个项目也停了：那件
        # 没结清的答复得让 main 知道（否则这条协作就静在那里，谁都收不到消息）。
        for entry in stalled_waiters(facts, quiet_seconds=self.resume_unverified_seconds):
            attempt_id = str(entry.get("attempt_id") or "")
            if not attempt_id or self.handed_off.get(attempt_id):
                continue
            self.hand_off(entry, facts, now, waiting_on_reply=True)
            self.handed_off[attempt_id] = True
            return {"verdict": "resume_handoff", "attempt_id": attempt_id}
        return None

    def act_resume(self, entry: dict[str, Any], facts: WatchdogFacts, now: float) -> dict[str, Any]:
        """给**停在中途的那个 worker 自己**发一条自解释的消息，并排一次唤醒。

        说清三件事，因为收件人很可能以为"我说完总结就没事了"：它的尝试还没提交；它已经安静
        了多久；在尝试提交之前**只用文字结束回合就等于会话空闲**，所以要么接着做，要么明确
        ``task.submit`` / ``task.block``。
        """

        quiet = int(float(entry.get("quiet_seconds") or 0) // 60)
        task_id = str(entry.get("task_id") or "")
        attempt_id = str(entry.get("attempt_id") or "")
        summary = (
            f"你的任务 {task_id} 还没提交，而这条会话已经安静了 {quiet} 分钟。"
            "如果还在做，忽略这条；如果刚才用一段总结结束了回合 —— 在尝试提交之前，"
            "只用文字回复就等于回合结束（会话空闲，没人会再叫你）。请继续做完，"
            "或者明确 task.submit 交活、task.block 说明卡在哪。"
        )
        with self.database.transaction() as uow:
            message = self.messages.send(
                # 命令 id 用"第几次叫它"而不是时刻：同一秒内重复调用会被幂等去重挡住（那会让
                # 第二次叫喊**静默失败**，异常还被 tick 吞掉）。这样每条都是一次可重放的动作。
                command_id=f"idle-watchdog:resume:{attempt_id}:{self.resume_counts.get(attempt_id, 0) + 1}",
                sender_agent_id="runtime", recipient_agent_id=str(entry.get("agent_id") or ""),
                kind=RESUME_MESSAGE_KIND, subject_ref="task/" + task_id,
                summary=summary,
                payload={"verdict": "resume", "task_id": task_id, "attempt_id": attempt_id,
                         "quiet_seconds": entry.get("quiet_seconds"),
                         "session_state": entry.get("session_state")},
            )
            self._commit(uow, "resume", facts, {"message_id": message.message_id,
                                                "task_id": task_id, "attempt_id": attempt_id,
                                                "recipient_agent_id": message.recipient_agent_id,
                                                "attempt": self.resume_counts.get(attempt_id, 0) + 1})
            self._stage_wake(uow, message)
        self.resumed_at[attempt_id] = now
        self.resume_counts[attempt_id] = self.resume_counts.get(attempt_id, 0) + 1
        return {"verdict": "resume", "message_id": message.message_id, "task_id": task_id,
                "attempt_id": attempt_id, "recipient_agent_id": message.recipient_agent_id,
                "attempt": self.resume_counts[attempt_id], "quiet_seconds": entry.get("quiet_seconds"),
                "session_state": entry.get("session_state")}

    def hand_off(self, entry: dict[str, Any], facts: WatchdogFacts, now: float,
                 *, waiting_on_reply: bool = False) -> dict[str, Any] | None:
        """叫了 ``RESUME_MAX_ATTEMPTS`` 次还不动，或者**它在等一个没人给的答复**：
        交给 main（它是协调者，不是用户）。

        main 能做的事比用户多：催一次、换个人、把任务收回去、或者让它阻塞。所以这条不走
        "待用户决定"，只发一条消息给 main（同样是 wake-worthy ⇒ 它会真的被叫起来）。
        """

        main = facts.main_agent_id
        if not main:
            return None
        attempt_id = str(entry.get("attempt_id") or "")
        if waiting_on_reply:
            summary = (
                f"{entry.get('agent_id')} 的任务 {entry.get('task_id')} 停在半路，而它在等一个"
                "没人给的答复（它问出去的那条消息还挂着未结清的回应义务）—— 协作因此静住了。"
                "请接手：催那个欠答复的人、换人做，或者判定那条依赖不再需要。"
            )
        else:
            summary = (
                f"{entry.get('agent_id')} 的任务 {entry.get('task_id')} 一直没提交，空闲看门狗叫了 "
                f"{self.resume_counts.get(attempt_id, 0)} 次都没有动静。请接手：催一次、换个人做、"
                "把任务收回去，或者让它明确 task.block 说明卡在哪。"
            )
        with self.database.transaction() as uow:
            message = self.messages.send(
                command_id=f"idle-watchdog:handoff:{attempt_id}",
                sender_agent_id="runtime", recipient_agent_id=str(main),
                kind=WAITING_MESSAGE_KIND, subject_ref="task/" + str(entry.get("task_id") or ""),
                summary=summary,
                payload={"verdict": "resume_handoff", "task_id": entry.get("task_id"),
                         "attempt_id": attempt_id, "agent_id": entry.get("agent_id"),
                         "resume_attempts": self.resume_counts.get(attempt_id, 0)},
            )
            self._commit(uow, "resume_handoff", facts,
                         {"message_id": message.message_id, "attempt_id": attempt_id,
                          "agent_id": entry.get("agent_id"),
                          "resume_attempts": self.resume_counts.get(attempt_id, 0)})
            self._stage_wake(uow, message)
        return {"verdict": "resume_handoff", "message_id": message.message_id}

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

        白名单里的种类才排：这条消息的全部意义就是让人动起来。排进 outbox 之后，投递由既有
        的自动通道负责（DSH 那条见 待改 12）；通道不可用时消息仍在收件箱里，控制台的时间线也
        照旧看得到这次判定 —— 看门狗只负责造出那条消息。

        **为什么这里要自己排一次**：``state_runtime.persist`` 会在写入实体变更时给白名单种类
        排 outbox，而看门狗不走 ``persist``（它自己写模块状态与事件，见 ``_commit``）——
        所以这一步是它唯一一次排程。2026-10-10 复测时发现这里原来是**反的**（``not in`` 加
        上 ``return`` 与排程挤在同一行）⇒ 消息落库了、却从来没有被排进 host_wake，等于"叫了
        但没人被叫"。回归测试见 ``test_a_resumed_worker_gets_a_real_wake_row``。
        """

        from tsunagou.modules.messaging import WAKE_WORTHY_KINDS as _wake_worthy

        if message.kind not in _wake_worthy:
            return
        uow.stage_outbox(kind="host_wake", target_ref="message/" + message.message_id, payload={
            "message_id": message.message_id, "recipient_agent_id": message.recipient_agent_id,
        })


async def run_idle_watchdog(watchdog: IdleWatchdog, *, interval_seconds: float = 30.0) -> None:
    """daemon lifespan 里的周期任务。一跳一次，异常不外抛（周期任务不该带着整个 daemon 死）。"""

    while True:
        await asyncio.sleep(interval_seconds)
        watchdog.tick()

