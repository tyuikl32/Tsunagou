"""「那台机器还在不在」：心跳只记在内存里，判据要既准又稳。

测试盯住三件事：会话不是 ready 就不算在线；**从未上报过也按离线算**（没有证据就是没有
证据 —— 用户 2026-10-04 定的口径，远端机器关着时页面立刻显示离线）；上报过就按时间判，
超过窗口没再来过就翻离线。
"""

from __future__ import annotations

from tsunagou.api.liveness import SessionLiveness


def test_a_session_that_never_reported_counts_as_offline() -> None:
    """没有证据就是没有证据：从未上报过按离线算。

    这样远端机器关着的时候，页面立刻显示离线，不用等它的桥装上心跳。
    """

    liveness = SessionLiveness()

    assert liveness.online("s-1", "ready") is False
    assert liveness.online("s-1", "degraded") is False
    assert liveness.online("s-1", "ended") is False
    assert liveness.online("s-1", "inactive") is False


def test_a_session_that_stops_reporting_falls_off_after_the_ttl() -> None:
    """拔掉电源：最后一次心跳之后过了 TTL，就不算在线 —— 徽标才会真的翻。"""

    liveness = SessionLiveness(ttl_seconds=90)
    liveness.seen("s-1", at_ms=1_000_000)

    assert liveness.online("s-1", "ready", now_ms=1_000_000) is True
    assert liveness.online("s-1", "ready", now_ms=1_090_000) is True    # 正好卡在阈值上
    assert liveness.online("s-1", "ready", now_ms=1_090_001) is False
    assert liveness.online("s-1", "ready", now_ms=9_999_999) is False


def test_every_report_refreshes_the_same_session() -> None:
    """桥每隔一会儿报一次：后一次覆盖前一次，不会越攒越多。"""

    liveness = SessionLiveness(ttl_seconds=90)
    liveness.seen("s-1", at_ms=1_000_000)
    liveness.seen("s-1", at_ms=1_080_000)

    assert liveness.online("s-1", "ready", now_ms=1_120_000) is True
    assert len(liveness._seen) == 1  # noqa: SLF001 - 这条测试盯的就是"同一个键被刷新"


def test_reports_without_a_session_are_ignored() -> None:
    """用户面/票据面的调用没有会话可记 —— 不能因此凭空造出一条记录。"""

    liveness = SessionLiveness()

    liveness.seen(None)
    liveness.seen("   ")

    assert liveness._seen == {}  # noqa: SLF001


def test_forgetting_a_session_drops_it() -> None:
    liveness = SessionLiveness()
    liveness.seen("s-1", at_ms=1_000_000)

    liveness.forget("s-1")

    assert liveness.online("s-1", "ready", now_ms=9_999_999) is False, "忘了就是没有证据 → 离线"


def test_the_agents_exit_reports_both_status_and_online() -> None:
    """agents 出口那两件事一起算：会话状态 + 机器在不在（页面就靠它们画徽标）。"""

    from types import SimpleNamespace

    from tsunagou.bootstrap.container import _agent_liveness

    session = SimpleNamespace(session_id="s-1", agent_id="a-1", status="ready", active=True)
    authority = SimpleNamespace(sessions={"s-1": session})

    fresh = SessionLiveness(ttl_seconds=90)
    fresh.seen("s-1")            # 刚刚报过（默认就是"现在"）
    assert _agent_liveness(authority, fresh, "a-1") == {"session_status": "ready", "online": True}

    # 心跳停了：同一个会话、同一个出口，但 online 已经翻了。
    assert _agent_liveness(authority, SessionLiveness(), "a-1") == {
        "session_status": "ready", "online": False}   # 从未上报过 → 离线
    stale = SessionLiveness(ttl_seconds=1)
    stale.seen("s-1", at_ms=1_000_000)               # 很久以前报过一次
    assert _agent_liveness(authority, stale, "a-1")["online"] is False

    # 没有活着的会话时：状态 inactive，且不算在线。
    assert _agent_liveness(SimpleNamespace(sessions={}), fresh, "a-1") == {
        "session_status": "inactive", "online": False}

