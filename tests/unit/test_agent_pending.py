"""Which project does an Agent join? — the machine answers, not the chat's cwd.

A person asks an Agent to join by saying one sentence *inside* the host. At that moment
the chat knows its own conversation id and working directory, and nothing else; the
coordination root is not derivable from either one, because a project may coordinate
several folders and the console creates projects under its own root. So the console
writes the decision down (one slot per machine: at most one Agent is being enrolled at a
time) and two things read it:

* ``tsunagou agent pending`` — the read-only answer for an Agent that is about to ask the
  user "which project?", and
* the connect path's runtime resolution — which falls back to that record only when the
  working directory does not already name a project.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tsunagou.cli import app as cli
from tsunagou.platform.enrollment_store import EnrollmentStore

runner = CliRunner()


def _project(tmp_path: Path, name: str = "协调仓库", project_id: str = "p-1") -> Path:
    root = tmp_path / name
    (root / ".tsunagou" / "local").mkdir(parents=True, exist_ok=True)
    (root / ".tsunagou" / "project.json").write_text(
        json.dumps({"project_id": project_id, "name": name}), encoding="utf-8",
    )
    return root


def _record(tmp_path: Path, *, adapter: str = "deepseek", root: str = "协调仓库", role: str = "worker") -> dict:
    return EnrollmentStore(tmp_path / "store").create(
        project_id="p-1", project_root=_project(tmp_path, root), role=role, adapter=adapter,
    )


def _pending(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *arguments: str) -> dict:
    monkeypatch.setenv("TSUNAGOU_ENROLLMENT_DIR", str(tmp_path / "store"))
    result = runner.invoke(cli.app, ["agent", "pending", *arguments])
    assert result.exit_code == 0, result.output
    return json.loads(result.output.strip().splitlines()[-1])


def test_without_a_record_the_answer_is_none_and_says_where_to_go(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """没有申请时不要猜、也不要自己建项目：接入是用户的决定。"""

    answer = _pending(monkeypatch, tmp_path)
    assert answer["status"] == "none"
    assert "控制台" in answer["note"]


def test_the_pending_record_carries_root_role_and_nickname(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("TSUNAGOU_ENROLLMENT_DIR", str(tmp_path / "store"))
    record = EnrollmentStore().create(
        project_id="p-1", project_root=_project(tmp_path), role="main", nickname="熊猫", adapter="deepseek",
    )

    answer = _pending(monkeypatch, tmp_path, "--adapter", "deepseek")
    assert answer["status"] == "pending"
    assert answer["state"] == "pending"
    assert answer["role"] == "main" and answer["nickname"] == "熊猫"
    assert Path(answer["project_root"]) == _project(tmp_path)
    assert answer["project_id"] == record["project_id"]
    # 别的宿主来问，拿不到这条（给 Codex 的申请不能交给 DeepSeek 的聊天）
    assert _pending(monkeypatch, tmp_path, "--adapter", "opencode")["status"] == "none"


def test_connect_resolves_the_project_from_the_record_when_cwd_has_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """聊天的工作目录不是协调仓库时，那条记录才是答案（DSH 的 tsunagou_connect 走这里）。"""

    root = _project(tmp_path)
    _record(tmp_path)
    elsewhere = tmp_path / "业务工作区"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("TSUNAGOU_ENROLLMENT_DIR", str(tmp_path / "store"))
    monkeypatch.delenv("TSUNAGOU_PROJECT_ROOT", raising=False)
    cli._selected_project_root.set(None)

    runtime = cli._runtime_for_connect("deepseek")
    assert runtime.project_root == root
    assert runtime.project_id == "p-1"


def test_the_working_directory_still_wins_over_the_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """工作目录里真有项目就用它：记录是"推不出来时"的兜底，不是覆盖。"""

    mine = _project(tmp_path, name="工作区里的项目", project_id="p-mine")
    _record(tmp_path)
    monkeypatch.chdir(mine)
    monkeypatch.setenv("TSUNAGOU_ENROLLMENT_DIR", str(tmp_path / "store"))
    monkeypatch.delenv("TSUNAGOU_PROJECT_ROOT", raising=False)
    cli._selected_project_root.set(None)

    runtime = cli._runtime_for_connect("deepseek")
    assert runtime.project_id == "p-mine"


def test_another_hosts_record_is_not_used_for_this_connect(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """记录属于某个宿主：给 Codex 的申请不能让 DeepSeek 的聊天去接。"""

    _record(tmp_path, adapter="codex")
    elsewhere = tmp_path / "业务工作区"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("TSUNAGOU_ENROLLMENT_DIR", str(tmp_path / "store"))
    monkeypatch.delenv("TSUNAGOU_PROJECT_ROOT", raising=False)
    cli._selected_project_root.set(None)

    runtime = cli._runtime_for_connect("deepseek")
    assert runtime.project_id is None
    assert runtime.project_root == elsewhere


def test_the_record_decides_the_role_and_a_conflicting_request_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """页面上选主 Agent，那条聊天就只能以主 Agent 接入 —— 它说什么都不算数。"""

    monkeypatch.setenv("TSUNAGOU_ENROLLMENT_DIR", str(tmp_path / "store"))
    EnrollmentStore().create(
        project_id="p-1", project_root=_project(tmp_path), role="main", adapter="deepseek",
    )

    assert cli._role_for_connect("deepseek", None) == "main"
    assert cli._role_for_connect("deepseek", "main") == "main"
    with pytest.raises(RuntimeError, match="^enrollment_role_conflict$"):
        cli._role_for_connect("deepseek", "worker")
    # 别的宿主不受这条记录影响；没有记录时回到"显式指定 / 宿主默认"。
    assert cli._role_for_connect("opencode", "worker") == "worker"
    assert cli._role_for_connect("opencode", None) is None


def test_a_conflicting_role_is_refused_before_any_bridge_material_is_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """冲突要在动任何东西之前就拒绝 —— 连 `.tsunagou/bridges` 都不该出现。"""

    monkeypatch.setenv("TSUNAGOU_ENROLLMENT_DIR", str(tmp_path / "store"))
    EnrollmentStore().create(
        project_id="p-1", project_root=_project(tmp_path), role="main", adapter="deepseek",
    )
    elsewhere = tmp_path / "业务工作区"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("DSH_SESSION_ID", "probe-session")
    monkeypatch.delenv("TSUNAGOU_PROJECT_ROOT", raising=False)
    cli._selected_project_root.set(None)

    result = runner.invoke(cli.app, ["agent", "connect", "--adapter", "deepseek", "--role", "worker"])

    assert result.exit_code == 4, result.output
    assert "enrollment_role_conflict" in result.output
    assert not (elsewhere / ".tsunagou").exists()
