"""中间层把一屏的出口拼成地址时，那条例外要有名字。

daemon 服务一个项目，绝大多数出口挂在 `/api/v1/projects/{id}/…` 下面，所以"出口名前面加项目
前缀"是能用的规矩。`decisions` 是例外：它是 `/api/v1/decisions`（答的是这个 daemon 自己那个
项目的待定项）。拼错的后果不是报错而是 404 —— 看上去像"这个项目没有待决定的事"，
于是验收页的收尾提案卡与主视图那一节永远空着，而且没人会觉得是接线出了问题。
"""

from __future__ import annotations

from tsunagou.console.app import CONSOLE_VIEWS, GlobalExit, exit_path

PROJECT = "0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b44"


def test_a_project_scoped_exit_gets_the_project_prefix() -> None:
    assert exit_path(PROJECT, "/tasks") == f"/api/v1/projects/{PROJECT}/tasks"


def test_a_global_exit_is_not_given_the_project_prefix() -> None:
    assert exit_path(PROJECT, GlobalExit("/decisions")) == "/api/v1/decisions"


def test_only_the_exits_that_are_really_global_are_marked() -> None:
    """标错的代价是静默 404，所以把"哪些被标了"钉在测试里。"""

    marked = {
        (view, name)
        for view, sources in CONSOLE_VIEWS.items()
        for name, source in sources.items()
        if isinstance(source, GlobalExit)
    }

    assert marked == {("overview", "decisions"), ("acceptance", "decisions")}
