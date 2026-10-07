"""任务声明的路径必须指向**已登记**的根。

2026-10-07 实测：主 Agent 给任务写了 `root_id: "workspace"`，而这个协作 `roots` 为空 ——
悬空引用被静默存下，直到 `task.begin`/workspace 准备那一刻才炸，报的还是
`root_binding_required`（指不出真因"这个根根本不存在"）。这里把它提前到建任务那一刻。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException, Response

from tsunagou.api.app import CommandRequest, create_app
from tsunagou.api.auth import LocalCommandAuthenticator
from tsunagou.application.handlers import build_handlers
from tsunagou.interfaces.runtime import CommandDispatcher
from tsunagou.modules.authority import AuthorityService
from tsunagou.modules.projects import ProjectRegistry
from tsunagou.shared_kernel.baseline import BASELINE_CAPABILITIES

ROOT = Path(__file__).parents[2]


def _baseline() -> dict[str, Any]:
    return {"baseline": {name: {"status": "supported", "evidence_refs": [f"fixture:{name}"]}
                         for name in BASELINE_CAPABILITIES}}


def _main_token(tmp_path: Path) -> tuple[Any, str, dict[str, Any]]:
    """一个装了项目的应用，加一个已任命的主 Agent 的凭据。"""

    # 协调仓库必须是 git 仓库（与其它集成测试同样的前提）。
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    ProjectRegistry.initialize(tmp_path, name="roots", objective="scope roots")
    registry = ProjectRegistry(tmp_path)
    dispatcher = CommandDispatcher(ROOT / "protocol" / "registry" / "commands.json")
    authority = AuthorityService(tmp_path / "identity.json")
    for kind, handler in build_handlers(authority=authority, project_registry=registry).items():
        dispatcher.register(kind, handler)
    app = create_app(dispatcher, authenticator=LocalCommandAuthenticator(
        authority=authority, control_token="ctl"))
    endpoint = next(route.endpoint for route in app.routes
                    if getattr(route, "path", "") == "/api/v1/commands/{command_kind}")

    def request(payload: dict[str, Any]) -> CommandRequest:
        return CommandRequest(command_id="c", protocol_version="1",
                              schema_bundle_digest="sha256:x", payload=payload)

    enrolled = endpoint(
        "agent.enroll",
        request({"installation_id": "install-a",
                 "conversation_evidence": {"conversation_id": "conversation-a"},
                 "probe_payload": _baseline()}),
        Response(), f"Bearer {authority.issue_ticket('install-a', 'conversation-a')}", None, None,
    )["result"]
    endpoint("authority.appoint", request({"agent_id": enrolled["agent_id"]}), Response(),
             "Bearer ctl", None, None)
    return (lambda kind, payload: endpoint(kind, request(payload), Response(),
                                           f"Bearer {enrolled['secret_token']}",
                                           enrolled["session_id"], enrolled["connection_epoch"])["result"],
            "ctl", {"registry": registry, "path": tmp_path})


SCOPE = {"resources": [{"kind": "path", "root_id": "workspace",
                        "segments": ["library-site", "server"], "mode": "exclusive_write"}]}


def test_a_scope_naming_an_unregistered_root_is_refused(tmp_path: Path) -> None:
    call, _token, _ = _main_token(tmp_path)

    with pytest.raises(Exception, match="unknown_root_id:workspace"):
        call("task.create", {"title": "t", "objective": "o", "execution_scope": SCOPE})


def test_the_same_scope_is_accepted_once_the_root_is_registered(tmp_path: Path) -> None:
    call, _token, fixture = _main_token(tmp_path)
    # register_root **返回生成的 root_id**（不是拿 name 当 id）：scope 里必须用返回的那个值。
    root_id = fixture["registry"].register_root("workspace", fixture["path"], root_kind="directory")
    scope = {"resources": [{"kind": "path", "root_id": root_id,
                            "segments": ["library-site", "server"], "mode": "exclusive_write"}]}

    created = call("task.create", {"title": "t", "objective": "o", "execution_scope": scope})

    assert created["status"] == "draft"


def test_a_binding_at_a_missing_path_is_not_called_bound(tmp_path: Path) -> None:
    """"已绑定"必须可信：路径不在（或该是目录却是文件）时不许记成 bound。

    2026-10-07 实测：给一个不存在的目录，`register_root` 照样把状态记成 `bound` —— 于是"根绑好了"
    这个前提是假的。**不拒绝**这种登记（目录被移走是有意义的状态，控制台要能显示"未绑定"），
    但要如实标出状态。
    """

    _call, _token, fixture = _main_token(tmp_path)

    missing = fixture["registry"].register_root("gone", fixture["path"] / "not-there")
    assert fixture["registry"].local_bindings[missing]["status"] == "missing"

    (fixture["path"] / "a-file").write_text("x\n", encoding="utf-8")
    wrong_type = fixture["registry"].register_root("file", fixture["path"] / "a-file")
    assert fixture["registry"].local_bindings[wrong_type]["status"] == "not_a_directory"

    ok = fixture["registry"].register_root("here", fixture["path"])
    assert fixture["registry"].local_bindings[ok]["status"] == "bound"


def test_a_declared_file_task_cannot_be_created_without_a_scope(tmp_path: Path) -> None:
    """声明了 `requires_files: true` 的文件任务，不能发成空 scope。

    这是用户那条规矩的完全机械版：A1/A4 把空 scope 的**含义**说清了（不做文件改动），
    这里再进一步 —— 主 Agent **自己声明**这活要改文件时，空 scope 直接拒绝，
    不给"发了才发现做不成"的机会。
    """

    call, _token, _fixture = _main_token(tmp_path)

    with pytest.raises(HTTPException) as refusal:
        call("task.create", {"title": "t", "objective": "o",
                             "execution_scope": {}, "requires_files": True})

    assert refusal.value.detail["code"] == "file_task_requires_scope"


def test_declaring_a_file_task_is_fine_once_it_names_paths(tmp_path: Path) -> None:
    call, _token, fixture = _main_token(tmp_path)
    root_id = fixture["registry"].register_root("workspace", fixture["path"], root_kind="directory")
    scope = {"resources": [{"kind": "path", "root_id": root_id,
                            "segments": ["server"], "mode": "exclusive_write"}]}

    created = call("task.create", {"title": "t", "objective": "o",
                                   "execution_scope": scope, "requires_files": True})

    assert created["status"] == "draft"
    assert "next" not in created, "有范围的声明不该再挂空 scope 的提示"


def test_an_empty_scope_is_never_checked_against_roots(tmp_path: Path) -> None:
    call, _token, _ = _main_token(tmp_path)

    created = call("task.create", {"title": "t", "objective": "o", "execution_scope": {}})

    assert created["status"] == "draft"


def test_registering_a_repository_on_an_unbound_root_names_the_root(tmp_path: Path) -> None:
    """拒绝要说清是**哪个根**没绑、以及它到底登记没有 —— 否则人只看到"需要绑定"。"""

    call, _token, fixture = _main_token(tmp_path)
    root_id = fixture["registry"].register_root("workspace", fixture["path"], root_kind="directory")
    # 公开接口目前总把 register_root 记成 bound，所以"登记了但没绑"这个状态在这里直接摆出来
    # —— 它不是臆造：绑定请求可能没被满足、路径可能已失效，而那时 repository.register
    # 的拒绝必须说清是哪个根（这就是本条要钉的东西）。
    fixture["registry"].local_bindings[root_id]["status"] = "requested"

    with pytest.raises(HTTPException) as refusal:
        call("repository.register", {"name": "repo", "root_id": root_id})

    detail = refusal.value.detail
    assert detail["code"] == "root_binding_required"
    assert detail["root_id"] == root_id
    assert detail["registered"] is True, "根登记了、只是没绑定 —— 这和「根不存在」是两回事"
    assert detail["next"]
