"""任务的公开描述：**开工之前**就该看得出这个任务要不要碰文件。

判据与执行那一道完全同源：资源请求里有 `path` 那一行（或写了 `roots`）就是"要工作区"。
把它说出来，是为了让远端那台机器**别白跑一趟** —— 它没报代码副本时接不了这类任务
（D191 / D192），而"白跑一趟"的表现是一次被拒的 `task.begin`，人要到那一刻才知道。
"""

from __future__ import annotations

import pytest

from tsunagou.modules.tasks import TaskService


def _service() -> TaskService:
    return TaskService()


def test_a_task_that_reserves_paths_says_so(tmp_path) -> None:
    service = _service()
    task = service.create_task("改一处代码", "产出一份改动", execution_scope={
        "resources": [{"kind": "path", "root_id": "coordination", "segments": ["demo.txt"],
                       "mode": "exclusive_write"}],
    })

    assert service.describe_task(task.task_id)["requires_workspace"] is True


def test_a_task_that_names_roots_also_says_so(tmp_path) -> None:
    """老写法（直接列 roots）同样是要工作区。"""

    service = _service()
    task = service.create_task("在某个根里干活", "产出", execution_scope={"roots": ["coordination"]})

    assert service.describe_task(task.task_id)["requires_workspace"] is True


def test_a_reasoning_task_says_no(tmp_path) -> None:
    """纯推理的活不占工作区：远端照旧能接，这一项也说"不用"。"""

    service = _service()
    task = service.create_task("只看不改", "给一份评审意见")

    assert service.describe_task(task.task_id)["requires_workspace"] is False


def test_only_a_path_resource_counts(tmp_path) -> None:
    """有资源、但没有路径那一种（例如某个名字的独占使用）不算"要碰文件"。"""

    service = _service()
    task = service.create_task("占用一个名字", "产出", execution_scope={
        "resources": [{"kind": "named", "namespace": "fixture", "name": "lock", "mode": "exclusive_use"}],
    })

    assert service.describe_task(task.task_id)["requires_workspace"] is False


def test_a_damaged_scope_does_not_crash_the_description(tmp_path) -> None:
    """范围写坏了不该让"看一眼任务"这件事炸掉：描述退回"不用工作区"，执行那边照样会拒。"""

    service = _service()
    task = service.create_task("范围怪怪的", "产出")
    task.execution_scope = ["not-a-mapping"]  # type: ignore[assignment]

    assert service.describe_task(task.task_id)["requires_workspace"] is False


@pytest.mark.parametrize("scope", [{}, {"resources": []}])
def test_an_empty_scope_is_a_reasoning_task(tmp_path, scope) -> None:
    service = _service()
    task = service.create_task("空范围", "产出", execution_scope=scope)

    assert service.describe_task(task.task_id)["requires_workspace"] is False
