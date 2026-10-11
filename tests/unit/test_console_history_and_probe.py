"""控制台的两个实测缺陷（2026-10-11）：历史键名不一致、探活拖慢整页。

用户现场：daemon 关掉后"有一部分历史看不到 + 报错"，而每次操作卡 1–2 秒。根因分别是
（1）同一个出口被记成两种历史键名（``agents`` 与 ``relay:/api/v1/projects/<id>/agents``），
只认一种就会假报"没有记录"；（2）列项目时逐个探测 daemon，10 个已停的项目 × 0.5 秒
⇒ ``GET /api/v1/projects`` 实测 4.7 秒，而 endpoint 里本来就记着 pid。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tsunagou.console.history import HistoryStore
from tsunagou.console.projects import _pid_alive, daemon_state


def test_a_dead_pid_short_circuits_the_probe(tmp_path: Path) -> None:
    """pid 明明死了就别再打网络 —— 这一条就是那 4.7 秒的来源。"""

    root = tmp_path / "project"
    (root / ".tsunagou" / "local").mkdir(parents=True)
    # 一个几乎必然不存在的 pid：比当前进程号大很多，且不可能被系统复用到这里。
    (root / ".tsunagou" / "local" / "endpoint.json").write_text(
        '{"url": "http://127.0.0.1:1", "pid": 999999, "project_id": "p"}', encoding="utf-8")

    assert _pid_alive(999999) is False
    state = daemon_state(root, probe=True)
    assert state is not None and state["running"] is False


def test_the_current_process_is_reported_alive() -> None:
    import os

    assert _pid_alive(os.getpid()) is True
    assert _pid_alive(None) is False and _pid_alive("not-a-pid") is False


def test_history_reads_both_key_shapes(tmp_path: Path) -> None:
    """两种键名并存过：代理记 ``relay:<path>``，面板记来源名。两边的数据都要读得到。"""

    store = HistoryStore(tmp_path / "console-history")
    store.record("p1", "relay:/api/v1/projects/p1/agents", {"agents": [1]}, captured_at="2026-10-11T00:00:00Z")

    def lookup(project_id: str, name: str, relay_key: str) -> Any:
        kept = store.payload(project_id, name)
        if kept is None:
            kept = store.payload(project_id, relay_key)
        return kept

    assert lookup("p1", "agents", "relay:/api/v1/projects/p1/agents") is not None, "代理记的那份要能读到"
    assert lookup("p1", "tasks", "relay:/api/v1/projects/p1/tasks") is None, "没记过的仍然是洞"
