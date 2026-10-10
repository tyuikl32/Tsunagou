from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

import rfc8785

from tsunagou.interfaces.runtime import PAYLOAD_FIELDS

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "docs/implementation/command-catalog.md"
REGISTRY = ROOT / "protocol/registry/commands.json"


def _cells(line: str) -> list[str]:
    # A literal pipe inside a Markdown table cell must be written as `\|`.
    # Protect that escape before splitting, or a field annotation such as
    # `kind:notification\|request` is cut in half and the rest of the payload
    # list silently becomes a different table column.
    protected = line.strip().strip("|").replace("\\|", "\x00")
    return [cell.replace("\x00", "|").strip() for cell in protected.split("|")]


def extract_commands() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    header = False
    for line in CATALOG.read_text(encoding="utf-8").splitlines():
        if line.startswith("| command kind |") or line.startswith("| command |"):
            header = True
            continue
        if not header or not line.startswith("|") or line.startswith("|---"):
            if line.startswith("## "):
                header = False
            continue
        cells = _cells(line)
        if len(cells) < 5 or cells[0] in {"command", "command kind", ""}:
            continue
        name, uri, permission, payload = cells[:4]
        uri = uri.replace(chr(96), "")
        if not re.match(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$", name):
            continue
        principal = permission.split("/", 1)[0].strip()
        fields = []
        required_fields = []
        for raw in payload.split(","):
            raw = raw.strip()
            if not raw or raw.startswith("同"):
                continue
            optional = raw.endswith("?")
            raw = raw.rstrip("?")
            field = re.split(r"[:(]", raw, maxsplit=1)[0].strip()
            if re.match(r"^[a-z][a-z0-9_]*$", field):
                fields.append(field)
                if not optional:
                    required_fields.append(field)
        result[name] = {
            "uri": uri,
            "principal": principal,
            "payload_fields": sorted(set(fields)),
            "required_fields": sorted(set(required_fields)),
            "schema": f"commands/{name.replace('.', '/')}.schema.json",
        }
    # 命令目录是**调用方看到的契约**，运行时白名单是**真正收字段的那一层**。两者不一致就是
    # "接口面骗人"里最便宜也最贵的一类：照着 schema 写的调用会被 `unknown_payload_field` 拒，
    # 而 schema 没提的字段（`task.ready` 的 `task_id`，handler 明明必填）只能靠模型猜。
    # 所以这里不是"谁覆盖谁"，而是**当场不一致就停**：先改目录，再生成（待改 22-①）。
    # 只在真目录上做：测试会拿一份合成目录来验证解析器（`test_message_contract`），
    # 那份目录本来就不是完整契约。
    if CATALOG != ROOT / "docs/implementation/command-catalog.md":
        return result
    for name, entry in result.items():
        accepted = PAYLOAD_FIELDS.get(name)
        if accepted is None:
            continue
        declared = set(entry["payload_fields"])
        if declared != set(accepted):
            raise SystemExit(
                f"{name}: docs/implementation/command-catalog.md 与 interfaces/runtime.py 的 "
                f"PAYLOAD_FIELDS 不一致：目录多了 {sorted(declared - set(accepted))}、"
                f"少了 {sorted(set(accepted) - declared)}。改目录，再重新生成。"
            )
        strays = set(entry["required_fields"]) - set(accepted)
        if strays:
            raise SystemExit(
                f"{name}: 目录把运行时根本不收的字段标成必填：{sorted(strays)}（待改 22-①）"
            )
        entry["payload_fields"] = sorted(accepted)
    return result


def field_schema(field: str) -> dict[str, Any]:
    """The type this generator scaffolds for a field it has not seen before.

    Deliberately permissive: the daemon's own validation is the authority on a value's shape,
    and a schema that over-specifies would refuse calls the daemon accepts. What the surface
    must get right is *which* fields exist.
    """

    if field.endswith("_id") or field in {"id", "proposal_ref", "subject_ref"}:
        return {"type": "string", "minLength": 1}
    if field in {"changed_paths", "untracked_summary", "commit_refs", "validation_refs",
                 "root_binding_refs", "scope_paths"}:
        return {"type": "array", "items": {"type": "string"}}
    if field == "patch_artifact_ref":
        return {"type": ["string", "null"]}
    if field.startswith("expected_") or field.endswith("_epoch") or field.endswith("_revision"):
        return {"type": ["integer", "string", "object"], "minimum": 0}
    if field in {"reason", "summary", "objective", "title", "name"}:
        return {"type": "string", "maxLength": 4096}
    return {}


def reconcile_schema(entry: dict[str, Any], path: Path) -> bool:
    """Make an existing schema tell the truth about the *field set* (待改 22-①).

    Hand-authored constraints stay: this never rewrites a type. What it fixes is the drift that
    bit callers for real — a schema that never mentioned a field the daemon accepts (and the
    handler *requires*: ``task.ready`` and ``task_id``), and one that promised a field the
    daemon rejected (``task.update_plan``'s ``acceptance``). Because these schemas set
    ``additionalProperties: false``, either direction turns the surface into a trap.
    """

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("type") != "object":
        return False
    properties = raw.get("properties")
    if not isinstance(properties, dict):
        return False
    accepted = set(entry["payload_fields"])
    changed = False
    for field in sorted(accepted - set(properties)):
        properties[field] = field_schema(field)
        changed = True
    for field in sorted(set(properties) - accepted):
        del properties[field]
        changed = True
    required = [field for field in entry.get("required_fields", []) if field in accepted]
    if list(raw.get("required", [])) != required:
        raw["required"] = required
        changed = True
    if changed:
        # No ``sort_keys``: this file is hand-authored, and reconciling the field set must not
        # show up as a whole-file reordering (that is how a one-line fix becomes unreviewable).
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return changed


def write_schema(name: str, entry: dict[str, Any]) -> None:
    path = ROOT / "protocol/schemas" / entry["schema"]
    # Existing domain schemas contain hand-authored constraints that cannot be
    # inferred from a Markdown field list. Preserve them; this generator owns
    # the workspace schemas and scaffolds missing command schemas only.
    if path.exists() and name not in {"workspace.prepare", "workspace.result"}:
        # …except the field set, for the commands the daemon actually serves: there the
        # runtime whitelist is ground truth, and a schema disagreeing with it is the defect
        # this reconciliation exists to prevent (待改 22-①).
        if name in PAYLOAD_FIELDS:
            reconcile_schema(entry, path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    properties: dict[str, Any] = {}
    for field in entry["payload_fields"]:
        if field == "validation_metadata":
            properties[field] = {
                "type": "array", "maxItems": 100,
                "items": {
                    "type": "object", "additionalProperties": False,
                    "properties": {
                        "started_at": {"type": "string", "format": "date-time"},
                        "finished_at": {"type": "string", "format": "date-time"},
                        "command": {"type": "string", "minLength": 1, "maxLength": 4096},
                        "exit_code": {"type": "integer"},
                        "tool": {"type": "string", "minLength": 1, "maxLength": 256},
                        "tool_version": {"type": "string", "minLength": 1, "maxLength": 256},
                        "workspace_digest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
                        "evidence_level": {"enum": ["agent_asserted", "host_observed", "system_verified", "user_confirmed"]},
                        "stdout_digest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
                        "stderr_digest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
                    },
                    "required": ["started_at", "finished_at", "command", "exit_code", "tool", "tool_version", "workspace_digest"],
                },
            }
        else:
            properties[field] = field_schema(field)
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://tsunagou.local/schema/commands/{name}",
        "title": "".join(part.title() for part in name.split(".")) + "Payload",
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": entry.get("required_fields", entry["payload_fields"]),
    }
    path.write_text(json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")


def main() -> None:
    commands = extract_commands()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    registry["commands"] = commands
    digest_input = rfc8785.dumps(commands)
    registry["schema_bundle_digest"] = "sha256:" + hashlib.sha256(digest_input).hexdigest()
    # ``newline="\n"`` everywhere: ``.gitattributes`` pins JSON to LF, and a CRLF working tree
    # makes every packaged-copy comparison (and every diff) unreadable.
    REGISTRY.write_text(json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8", newline="\n")
    for name, entry in commands.items():
        write_schema(name, entry)
    for directory in ("registry", "schemas", "fixtures"):
        shutil.copytree(ROOT / "protocol" / directory, ROOT / "src/tsunagou/protocol_data" / directory, dirs_exist_ok=True)
    # 桥读它自己那份 registry（命令策略与 schema bundle 摘要都在里面）：摘要不一致会让每次调用都
    # `schema_bundle_digest_mismatch`，所以这一份必须跟着生成。schemas 也一样要跟：桥把 schema
    # 原样当 MCP `inputSchema` 发给模型（`commandSchema()` 先在自己包里找），只同步一部分就会让
    # 装好的桥对剩下的工具报 `command_schema_unavailable` —— 而契约测试拿三份拷贝逐字节比对，
    # 只补一部分还会让"这份拷贝是不是陈的"没法判断。
    for directory in ("registry", "schemas"):
        shutil.copytree(
            ROOT / "protocol" / directory, ROOT / "packages/bridge-server/protocol" / directory,
            dirs_exist_ok=True,
        )
    generated_py = ROOT / "src/tsunagou/generated/protocol/models.py"
    generated_py.parent.mkdir(parents=True, exist_ok=True)
    generated_py.write_text(
        '"""Generated from protocol/registry/commands.json; do not edit."""\n'
        '\n'
        'from pydantic import BaseModel, ConfigDict, Field\n\n\n'
        'class CommandEnvelopeModel(BaseModel):\n'
        '    model_config = ConfigDict(extra="forbid", frozen=True)\n'
        '    command_id: str\n'
        '    protocol_version: str\n'
        '    schema_bundle_digest: str\n'
        '    payload: dict[str, object] = Field(default_factory=dict)\n',
        encoding="utf-8",
    )
    generated_ts = ROOT / "packages/protocol-ts/src/generated/commands.ts"
    generated_ts.write_text(
        "// Generated from protocol/registry/commands.json; do not edit.\n"
        "export type CommandKind =\n"
        + "".join(f'  | "{name}"\n' for name in sorted(commands))
        + ";\n",
        encoding="utf-8", newline="\n",
    )
    print(f"generated {len(commands)} command schemas")


if __name__ == "__main__":
    main()
