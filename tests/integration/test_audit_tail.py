"""审计出口的**尾巴**取法：`?order=desc` 让"最新活动"一次请求就到手（待改 16 的剩余边界）。

2026-10-08 那次修的是页面**跟游标翻页**（正向走到底），所以事件多到 10 页 × 200 条以上时仍然
取不到真尾巴 —— 正向出口根本没有"从最新往回走"的用法。这里钉住新增的那个用法：

* `order=desc` 第一页就是**最新的一页**（`event_seq` 从大到小），载荷里回显 `order`，
  调用方据此知道自己拿的是尾巴还是开头（老 daemon 不认这个参数时会照旧回升序，页面据此退回翻页）；
* 游标在降序里指"比它更旧的下一段"，与升序共用同一个签名编解码（方向不同的游标互不通用）；
* `order=asc` 的行为一字未变，且仍是默认。
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException
from tests.integration.test_state_integrity import events
from tests.integration.test_state_integrity import runtime as _runtime_fixture

#: 比一页（200）多，正好是"正向翻页取不到尾巴"的量级。
EXTRA_EVENTS = 240


@pytest.fixture(name="runtime")
def audit_runtime(tmp_path, monkeypatch):
    yield from _runtime_fixture.__wrapped__(tmp_path, monkeypatch)


def _history(app: Any, project_id: str, **query: Any) -> dict[str, Any]:
    endpoint = next(route.endpoint for route in app.routes
                    if getattr(route, "path", "") == "/api/v1/projects/{project_id}/history")
    return endpoint(project_id, authorization="Bearer control", session_id=None, connection_epoch=None, **query)


def _fill(app: Any, count: int) -> int:
    """直接往事件库里写，不经过命令 —— 这里要的是条数，不是业务动作。"""

    with app.state.project_database.transaction() as uow:
        for index in range(count):
            uow.append_event(lineage_id="local-lineage", event_type="fixture.event",
                             aggregate_ref="project/fixture", actor_ref="runtime",
                             payload={"index": index})
    return app.state.project_database.last_event_seq()


def test_the_tail_comes_back_in_one_request(runtime) -> None:
    app, call, main, worker = runtime
    newest = _fill(app, EXTRA_EVENTS)
    total = len(events(app))
    assert total > 200, "这一条要的正是'比一页还多'的项目"

    page = _history(app, app.state.project_database.project_id, limit=200, order="desc")
    assert page["order"] == "desc", "方向要回显，调用方才分得清尾巴与开头"
    assert len(page["items"]) == 200
    seqs = [item["event_seq"] for item in page["items"]]
    assert seqs == sorted(seqs, reverse=True), "降序页必须是从新到旧"
    assert seqs[0] == newest, "第一页的第一条就是最新那一条 —— 这就是'尾巴'"
    assert page["next_cursor"], "比一页还多，所以还有更旧的一段"
    assert page["as_of_event_seq"] == newest

    # 继续往回：游标指"更旧的下一段"。
    older = _history(app, app.state.project_database.project_id, limit=200, cursor=page["next_cursor"], order="desc")
    assert older["items"], "降序游标要继续给更旧的事件"
    assert max(item["event_seq"] for item in older["items"]) < min(seqs)


def test_ascending_stays_exactly_as_it_was(runtime) -> None:
    app, call, main, worker = runtime
    _fill(app, EXTRA_EVENTS)

    page = _history(app, app.state.project_database.project_id, limit=50)
    assert page["order"] == "asc"
    seqs = [item["event_seq"] for item in page["items"]]
    assert seqs == sorted(seqs), "默认仍是升序（老调用方一字未变）"
    assert seqs[0] == 1, "升序第一页仍从项目最早那一条开始"


def test_a_cursor_only_works_for_the_direction_it_was_issued_for(runtime) -> None:
    """游标绑定查询上下文（含方向）：拿降序游标去问升序，应当拒绝而不是给一段错的东西。"""

    app, call, main, worker = runtime
    _fill(app, EXTRA_EVENTS)
    project_id = app.state.project_database.project_id
    descending = _history(app, project_id, limit=10, order="desc")

    with pytest.raises(HTTPException) as refusal:
        _history(app, project_id, limit=10, cursor=descending["next_cursor"], order="asc")
    assert refusal.value.detail["code"] == "invalid_audit_cursor"


def test_an_unknown_order_is_refused(runtime) -> None:
    """真正走 HTTP 时路由的枚举先挡（422）；直接调端点也必须是明确的拒绝，不是默默按升序给。"""

    app, call, main, worker = runtime
    with pytest.raises(HTTPException) as refusal:
        _history(app, app.state.project_database.project_id, order="sideways")
    assert refusal.value.detail["code"] == "invalid_audit_order"
