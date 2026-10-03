"""Which project does an Agent join? — the machine answers, not the chat's cwd.

A person asks an Agent to join by saying one sentence *inside* the host. At that moment
the chat knows its own conversation id and working directory, and nothing else; the
coordination root is not derivable from either one, because a project may coordinate
several folders and the console creates projects under its own root. So the console
writes the decision down (one slot per machine: at most one Agent is being enrolled at a
time) and two things read it:

* ``tsunagou agent pending`` — the read-only answer for an Agent that is about to ask the
  user "which project?", and
* DSH connect runtime resolution, which uses that record before cwd discovery.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tsunagou.cli import app as cli
from tsunagou.platform.enrollment_store import EnrollmentStore

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_connect_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    for key in tuple(cli.os.environ):
        if key.startswith(("TSUNAGOU_", "CODEX_", "DSH_")):
            monkeypatch.delenv(key)
    monkeypatch.setenv("TSUNAGOU_ENROLLMENT_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("TSUNAGOU_ROUTING_DIR", str(tmp_path / "routes"))
    selection = cli._selected_project_root.set(None)
    yield
    cli._selected_project_root.reset(selection)


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
    assert answer["enrollment_id"] == record["enrollment_id"]
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


def test_dsh_pending_project_wins_over_the_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """DSH must honor the console selection even inside another project."""

    mine = _project(tmp_path, name="工作区里的项目", project_id="p-mine")
    _record(tmp_path)
    monkeypatch.chdir(mine)
    monkeypatch.setenv("TSUNAGOU_ENROLLMENT_DIR", str(tmp_path / "store"))
    monkeypatch.delenv("TSUNAGOU_PROJECT_ROOT", raising=False)
    cli._selected_project_root.set(None)

    runtime = cli._runtime_for_connect("deepseek")
    assert runtime.project_id == "p-1"
    assert runtime.project_root == _project(tmp_path)


@pytest.mark.parametrize("adapter", ["codex", "opencode"])
def test_other_hosts_keep_existing_cwd_precedence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, adapter: str) -> None:
    mine = _project(tmp_path, "cwd-project", "p-mine")
    _record(tmp_path, adapter=adapter)
    monkeypatch.chdir(mine)
    assert cli._runtime_for_connect(adapter).project_id == "p-mine"


def test_no_pending_dsh_connect_uses_the_nearest_parent_project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = _project(tmp_path)
    child = root / "src" / "nested"
    child.mkdir(parents=True)
    monkeypatch.chdir(child)
    assert cli._runtime_for_connect("deepseek").project_root == root


def test_matching_pending_cwd_and_route_are_valid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from tsunagou.application.onboarding import conversation_key

    record = _record(tmp_path)
    root = Path(record["project_root"])
    monkeypatch.chdir(root)
    monkeypatch.setenv("DSH_SESSION_ID", "fixture-chat")
    route = tmp_path / "routes" / (conversation_key("fixture-chat") + ".json")
    route.parent.mkdir()
    route.write_text(json.dumps({"project_id": "p-1", "project_root": str(root)}), encoding="utf-8")
    before = route.read_bytes()
    assert cli._runtime_for_connect("deepseek").project_id == "p-1"
    assert route.read_bytes() == before


@pytest.mark.parametrize("explicit_kind", ["flag", "environment"])
def test_explicit_selection_conflicting_with_pending_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, explicit_kind: str,
) -> None:
    _record(tmp_path)
    other = _project(tmp_path, "explicit-project", "p-other")
    if explicit_kind == "flag":
        cli._selected_project_root.set(other)
    else:
        monkeypatch.setenv("TSUNAGOU_PROJECT_ROOT", str(other))
    with pytest.raises(RuntimeError, match="^onboarding_project_mismatch$"):
        cli._runtime_for_connect("deepseek")


@pytest.mark.parametrize("manifest", [None, {"project_id": "p-other"}, {}])
def test_missing_or_mismatched_pending_manifest_is_not_a_cwd_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, manifest: dict | None,
) -> None:
    record = _record(tmp_path)
    path = Path(record["project_root"]) / ".tsunagou/project.json"
    if manifest is None:
        path.unlink()
    else:
        path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.chdir(_project(tmp_path, "cwd-project", "p-other"))
    with pytest.raises(RuntimeError, match="^onboarding_project_mismatch$"):
        cli._runtime_for_connect("deepseek")


def test_cli_connect_selects_pending_before_connection_side_effects(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from tsunagou.application import agent_connection

    record = _record(tmp_path)
    monkeypatch.chdir(_project(tmp_path, "cwd-project", "p-other"))
    observed = []

    def connect(operations, **arguments):
        runtime = operations.runtime()
        observed.append((runtime.project_root, runtime.project_id, arguments["role"]))
        return {"status": "enrolled", "project_id": runtime.project_id}

    monkeypatch.setattr(agent_connection, "connect_agent", connect)
    result = runner.invoke(cli.app, ["agent", "connect", "--adapter", "deepseek"])
    assert result.exit_code == 0, result.output
    assert observed == [(Path(record["project_root"]), "p-1", "worker")]
    assert EnrollmentStore().get(record["enrollment_id"])["status"] == "pending"


def test_existing_dsh_route_project_mismatch_is_rejected_before_identity_creation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from tsunagou.application.onboarding import conversation_key

    record = _record(tmp_path)
    other = _project(tmp_path, "already-connected", "p-other")
    monkeypatch.chdir(other)
    monkeypatch.setenv("DSH_SESSION_ID", "fixture-chat")
    route = tmp_path / "routes" / (conversation_key("fixture-chat") + ".json")
    route.parent.mkdir()
    route.write_text(json.dumps({"project_id": "p-other", "project_root": str(other)}), encoding="utf-8")
    before = route.read_bytes()
    result = runner.invoke(cli.app, ["agent", "connect", "--adapter", "deepseek", "--profile", "desktop"])
    assert result.exit_code == 4, result.output
    assert json.loads(result.output)["error"] == "onboarding_project_mismatch"
    assert route.read_bytes() == before
    assert not (Path(record["project_root"]) / ".tsunagou/bridges").exists()
    assert not (other / ".tsunagou/bridges").exists()
    assert EnrollmentStore().get(record["enrollment_id"])["status"] == "pending"


@pytest.mark.parametrize("replace_selection", [False, True])
def test_adapter_pending_snapshot_cancellation_or_replacement_fails_before_connect(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, replace_selection: bool,
) -> None:
    record = _record(tmp_path)
    store = EnrollmentStore()
    store.cancel(record["enrollment_id"])
    if replace_selection:
        store.create(project_id="p-1", project_root=Path(record["project_root"]), role="worker", adapter="deepseek")
    monkeypatch.chdir(_project(tmp_path, "cwd-project", "p-other"))
    result = runner.invoke(cli.app, ["--project-root", record["project_root"], "agent", "connect", "--adapter", "deepseek",
                                     "--pending-enrollment-id", record["enrollment_id"]])
    assert result.exit_code == 4, result.output
    assert json.loads(result.output)["error"] == ("enrollment_selection_changed" if replace_selection else "enrollment_not_pending")
    assert not (Path(record["project_root"]) / ".tsunagou/bridges").exists()


@pytest.mark.parametrize("status", ["claimed", "enrolled"])
def test_non_pending_dsh_record_is_not_selected_for_new_connect(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, status: str,
) -> None:
    record = _record(tmp_path)
    store = EnrollmentStore()
    claimed = store.claim(record["enrollment_id"], "different-chat", expected_revision=record["revision"])
    if status == "enrolled":
        store.mark_enrolled(claimed["enrollment_id"], "different-chat", agent_id="other-agent")
    cwd = _project(tmp_path, "cwd-project", "p-other")
    monkeypatch.chdir(cwd)
    assert cli._runtime_for_connect("deepseek").project_id == "p-other"
    result = runner.invoke(cli.app, ["agent", "connect", "--adapter", "deepseek",
                                     "--pending-enrollment-id", record["enrollment_id"]])
    assert result.exit_code == 4, result.output
    assert json.loads(result.output)["error"] == "enrollment_not_pending"
    assert not (cwd / ".tsunagou/bridges").exists()


def test_invalid_enrollment_store_does_not_fall_back_to_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    store = tmp_path / "store"
    store.mkdir()
    (store / "enrollments.json").write_text("{invalid", encoding="utf-8")
    cwd = _project(tmp_path, "cwd-project", "p-other")
    monkeypatch.chdir(cwd)
    with pytest.raises(RuntimeError):
        cli._runtime_for_connect("deepseek")
    assert not (cwd / ".tsunagou/bridges").exists()


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
