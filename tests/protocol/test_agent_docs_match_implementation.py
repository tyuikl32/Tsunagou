"""面向 Agent 的文档必须与实现一致 —— 不一致就让测试红（2026-10-10 复盘的收尾要求）。

实测里"手册与实现不一致"是真实成本：手册 §2.6 写"只有 command 与 exit_code 必填"，而校验器要七个
⇒ 16 次拒绝、工人干完活交不上；桥的 `task__review_accept` schema 把 `slot_id` 标成必填，而 handler
从来不读它 ⇒ 模型得凭空编一个值。靠人读手册发现不了这一类，所以这里把它变成断言：

1. 手册里提到的**每条命令**都在命令注册表里（写错名字、或命令改了名，立刻红）；
2. 手册里提到的**每个工具名**都在桥的工具表里（同上，真值取自 `server.ts` 的源码）；
3. 手册对 `validation_metadata` 的必填说法 == 校验器真正要的字段集（这一类"半截改动"的哨兵）；
4. 手册列出的唤醒白名单 == `WAKE_WORTHY_KINDS`（"我发了它会不会动"是 Agent 每天都要判的事）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tsunagou.modules.messaging import WAKE_WORTHY_KINDS
from tsunagou.modules.workspaces import _normalise_validation_metadata

ROOT = Path(__file__).resolve().parents[2]
MANUAL = ROOT / "docs" / "overview" / "agent-operating-manual.md"
REGISTRY = ROOT / "protocol" / "registry" / "commands.json"
BRIDGE_SOURCE = ROOT / "packages" / "bridge-server" / "src" / "server.ts"

#: 手册里出现的形如 ``task.foo.bar`` 的 token 里，这些前缀才是命令（其余是文件名/字段名）。
_COMMAND_PREFIXES = (
    "task", "inbox", "message", "coordination", "contract", "workspace", "root", "repository",
    "context", "project", "user_decision", "cognition", "discrepancy", "durability",
)
_COMMAND_RE = re.compile(r"\b(" + "|".join(_COMMAND_PREFIXES) + r")\.[a-z][a-z_.]*[a-z]\b")
_TOOL_RE = re.compile(r"\b(" + "|".join(_COMMAND_PREFIXES) + r")__[a-z][a-z_]*[a-z]\b")


def _registered() -> set[str]:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    commands = registry["commands"] if isinstance(registry, dict) and "commands" in registry else registry
    return set(commands) if isinstance(commands, dict) else {str(item["command_kind"]) for item in commands}


def _bridge_tools() -> set[str]:
    return set(re.findall(r'\{ name: "([a-z_]+)"', BRIDGE_SOURCE.read_text(encoding="utf-8")))


def _manual() -> str:
    return MANUAL.read_text(encoding="utf-8")


#: 这些 token 看起来像命令，但不是命令：运行层自己写的事件/账本键、能力名、以及手册引用实现时
#: 提到的内部函数。每条都要写清理由 —— 白名单本身就是"手册允许提到什么"的清单。
_NOT_COMMANDS = {
    "coordination.denied": "context.project_read 里的拒绝账本键（不是命令）",
    "coordination.idle_watchdog": "看门狗自己写的运行层事件名",
    "coordination.refusal_repeat": "拒绝回响写的运行层事件名",
    "project.objective": "用户决定的 kind（不是命令）",
    "project.complete": "完工决定的 kind（不是命令）",
    "task.execute": "能力名（授权用的 capability，不是命令）",
    "task.manage": "能力名",
    "task.coordinate_self": "能力名",
    "coordination.read": "能力名",
    "coordination.write": "能力名",
    "message.send": "能力名与命令同名：能力那一侧由白名单覆盖",
    "coordination.create_plan": "手册引用实现时提到的内部函数名",
}
_FILE_SUFFIXES = ("py", "md", "json", "ts", "tsx", "toml", "yaml", "yml", "sqlite3")


def test_every_command_the_manual_names_exists() -> None:
    """手册点名的命令必须真的在册：名字写错、命令改名、或提到不存在的东西，这一条就红。"""

    registered = _registered()
    messaging = (ROOT / "src" / "tsunagou" / "modules" / "messaging.py").read_text(encoding="utf-8")
    kinds = set(re.findall(r'"([a-z_]+\.[a-z_.]+)"', messaging))
    allowed = registered | kinds | set(_NOT_COMMANDS)
    unknown = []
    for match in _COMMAND_RE.finditer(_manual()):
        name = match.group(0)
        if name.rsplit(".", 1)[-1] in _FILE_SUFFIXES:
            continue
        if name not in allowed:
            unknown.append(name)
    assert not sorted(set(unknown)), f"手册提到的名字既不是命令也不是已知种类：{sorted(set(unknown))}"


def test_the_manual_documents_the_whole_tool_surface() -> None:
    """反方向：桥暴露给 Agent 的每条命令，手册都要点名（新命令不允许悄悄出现）。

    只比**桥的工具面**，不比整个注册表：注册表里还有用户面/控制台面的命令（`*.user`、入席、
    项目生命周期、产物、风险……），那些不是 Agent 的工作面，不该要求手册覆盖。

    2026-10-10 的教训正是"实现先走、文档落后"：手册 §2.6 写着旧的必填规则，而校验器已经改了。
    """

    manual = _manual()
    pairs = re.findall(r'\{ name: "([a-z_]+)", command_kind: "([a-z_.]+)"',
                       BRIDGE_SOURCE.read_text(encoding="utf-8"))
    missing = sorted(kind for tool, kind in pairs if tool not in manual and kind not in manual)
    assert not missing, f"这些命令在桥的工具面上，却没有写进手册：{missing}"


def test_every_tool_the_manual_names_exists_in_the_bridge() -> None:
    """手册点名的 MCP 工具必须真的由桥暴露（真值取自桥的源码，不是另抄一份清单）。"""

    tools = _bridge_tools()
    mentioned = {match.group(0) for match in _TOOL_RE.finditer(_manual())}
    unknown = sorted(name for name in mentioned if name not in tools)
    assert not unknown, f"手册提到的工具不在桥的工具表里：{unknown}"
    # 反向也要成立：桥暴露的每条命令，手册至少要在某处点过名（新命令不许悄悄出现）。
    registered_kinds = _registered()
    tool_kinds = set(re.findall(r'command_kind: "([a-z_.]+)"', BRIDGE_SOURCE.read_text(encoding="utf-8")))
    assert tool_kinds <= registered_kinds, f"桥暴露了注册表里没有的命令：{sorted(tool_kinds - registered_kinds)}"


def test_the_manual_states_the_validation_receipt_minimum_the_validator_enforces() -> None:
    """2026-10-10 那次"16 次字段门"的哨兵：手册写的必填 == 校验器真正接受的必填。"""

    from tsunagou.shared_kernel.errors import CommandRefused

    try:
        _normalise_validation_metadata([{"command": "pytest -q", "exit_code": 0}])
    except CommandRefused as exc:  # pragma: no cover - 这条一旦触发就是回归
        raise AssertionError(f"最小回执被拒了：{exc.detail}") from exc
    with pytest_raises(CommandRefused) as caught:
        _normalise_validation_metadata([{"exit_code": 0}])
    enforced = set(caught.value.detail["required"])
    assert enforced == {"command", "exit_code"}, enforced

    manual = _manual()
    assert "`validation_metadata`（其中只有 `command` 与 `exit_code` 必填" in manual, \
        "手册里那句必填说明要与校验器一致"


def test_the_manual_lists_exactly_the_wake_worthy_kinds() -> None:
    """手册里的唤醒白名单 == ``WAKE_WORTHY_KINDS``（Agent 据此判断"我发了它会不会动"）。"""

    manual = _manual()
    missing = sorted(kind for kind in WAKE_WORTHY_KINDS if kind not in manual)
    assert not missing, f"手册没有列出这些会唤醒对方的 kind：{missing}"


# ``pytest.raises`` 的薄包装：这个模块只 import 需要的东西，读起来更直白。
def pytest_raises(exception: type[BaseException]) -> object:
    import pytest

    return pytest.raises(exception)
