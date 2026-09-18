from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


def validate_schemas() -> list[str]:
    errors: list[str] = []
    for path in (ROOT / "protocol/schemas").rglob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        try:
            Draft202012Validator.check_schema(schema)
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    return errors


def main() -> int:
    registry = json.loads((ROOT / "protocol/registry/commands.json").read_text(encoding="utf-8"))
    commands = registry.get("commands", {})
    errors = validate_schemas()
    for name, entry in commands.items():
        schema_path = ROOT / "protocol/schemas" / entry["schema"]
        if not schema_path.is_file():
            errors.append(f"{name}: missing {schema_path}")
        if entry.get("principal") not in {"U", "B", "M", "X", "R", "H", "D", "T"}:
            errors.append(f"{name}: invalid principal")
    if errors:
        print("\n".join(errors))
        return 1
    print(f"validated {len(commands)} command policies and {len(list((ROOT / 'protocol/schemas').rglob('*.schema.json')))} schemas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
