"""命令面必须说真话：schema / 命令目录 / 运行时白名单 / handler 是同一件事（待改 22-①）。

两次实测的返工都落在这里：

* ``coordination.plan`` 的行内字段只写在**描述**里（schema 的 ``items`` 只声明了
  ``acceptance``），主 Agent 因此直接断言" schema 参数和 handler 要的不一致"，转头去读源码、
  甚至准备绕开桥直接打 HTTP（2026-10-08）；
* ``task.ready`` 的 schema 只声明 ``reason`` 且 ``required: ["reason"]``，而 handler 必填
  ``task_id``，还带着 ``additionalProperties: false`` —— 照 schema 写就会被拒；
* ``task.update_plan`` 的 schema 声明 ``acceptance``，运行时白名单当时没有它 →
  任何真实调用都先吃 ``unknown_payload_field``；
* ``agent.retire.user`` 声明 ``agent_id``/``reason``，运行时白名单**整条都不在**；
* ``workspace.integrate`` 有 handler 却没有白名单条目 —— 而**缺条目等于没有校验**
  （``_dispatch`` 只在有条目时才比对字段），所以"没人声明"比"声明错了"更安静。

这四条断言全部机械可查，不需要读 handler 的意图：
schema 的字段集 = 命令目录的字段集 = 运行时真正收的字段集；并且**桥暴露的每个工具都必须有
handler**（模型能看到却永远打不通的工具，是这一族里最贵的一种）。
"""

from __future__ import annotations

import json
import re
from importlib.resources import files
from pathlib import Path

from tsunagou.application.handlers import build_handlers
from tsunagou.interfaces.runtime import PAYLOAD_FIELDS
from tsunagou.modules.authority import AuthorityService

ROOT = Path(__file__).resolve().parents[2]
BRIDGE_SERVER = ROOT / "packages/bridge-server/src/server.ts"
#: 行内字段（coordination.plan 的 assignments）：handler 逐行读这些键。放在这里而不是从
#: handler 反推，是因为它就是"计划这一行长什么样"的唯一说明；schema 与它不一致就是骗人。
PLAN_ROW_FIELDS = {
    "assigned_worker_id", "title", "task_objective", "acceptance", "dependencies",
    "required_contract_ids", "parent_task_id", "execution_scope", "workspace", "supersedes_task_id",
}
PLAN_ROW_REQUIRED = {"assigned_worker_id", "title", "task_objective", "acceptance"}


def _registry() -> dict:
    raw = files("tsunagou.protocol_data").joinpath("registry", "commands.json")
    return json.loads(raw.read_text(encoding="utf-8"))["commands"]


def _schema(entry: dict) -> dict:
    raw = files("tsunagou.protocol_data").joinpath("schemas", entry["schema"])
    return json.loads(raw.read_text(encoding="utf-8"))


def _handlers() -> dict:
    return build_handlers(authority=AuthorityService())


def test_every_command_the_runtime_screens_is_screened_by_a_real_handler() -> None:
    """白名单有条目却没 handler：那条"校验"守着一个不存在的门。"""

    handlers = _handlers()
    unpublished = sorted(set(PAYLOAD_FIELDS) - set(handlers) - {"workspace.git.report"})
    assert unpublished == [], f"白名单里有条目但没人实现：{unpublished}"


def test_the_catalog_and_the_runtime_accept_the_same_fields() -> None:
    """命令目录是调用方看到的契约，运行时白名单是真正收字段的那一层。"""

    registry, handlers = _registry(), _handlers()
    mismatches = []
    for kind in sorted(set(handlers)):
        entry = registry.get(kind)
        assert entry is not None, f"{kind} 有 handler 却不在命令目录里"
        declared = set(entry["payload_fields"])
        accepted = set(PAYLOAD_FIELDS.get(kind, set()))
        if declared != accepted:
            mismatches.append((kind, sorted(declared - accepted), sorted(accepted - declared)))
        strays = set(entry["required_fields"]) - accepted
        assert not strays, f"{kind} 把运行时根本不收的字段标成必填：{sorted(strays)}"
    assert mismatches == [], f"目录与运行时不一致（多收的字段会被 unknown_payload_field 拒）：{mismatches}"


def test_every_served_command_schema_declares_exactly_what_the_daemon_accepts() -> None:
    """桥把这份 schema 原样当 MCP ``inputSchema`` 发给模型，所以它就是"工具面"。"""

    registry, handlers = _registry(), _handlers()
    problems = []
    for kind in sorted(set(handlers)):
        entry = registry[kind]
        schema = _schema(entry)
        properties = set(schema.get("properties", {}))
        accepted = set(PAYLOAD_FIELDS.get(kind, set()))
        if properties != accepted:
            problems.append((kind, "properties", sorted(accepted - properties), sorted(properties - accepted)))
        required = set(schema.get("required", []))
        if required - accepted:
            problems.append((kind, "required-not-accepted", sorted(required - accepted), []))
        if set(entry["required_fields"]) != required:
            problems.append((kind, "catalog-required", sorted(required), sorted(set(entry["required_fields"]))))
    assert problems == [], f"schema 与运行时/目录不一致：{problems}"


def test_the_plan_row_schema_names_the_row_the_handler_reads() -> None:
    """`coordination.plan` 的行：schema 必须声明 handler 真正读的那些键。

    这一条是 2026-10-08 那次"schema 参数和 handler 要的不一致"的直接回归：当时 items 里只有
    ``acceptance``，而 handler 逐行读 assigned_worker_id / title / task_objective ……
    """

    schema = _schema(_registry()["coordination.plan"])
    items = schema["properties"]["assignments"]["items"]
    properties = set(items.get("properties", {}))
    assert PLAN_ROW_FIELDS <= properties, f"行内字段没声明全：{sorted(PLAN_ROW_FIELDS - properties)}"
    assert set(items.get("required", [])) == PLAN_ROW_REQUIRED


def test_every_tool_the_bridge_exposes_is_implemented_here() -> None:
    """桥的工具面是模型唯一能看见的东西：它列出来的名字必须真能打通。"""

    source = BRIDGE_SERVER.read_text(encoding="utf-8")
    kinds = set(re.findall(r'command_kind:\s*"([a-z][a-z0-9_.]*)"', source))
    assert len(kinds) > 40, f"从桥的 TOOLS 里只认出 {len(kinds)} 个 command_kind，解析大概失效了"
    handlers = _handlers()
    missing = sorted(kinds - set(handlers))
    assert missing == [], f"桥把这几条列进了工具面，daemon 却没有 handler：{missing}"
