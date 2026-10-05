"""谁最近还活着 —— 只记在内存里，不落库、不写审计。

桥按固定间隔做一次便宜的已认证读取（见 `packages/bridge-server`），那些调用本身就是
"我还在"的证明。这里只记下**最近一次见到某个会话的时刻**，据此回答 agents 出口里的
``online``。

它故意**不进领域状态**：心跳不是业务事实，没有版本、没有审计价值；重启之后为空也照样能用
—— 只是那一小段时间里"没有证据"就等于离线（见 ``online``），各桥会在一个间隔内补上。
"""

from __future__ import annotations

import time

#: 桥的上报间隔是 30 秒；连续三次没来才算走开，避免抖一下就翻成离线。
DEFAULT_TTL_SECONDS = 90.0


class SessionLiveness:
    """``session_id -> 最近一次见到的时刻（毫秒）``，外加"现在算不算在线"的判据。"""

    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> None:
        self.ttl_ms = int(max(float(ttl_seconds), 0.0) * 1000)
        self._seen: dict[str, int] = {}

    def seen(self, session_id: str | None, *, at_ms: int | None = None) -> None:
        """一次已认证的会话调用。没有会话的调用（用户面、票据面）没得记，直接返回。"""

        token = str(session_id or "").strip()
        if not token:
            return
        self._seen[token] = int(at_ms if at_ms is not None else time.time() * 1000)

    def online(self, session_id: str | None, status: str, *, now_ms: int | None = None) -> bool:
        """这条会话现在算不算"那台机器还在"。

        两件事都要成立，缺一不算在线：

        1. 会话自己是 ``ready`` —— 会话都干不了活了，机器在不在都没意义；
        2. **最近真的上报过**（时间在 ``ttl_ms`` 之内）。

        「从未上报过」按**离线**算（用户 2026-10-04 定的口径）：没有证据就是没有证据，
        宁可保守，也不写一句没依据的"在线" —— 远端机器关着的时候页面立刻就该显示离线，
        而不是等它的桥装上心跳。代价写在这里，免得以后有人意外：daemon 重启后内存表是空的，
        到各桥第一次上报之间（≤ 一个间隔，默认 30 秒）会短暂显示离线。
        """

        if str(status or "") != "ready":
            return False
        token = str(session_id or "").strip()
        last = self._seen.get(token) if token else None
        if last is None:
            return False
        now = int(now_ms if now_ms is not None else time.time() * 1000)
        return (now - last) <= self.ttl_ms

    def forget(self, session_id: str | None) -> None:
        """会话结束/退役时把那一条抹掉（内存不涨、也不留旧时刻误导下一次判据）。"""

        token = str(session_id or "").strip()
        if token:
            self._seen.pop(token, None)
