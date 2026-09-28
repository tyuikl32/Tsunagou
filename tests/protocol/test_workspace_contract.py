import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[2]


def test_workspace_receipt_schema_is_optional_but_strict_when_supplied() -> None:
    schema = json.loads((ROOT / "protocol/schemas/commands/workspace/result.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    payload = {"workspace_id": "w", "task_id": "t", "attempt_id": "a", "baseline_digest": "sha256:x",
               "changed_paths": [], "untracked_summary": [], "commit_refs": [], "validation_refs": []}
    validator.validate(payload)
    receipt = {"started_at": "2026-09-27T18:00:00.000Z", "finished_at": "2026-09-27T18:01:00.000Z",
               "command": "pytest -q", "exit_code": 0, "tool": "pytest", "tool_version": "8.0",
               "workspace_digest": "sha256:" + "a" * 64}
    validator.validate({**payload, "validation_metadata": [receipt]})
    with pytest.raises(ValidationError):
        validator.validate({**payload, "validation_metadata": [{**receipt, "stdout_digest": "raw private output"}]})
    with pytest.raises(ValidationError):
        validator.validate({**payload, "validation_metadata": [{**receipt, "stdout": "raw private output"}]})


def test_workspace_protocol_mirror_matches_source_and_scope_is_server_owned() -> None:
    for name in ("result", "prepare"):
        relative = f"schemas/commands/workspace/{name}.schema.json"
        assert (ROOT / "protocol" / relative).read_bytes() == (ROOT / "src/tsunagou/protocol_data" / relative).read_bytes()
    schema = json.loads((ROOT / "protocol/schemas/commands/workspace/prepare.schema.json").read_text(encoding="utf-8"))
    assert "scope_paths" not in schema["properties"]
    assert "scope_digest" not in schema["properties"]
