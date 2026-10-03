"""跨机器：远端什么时候可以干"要碰文件"的活（D191 → D192）。

判据不是"任务描述里提到文件"，而是**它要不要工作区**：任务的资源请求里有 `path` 那一行时，
`prepare_begin` 就会去要工作区。工作区、基线与证据按构造都是**某台机器文件系统上的事实**：

* **本机** Agent：仓库根就在这台机器上，照旧 —— 主机亲自扫、亲自记基线、交活时出清单。
* **远端** Agent：主机读不到它那份副本，所以只放行一种形态 —— 那台机器**入席时报过自己的副本**
  （`agent import --copy`，随 `descriptor_ref` 上来），且工作区按**外部准备**指向同一个位置。
  这时主机只记账、不扫盘：没有基线、交活时**没有清单**（"那台机器说它改了什么"，不是"我们看过"）。
* 其余情形一律拒绝：没报副本、走了共享目录/独立检出、或者工作区指到了另一个位置 ——
  它们会变成最坏的那种失败：看起来在范围内，实际改的是别处的同名文件。
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from tests.integration.test_execution_begin import begin, published
from tests.integration.test_execution_begin import execution_runtime as runtime  # noqa: F401  (夹具按名字取用)
from tests.integration.test_m1_runtime_flow import _baseline

COPY = "D:/work/远端副本"


def enroll_remote(call, name: str, *, machine: str = "工位-七", copy: str = "", baseline: str = ""):
    """一个跨机器接进来的子 Agent：入席时自报机器名（以及它那份代码副本）。"""

    identity = {"installation_id": name, "conversation_evidence": {"conversation_id": name}}
    ticket = call("agent.ticket.create.user", {"kind": "worker", **identity})
    descriptor: dict = {"machine": machine}
    if copy:
        descriptor["copy"] = {"path": copy, "baseline": baseline}
    return call("agent.enroll", {
        **identity, "descriptor_ref": descriptor, "probe_payload": _baseline(),
    }, token=ticket["secret"])


def a_file_task_with(call, main, driver_kind: str, locator: str | None = None):
    """一个要工作区的任务，隔离方式由主 Agent 选。"""

    scope = {"resources": [{"kind": "path", "root_id": "coordination",
                            "segments": ["demo.txt"], "mode": "exclusive_write"}]}
    task = call("task.create", {"title": "write", "objective": "produce output", "execution_scope": scope}, main)
    decision = {"task_id": task["task_id"], "driver_kind": driver_kind}
    if locator is not None:
        decision["external_locator"] = locator
    call("workspace.select", decision, main)
    call("task.ready", {"task_id": task["task_id"]}, main)
    return call("task.publish", {"task_id": task["task_id"]}, main)


def refusal(call, task, worker) -> str:
    with pytest.raises(HTTPException) as refused:
        begin(call, task, worker)
    return str(refused.value.detail)


def test_a_remote_without_a_reported_copy_is_refused(runtime) -> None:  # noqa: F811
    app, call, main, worker = runtime
    task = a_file_task_with(call, main, "external", COPY)
    remote = enroll_remote(call, "没报副本的远端")
    state = app.state.state_runtime
    before = state.capture()

    assert "remote_worker_needs_a_code_copy" in refusal(call, task, remote)
    assert state.capture() == before, "拒绝要早：没占工作区、没占资源、没建尝试"


def test_a_remote_must_use_the_external_shape(runtime) -> None:  # noqa: F811
    """报了副本还不够：工作区必须是"外部准备"。共享目录/独立检出绑的是**主机**的根。"""

    app, call, main, worker = runtime
    shared = a_file_task_with(call, main, "shared")
    remote = enroll_remote(call, "报了副本的远端", copy=COPY)

    assert "remote_worker_requires_external_workspace" in refusal(call, shared, remote)


def test_a_remote_workspace_must_point_at_the_reported_copy(runtime) -> None:  # noqa: F811
    """指到别处等于又变成"看起来在范围内"：位置对不上就拒绝。"""

    app, call, main, worker = runtime
    elsewhere = a_file_task_with(call, main, "external", "D:/somewhere/else")
    remote = enroll_remote(call, "报了副本的远端", copy=COPY)

    assert "remote_workspace_locator_mismatch" in refusal(call, elsewhere, remote)


def test_a_remote_with_a_copy_and_external_can_work_and_leaves_no_manifest(runtime) -> None:  # noqa: F811
    """放行的那一种：主机**不扫**它的盘 —— 没有基线、交活时没有清单，只有那台机器的交代。"""

    app, call, main, worker = runtime
    task = a_file_task_with(call, main, "external", COPY)
    remote = enroll_remote(call, "报了副本的远端", copy=COPY, baseline="main")
    state = app.state.state_runtime

    started = begin(call, task, remote)

    assert started["status"] == "running" and started["workspace_id"]
    workspace = state.workspaces.workspaces[started["workspace_id"]]
    assert workspace.driver_kind == "external" and workspace.external_locator == COPY
    assert workspace.status == "remote_reported", "如实写成远端自报，不是就绪"
    assert workspace.baseline_manifest_id is None, "主机没看过，就没有基线"
    assert not [item for item in state.workspaces.baselines.values()
                if item.workspace_id == workspace.workspace_id]

    done = call("task.submit", {"task_id": task["task_id"], "attempt_id": started["attempt_id"],
                                "summary": "在远端副本上改完了"}, remote)

    assert done["status"] == "submitted"
    assert done.get("workspace_result_ref") is None, "没有清单：那不是主机观察出来的东西"


def test_a_local_worker_is_untouched_by_any_of_this(runtime) -> None:  # noqa: F811
    """本机 Agent 一个路径都不少：同一个任务照旧扫盘、记基线、出清单。"""

    app, call, main, worker = runtime
    task = a_file_task_with(call, main, "shared")
    enroll_remote(call, "旁边那个远端", copy=COPY)
    state = app.state.state_runtime

    started = begin(call, task, worker)

    assert started["status"] == "running" and started["workspace_id"]
    workspace = state.workspaces.workspaces[started["workspace_id"]]
    assert workspace.baseline_manifest_id is not None, "本机这一条照旧有基线"
    assert workspace.status != "remote_reported"


def test_a_remote_keeps_every_task_that_needs_no_files(runtime) -> None:  # noqa: F811
    """纯推理的活不受这些门槛影响：没有 path 资源，就走不到工作区那一步。"""

    app, call, main, worker = runtime
    task = published(call, main)
    remote = enroll_remote(call, "远端的会话")

    started = begin(call, task, remote)

    assert started["status"] == "running" and started["workspace_id"] is None
    done = call("task.submit", {"task_id": task["task_id"], "attempt_id": started["attempt_id"],
                                "summary": "只看不改，做完了"}, remote)
    assert done["status"] == "submitted"


def test_the_descriptor_object_still_names_the_machine(runtime) -> None:  # noqa: F811
    """入席时报的是一个对象：机器名和副本位置都记得住。"""

    app, call, main, worker = runtime
    receipt = enroll_remote(call, "远端的会话", machine="工位-八", copy=COPY, baseline="v1.2")

    agent = app.state.state_runtime.authority.agents[receipt["agent_id"]]

    assert agent.machine == "工位-八"
    assert agent.copy_path == COPY and agent.copy_baseline == "v1.2"
