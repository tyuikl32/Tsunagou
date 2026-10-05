"""Discovery and creation of projects, without a daemon in the picture."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tsunagou.console.config import ConsoleConfig
from tsunagou.console.errors import ConsoleError
from tsunagou.console.projects import bridge_profiles, create, discover, forget, register, stop_daemon
from tsunagou.modules.projects import PENDING_OBJECTIVE, ProjectRegistry
from tsunagou.platform import host_registration
from tsunagou.platform.project_index import load_index, record_project


def _config(tmp_path: Path) -> ConsoleConfig:
    return ConsoleConfig(
        projects_root=tmp_path / "projects",
        scan_roots=[tmp_path],
        index_path=tmp_path / "index.json",
        profile_path=tmp_path / "profile.json",
    )


def _existing_project(tmp_path: Path, name: str = "scan") -> Path:
    root = tmp_path / name
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    ProjectRegistry.initialize(root, name=name, objective="scan me")
    return root


def test_discovery_reads_the_projects_manifest_not_the_index(tmp_path: Path) -> None:
    config = _config(tmp_path)
    root = _existing_project(tmp_path)
    # The index is a hint: its name is stale, and it also remembers a project whose
    # folder is gone. The manifest wins, and the ghost is reported, not hidden.
    record_project(project_id="ghost", path=tmp_path / "gone", name="Gone", index=config.index_path)

    entries = {entry.project_id: entry for entry in discover(config, probe=False)}

    manifest = json.loads((root / ".tsunagou" / "project.json").read_text(encoding="utf-8"))
    assert entries[manifest["project_id"]].name == "scan"
    assert entries[manifest["project_id"]].available is True
    assert entries[manifest["project_id"]].path == root.resolve()
    assert entries["ghost"].available is False
    assert entries["ghost"].daemon is None


def test_a_project_without_a_running_daemon_is_available_but_not_started(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _existing_project(tmp_path)
    (entry,) = discover(config, probe=True)
    assert entry.available is True
    assert entry.daemon is None


def test_creating_a_project_makes_a_repository_and_registers_it(tmp_path: Path) -> None:
    config = _config(tmp_path)
    entry = create(config, name="用户服务重构", objective="让两个 Agent 对齐")

    assert entry.path.parent == config.projects_root
    assert entry.path.name == "用户服务重构"
    assert (entry.path / ".git").exists()
    assert (entry.path / ".tsunagou" / "project.json").is_file()
    stored = json.loads(config.index_path.read_text(encoding="utf-8"))["projects"]
    assert [item["project_id"] for item in stored] == [entry.project_id]
    assert stored[0]["sources"] == ["console"]
    assert stored[0]["objective"] == "让两个 Agent 对齐"


def test_a_project_created_without_a_goal_holds_the_placeholder(tmp_path: Path) -> None:
    """没有目标时写占位，不拿项目名冒充目标。

    目标是用户与主 Agent 谈完、用户确认过之后才存在的事实（见
    docs/decisions/2026-10-01-objective-from-dialogue.md）；建项目时那句
    "objective or name" 会让人读到一个看起来像目标、其实只是名字的句子。
    """

    config = _config(tmp_path)
    entry = create(config, name="没有目标")

    assert entry.objective == PENDING_OBJECTIVE
    assert PENDING_OBJECTIVE != "没有目标"
    manifest = json.loads((entry.path / ".tsunagou" / "project.json").read_text(encoding="utf-8"))
    assert manifest["objective"] == PENDING_OBJECTIVE
    stored = json.loads(config.index_path.read_text(encoding="utf-8"))["projects"]
    assert stored[0]["objective"] == PENDING_OBJECTIVE


def test_a_created_project_carries_its_agent_facing_entry_files(tmp_path: Path) -> None:
    """建完就要有 Agent 侧的入口。

    控制台建的项目**马上**会被拿去请一个宿主会话接入；而那个 Agent 的第一条指令是
    "存在就读 .tsunagou/agent-context.md 与 AGENTS.md 受管区块"。不存在它不会报错，
    只会没有任何线索，然后照自己的说明去别处 `project init` —— 真实发生过。
    """

    config = _config(tmp_path)
    entry = create(config, name="带入口")

    assert entry.bootstrap is not None
    assert entry.bootstrap["status"] == "bootstrapped", entry.bootstrap
    for relative in (
        "AGENTS.md",
        ".tsunagou/agent-context.md",
        ".tsunagou/project-integration.json",
        ".agents/skills/tsunagou-project/SKILL.md",
    ):
        assert (entry.path / relative).is_file(), relative
    # 本机私有目录要被受管区块挡在 Git 外面。
    assert ".tsunagou/local/" in (entry.path / ".gitignore").read_text(encoding="utf-8")
    # 只写 host-neutral 入口：接入时中间层会自己把 bridge 注册进宿主的配置。
    assert not (entry.path / ".codex" / "config.toml").exists()
    # 路由把这份报告原样交给页面（`_woken` 返回的就是 public()），所以这里断言序列化结果。
    assert entry.public()["bootstrap"]["status"] == "bootstrapped"


def test_registering_a_project_leaves_its_own_files_alone(tmp_path: Path) -> None:
    """登记一个已经存在的项目不动它的文件：那些文件属于把项目放这儿的人。"""

    config = _config(tmp_path)
    root = _existing_project(tmp_path, "registered")

    entry = register(config, path=root)

    assert entry.bootstrap is None
    assert "bootstrap" not in entry.public()
    assert not (root / "AGENTS.md").exists()
    assert not (root / ".tsunagou" / "agent-context.md").exists()


def test_two_projects_with_the_same_name_do_not_collide(tmp_path: Path) -> None:
    config = _config(tmp_path)
    first = create(config, name="same name")
    second = create(config, name="same name")
    assert first.path.name == "same-name"
    assert second.path.name == "same-name-2"
    assert first.project_id != second.project_id


def test_registering_a_folder_that_holds_no_project_is_refused(tmp_path: Path) -> None:
    config = _config(tmp_path)
    (tmp_path / "not-a-project").mkdir()
    with pytest.raises(ConsoleError) as refusal:
        register(config, path=tmp_path / "not-a-project")
    assert refusal.value.code == "project_not_found_at_path"


def test_registering_an_existing_project_only_adds_it_to_the_index(tmp_path: Path) -> None:
    config = _config(tmp_path)
    root = _existing_project(tmp_path, "already-there")
    entry = register(config, path=root)
    assert entry.available is True
    stored = json.loads(config.index_path.read_text(encoding="utf-8"))["projects"]
    assert [item["project_id"] for item in stored] == [entry.project_id]


def test_creating_refuses_when_git_cannot_initialise_the_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(tmp_path)

    def no_git(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=128, stdout="", stderr="git not available")

    monkeypatch.setattr(subprocess, "run", no_git)
    with pytest.raises(ConsoleError) as refusal:
        create(config, name="doomed")
    assert refusal.value.code == "git_initialization_failed"
    assert "git not available" in refusal.value.detail["stderr"]


# ---- 一次性删掉整个项目（没有分步后撤，就这一个动作）------------------------


def _own_project(tmp_path: Path, name: str = "mine") -> tuple[ConsoleConfig, Path, str]:
    """A project the console itself created — i.e. one inside ``projects_root``."""

    config = _config(tmp_path)
    config.projects_root.mkdir(parents=True, exist_ok=True)
    root = _existing_project(config.projects_root, name)
    entry = register(config, path=root)
    return config, root, entry.project_id


def test_deleting_an_unknown_project_is_a_clean_404(tmp_path: Path) -> None:
    with pytest.raises(ConsoleError) as refusal:
        forget(_config(tmp_path), "nope")

    assert refusal.value.code == "project_not_found"
    assert refusal.value.status == 404


def test_forgetting_a_project_drops_its_index_line_and_its_folder(tmp_path: Path) -> None:
    config, root, project_id = _own_project(tmp_path)

    report = forget(config, project_id, delete_files=True)

    assert report["status"] == "forgotten"
    assert report["files"]["deleted"] is True
    assert not root.exists(), "控制台自己建的项目，说删就该真删"
    assert [item for item in load_index(config.index_path)["projects"] if item["path"] == root.as_posix()] == []


def test_forgetting_a_project_removes_read_only_files_too(tmp_path: Path) -> None:
    """Windows 上 git 把 ``.git/objects`` 下的对象设成只读，删项目不能因此半途而废。

    真实现场（2026-10-04 实机测试）：``POST /api/v1/console/projects/{id}:forget`` 在
    ``rmtree`` 上抛 ``PermissionError: [WinError 5]``，而它此前已经停了 daemon ——
    结果是"daemon 没了、文件一个没删、索引还在"，页面随后满屏 503。
    """

    config, root, project_id = _own_project(tmp_path)
    objects = root / ".git" / "objects" / "13"
    objects.mkdir(parents=True)
    read_only = objects / "243ab4e07786cb1dc7b3cb256ed4a7c1377065"
    read_only.write_text("git object", encoding="utf-8")
    read_only.chmod(0o444)  # 在 Windows 上就是"只读"

    report = forget(config, project_id, delete_files=True)

    assert report["status"] == "forgotten"
    assert report["files"]["deleted"] is True
    assert not root.exists(), "一个只读文件不该让整个项目删不掉"


def test_a_registered_project_outside_projects_root_keeps_its_files(tmp_path: Path) -> None:
    config = _config(tmp_path)
    outside = _existing_project(tmp_path, "somebody-elses")
    entry = register(config, path=outside)

    report = forget(config, entry.project_id, delete_files=True)

    assert report["files"]["deleted"] is False
    assert "projects_root" in report["files"]["reason"]
    assert outside.exists(), "别人放在这儿的项目，不能连目录一起删"


def test_forgetting_takes_the_bridge_registrations_back_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, root, project_id = _own_project(tmp_path)
    bridge = root / ".tsunagou" / "bridges" / "codex-main"
    bridge.mkdir(parents=True)
    (bridge / "bridge.json").write_text(json.dumps({"adapter": "codex"}), encoding="utf-8")
    asked: list[tuple[str, str]] = []
    scopes: list[bool] = []

    def fake_unregister(
        adapter: str, *, profile: str, project_root: Path, all_registrations: bool = False,
        run: object = None,
    ) -> host_registration.Registration:
        asked.append((adapter, profile))
        scopes.append(all_registrations)
        return host_registration.Registration(
            adapter=adapter, label=adapter, status="unregistered", name=f"tsunagou-{profile}",
        )

    monkeypatch.setattr(host_registration, "unregister", fake_unregister)

    report = forget(config, project_id)

    assert asked == [("codex", "main")], "每个 bridge 目录都要注销一次，profile 不能被拆错"
    # Forgetting a project is the whole-project request, not one enrollment: without it a
    # project holding two conversations answered ambiguous and kept every overlay.
    assert scopes == [True], "forget 必须以整项目范围注销"
    assert report["host_registrations"][0]["status"] == "unregistered"


def test_bridge_profiles_reads_the_adapter_from_the_config(tmp_path: Path) -> None:
    root = tmp_path / "p"
    bridge = root / ".tsunagou" / "bridges" / "codex-main-1a2b"
    bridge.mkdir(parents=True)
    (bridge / "bridge.json").write_text(json.dumps({"adapter": "codex"}), encoding="utf-8")

    assert bridge_profiles(root) == [("codex", "main-1a2b")]


def test_stopping_a_daemon_that_is_not_running_is_not_an_error(tmp_path: Path) -> None:
    assert stop_daemon(tmp_path) == {"status": "not_running"}


def test_stopping_a_live_daemon_kills_the_pid_from_the_endpoint_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = tmp_path / ".tsunagou" / "local"
    state.mkdir(parents=True)
    (state / "endpoint.json").write_text(
        json.dumps({"url": "http://127.0.0.1:1", "pid": 4242}), encoding="utf-8",
    )
    monkeypatch.setattr("tsunagou.console.projects.daemon_alive", lambda url: True)
    killed: list[int] = []

    report = stop_daemon(tmp_path, kill=killed.append)

    assert report["status"] == "stopped"
    assert killed == [4242]
