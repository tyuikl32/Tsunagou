from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import rfc8785

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "docs/implementation/command-catalog.md"
REGISTRY = ROOT / "protocol/registry/commands.json"


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


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
        for raw in payload.split(","):
            raw = raw.strip().replace("?", "")
            if not raw or raw.startswith("同"):
                continue
            field = re.split(r"[:(]", raw, maxsplit=1)[0].strip()
            if re.match(r"^[a-z][a-z0-9_]*$", field):
                fields.append(field)
        result[name] = {
            "uri": uri,
            "principal": principal,
            "payload_fields": sorted(set(fields)),
            "schema": f"commands/{name.replace('.', '/')}.schema.json",
        }
    return result


def write_schema(name: str, entry: dict[str, Any]) -> None:
    path = ROOT / "protocol/schemas" / entry["schema"]
    path.parent.mkdir(parents=True, exist_ok=True)
    properties: dict[str, Any] = {}
    for field in entry["payload_fields"]:
        if field.endswith("_id") or field in {"id", "proposal_ref", "subject_ref"}:
            properties[field] = {"type": "string", "minLength": 1}
        elif field.startswith("expected_") or field.endswith("_epoch") or field.endswith("_revision"):
            properties[field] = {"type": ["integer", "string", "object"], "minimum": 0}
        elif field in {"reason", "summary", "objective", "title", "name"}:
            properties[field] = {"type": "string", "maxLength": 4096}
        else:
            properties[field] = {}
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://tsunagou.local/schema/commands/{name}",
        "title": "".join(part.title() for part in name.split(".")) + "Payload",
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": [field for field in entry["payload_fields"] if not field.endswith("?")],
    }
    path.write_text(json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    commands = extract_commands()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    registry["commands"] = commands
    digest_input = rfc8785.dumps(commands)
    registry["schema_bundle_digest"] = "sha256:" + hashlib.sha256(digest_input).hexdigest()
    REGISTRY.write_text(json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for name, entry in commands.items():
        write_schema(name, entry)
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
        encoding="utf-8",
    )
    print(f"generated {len(commands)} command schemas")


if __name__ == "__main__":
    main()
