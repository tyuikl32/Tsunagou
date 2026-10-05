"""控制台自己那份记录：daemon 停了之后，屏幕上还剩什么。

这套测试盯的是三件事，它们共同决定这个功能是"方便的存档"还是"会骗人的第二真相"：

* 记的是**搬运过的东西**（同一个出口后一次覆盖前一次，不同出口各自一份）；
* 它是**有界**的（长列表会被截断，超大的整份不存，坏文件读成"没有记录"）；
* 它**永不打断读取**（写不进去、读不出来都只当没有，绝不让一屏本来能看的界面报错）。
"""

from __future__ import annotations

import json
from pathlib import Path

from tsunagou.console.history import MAX_ITEMS, MAX_SOURCES, HistoryStore


def _store(tmp_path: Path) -> HistoryStore:
    return HistoryStore(tmp_path / "console-history")


def test_a_recorded_exit_comes_back_with_when_it_was_seen(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record("p-1", "agents", {"items": [{"agent_id": "a-1"}]}, captured_at="2026-10-03T13:20:00+08:00")

    payload, captured_at = store.payload("p-1", "agents")

    assert payload == {"items": [{"agent_id": "a-1"}]}
    assert captured_at == "2026-10-03T13:20:00+08:00"
    assert store.latest("p-1") == "2026-10-03T13:20:00+08:00"


def test_the_newest_answer_replaces_the_older_one_for_the_same_exit(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record("p-1", "tasks", {"items": [{"task_id": "t-1"}]}, captured_at="2026-10-03T13:00:00+08:00")
    store.record("p-1", "tasks", {"items": [{"task_id": "t-2"}]}, captured_at="2026-10-03T13:05:00+08:00")

    payload, captured_at = store.payload("p-1", "tasks")

    assert payload == {"items": [{"task_id": "t-2"}]}
    assert captured_at == "2026-10-03T13:05:00+08:00"


def test_different_exits_are_kept_apart(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record("p-1", "agents", {"items": []}, captured_at="2026-10-03T13:00:00+08:00")
    store.record("p-1", "checkpoints", {"items": [{"digest": "abc"}]}, captured_at="2026-10-03T13:01:00+08:00")

    assert store.payload("p-1", "agents")[1] == "2026-10-03T13:00:00+08:00"
    assert store.payload("p-1", "checkpoints")[1] == "2026-10-03T13:01:00+08:00"
    assert store.latest("p-1") == "2026-10-03T13:01:00+08:00"
    assert store.summary("p-1") == {"captured_at": "2026-10-03T13:01:00+08:00", "sources": 2}


def test_projects_do_not_mix(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record("p-1", "agents", {"items": [{"agent_id": "a-1"}]}, captured_at="2026-10-03T13:00:00+08:00")
    store.record("p-2", "agents", {"items": [{"agent_id": "a-2"}]}, captured_at="2026-10-03T13:00:00+08:00")

    assert store.payload("p-1", "agents")[0]["items"][0]["agent_id"] == "a-1"
    assert store.payload("p-2", "agents")[0]["items"][0]["agent_id"] == "a-2"


def test_a_long_list_is_trimmed_and_says_so(tmp_path: Path) -> None:
    store = _store(tmp_path)
    rows = [{"task_id": f"t-{index}"} for index in range(MAX_ITEMS + 25)]
    store.record("p-1", "tasks", {"items": rows}, captured_at="2026-10-03T13:00:00+08:00")

    payload, _ = store.payload("p-1", "tasks")

    assert len(payload["items"]) == MAX_ITEMS
    assert payload["items_trimmed"] is True, "被截断这件事要写在记录里，不能悄悄少"


def test_one_huge_answer_is_replaced_by_a_note(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record("p-1", "history", {"items": [{"blob": "x" * 40_000} for _ in range(20)]},
                 captured_at="2026-10-03T13:00:00+08:00")

    payload, _ = store.payload("p-1", "history")

    assert payload["too_large"] is True and payload["bytes"] > 0
    assert "没有留下记录" in payload["note"]


def test_the_number_of_kept_exits_is_bounded(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for index in range(MAX_SOURCES + 5):
        store.record("p-1", f"relay:/api/v1/projects/p-1/thing-{index}", {"items": []},
                     captured_at=f"2026-10-03T13:{index:02d}:00+08:00")

    kept = store.read("p-1")["sources"]

    assert len(kept) == MAX_SOURCES
    assert "relay:/api/v1/projects/p-1/thing-0" not in kept, "先记的（更旧的）被挤出去"
    assert f"relay:/api/v1/projects/p-1/thing-{MAX_SOURCES + 4}" in kept


def test_a_damaged_file_reads_as_nothing_kept(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record("p-1", "agents", {"items": []}, captured_at="2026-10-03T13:00:00+08:00")
    store.path_for("p-1").write_text("{ not json", encoding="utf-8")

    assert store.payload("p-1", "agents") is None
    assert store.latest("p-1") is None
    assert store.summary("p-1") == {"captured_at": None, "sources": 0}


def test_a_wrong_shaped_file_reads_as_nothing_kept(tmp_path: Path) -> None:
    store = _store(tmp_path)
    path = store.path_for("p-1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sources": {"agents": "not-an-object"}}), encoding="utf-8")

    assert store.read("p-1")["sources"] == {}


def test_an_unknown_value_is_kept_as_its_text(tmp_path: Path) -> None:
    """认不出来的值按字符串留个形状：记录只为"还能看出当时是什么"，不追求忠实还原。"""

    store = _store(tmp_path)
    store.record("p-1", "agents", {"items": [object()]}, captured_at="2026-10-03T13:00:00+08:00")

    kept = store.payload("p-1", "agents")

    assert kept is not None
    assert isinstance(kept[0]["items"][0], str)


def test_a_record_that_cannot_be_written_does_not_raise(tmp_path: Path) -> None:
    """记录是"读取的副作用"：写不成只能当没记，绝不能让那一屏本来能看的界面报错。"""

    blocked = tmp_path / "console-history"
    blocked.parent.mkdir(parents=True, exist_ok=True)
    blocked.write_text("这个路径被一个文件占住了", encoding="utf-8")
    store = HistoryStore(blocked)

    store.record("p-1", "agents", {"items": []}, captured_at="2026-10-03T13:00:00+08:00")

    assert store.payload("p-1", "agents") is None


def test_a_missing_project_is_not_a_404(tmp_path: Path) -> None:
    store = _store(tmp_path)

    assert store.payload("never-seen", "agents") is None
    assert store.forget("never-seen") is False


def test_forget_removes_the_record(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record("p-1", "agents", {"items": []}, captured_at="2026-10-03T13:00:00+08:00")

    assert store.forget("p-1") is True
    assert store.payload("p-1", "agents") is None


def test_dropping_one_exit_keeps_the_others_and_recomputes_the_stamp(tmp_path: Path) -> None:
    """控制台自己执行了会改掉某个出口的命令之后，那一份就不能再冒充当前答案。

    实机现场：18:32:30 完工确认成功（随后 daemon 按设计退出），而 decisions 那一份停在
    18:32:27 —— 项目卡片取的是``latest()``（各来源里最新的一个），面板取的是自己那一份，
    于是卡片说"已完成"、面板还在说提案"待处理"。
    """

    store = _store(tmp_path)
    store.record("p-1", "decisions", {"items": [{"proposal_id": "d-1", "status": "pending"}]},
                 captured_at="2026-10-04T18:32:27+08:00")
    store.record("p-1", "overview", {"lifecycle": "active"}, captured_at="2026-10-04T18:32:30+08:00")

    dropped = store.forget_sources("p-1", ("decisions",))

    assert dropped == 1
    assert store.payload("p-1", "decisions") is None
    assert store.payload("p-1", "overview") == ({"lifecycle": "active"}, "2026-10-04T18:32:30+08:00")
    assert store.latest("p-1") == "2026-10-04T18:32:30+08:00", "剩下的那份要重新算时间戳"


def test_dropping_the_last_exit_deletes_the_file(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record("p-1", "decisions", {"items": []}, captured_at="2026-10-04T18:32:27+08:00")

    assert store.forget_sources("p-1", ("decisions",)) == 1
    assert store.forget_sources("p-1", ("decisions",)) == 0, "已经没有了，不是又删了一次"
    assert not store.path_for("p-1").exists()


def test_an_odd_project_id_cannot_escape_the_directory(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record("../../etc/passwd", "agents", {"items": []}, captured_at="2026-10-03T13:00:00+08:00")

    written = list((tmp_path / "console-history").glob("*.json"))

    assert len(written) == 1
    assert written[0].parent == tmp_path / "console-history"


def test_the_store_sits_beside_the_index(tmp_path: Path) -> None:
    """没有新的配置项：记录跟着机器级索引走，测试把索引指到临时目录就自动隔离。"""

    store = HistoryStore.beside_index(tmp_path / "home" / ".tsunagou" / "projects.json")

    assert store.directory == tmp_path / "home" / ".tsunagou" / "console-history"
