"""Generate audit DTOs from the authoritative, deliberately small JSON Schema."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "protocol/schemas/queries/audit-page.schema.json"


def _resolved(schema: dict[str, Any]) -> dict[str, Any]:
    if schema.get("$ref", "").startswith("../"):
        loaded: dict[str, Any] = json.loads((SOURCE.parent / schema["$ref"]).read_text(encoding="utf-8"))
        return loaded
    return schema


def _type(schema: dict[str, Any], *, python: bool) -> str:
    schema = _resolved(schema)
    if "$ref" in schema:
        return str(schema["$ref"]).rsplit("/", 1)[-1] + ("Model" if python else "")
    variants = schema.get("anyOf")
    if variants is not None:
        return " | ".join(_type(item, python=python) for item in variants)
    if "enum" in schema or "const" in schema:
        values = schema.get("enum", [schema.get("const")])
        if python:
            return "Literal[" + ", ".join(repr(item) for item in values) + "]"
        return " | ".join(json.dumps(item) for item in values)
    kind = schema["type"]
    if isinstance(kind, list):
        return " | ".join(_type({**schema, "type": item}, python=python) for item in kind)
    if kind == "array":
        item = _type(schema["items"], python=python)
        return f"list[{item}]" if python else f"Array<{item}>"
    names = {"string": "str" if python else "string", "integer": "int" if python else "number",
             "null": "None" if python else "null"}
    if kind not in names:
        raise ValueError(f"unsupported_audit_schema_type:{kind}")
    return names[kind]


def _constraints(schema: dict[str, Any]) -> str:
    schema = _resolved(schema)
    variants = schema.get("anyOf")
    if variants is not None:
        # The audit schema uses anyOf only for nullable timestamp references.
        schema = _resolved(next(item for item in variants if item.get("type") != "null"))
    names = {"minLength": "min_length", "maxLength": "max_length", "maxItems": "max_length",
             "minimum": "ge", "maximum": "le", "pattern": "pattern"}
    constraints = [f"{target}={schema[source]!r}" for source, target in names.items() if source in schema]
    return " = Field(" + ", ".join(constraints) + ")" if constraints else ""


def render_models(source: Path = SOURCE) -> tuple[str, str]:
    schema = json.loads(source.read_text(encoding="utf-8"))
    definitions = [*schema.get("$defs", {}).values(), schema]
    digest = hashlib.sha256(source.read_bytes() + (source.parent / "../common/timestamp.schema.json").read_bytes()).hexdigest()
    relative = source.relative_to(ROOT).as_posix()
    py = [f'"""Generated from {relative}; do not edit."""',
          f"# Source digest: sha256:{digest}; generator: query-v1", "",
          "from typing import Literal", "", "from pydantic import BaseModel, ConfigDict, Field"]
    ts = [f"// Generated from {relative}; do not edit.",
          f"// Source digest: sha256:{digest}; generator: query-v1"]
    for definition in definitions:
        title = definition["title"]
        py.extend(["", "", f"class {title}Model(BaseModel):",
                   '    model_config = ConfigDict(extra="forbid", strict=True)'])
        ts.extend(["", f"export interface {title} {{"])
        for name, prop in definition["properties"].items():
            if name not in definition["required"]:
                raise ValueError("audit_fields_must_be_present_even_when_null")
            py.append(f"    {name}: {_type(prop, python=True)}{_constraints(prop)}")
            ts.append(f"  {name}: {_type(prop, python=False)};")
        ts.append("}")
    return "\n".join(py) + "\n", "\n".join(ts) + "\n"


def main() -> None:
    query_sources = (
        ("audit", SOURCE),
        ("delivery", SOURCE.with_name("credential-delivery.schema.json")),
        ("checkpoint", SOURCE.with_name("checkpoint-page.schema.json")),
        ("checkpoint_verification", SOURCE.with_name("checkpoint-verification.schema.json")),
    )
    for name, source in query_sources:
        py, ts = render_models(source)
        (ROOT / f"src/tsunagou/generated/protocol/{name}.py").write_text(py, encoding="utf-8")
        (ROOT / f"packages/protocol-ts/src/generated/{name}.ts").write_text(ts, encoding="utf-8")
        # The installed wheel resolves schemas with importlib.resources, not repo paths.
        target = ROOT / "src/tsunagou/protocol_data/schemas/queries" / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    print("generated audit/delivery Python/TypeScript DTOs and packaged schemas")


if __name__ == "__main__":
    main()
