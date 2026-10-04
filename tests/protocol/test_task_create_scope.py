"""``task.create`` requires an ``execution_scope`` key, but {} stays legal.

The field is what the reservation, workspace and evidence layers all key off, so a caller
that simply omits it is asking the daemon to guess. Passing ``{}`` is different: it is a
statement that the task claims nothing in particular. Required is therefore not the same
as non-empty, and both halves have to hold at the wire contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[2]
RELATIVE = "schemas/commands/task/create.schema.json"


def schema() -> dict:
    return json.loads((ROOT / "protocol" / RELATIVE).read_text(encoding="utf-8"))


def test_execution_scope_is_required_but_may_be_empty() -> None:
    validator = Draft202012Validator(schema())
    assert "execution_scope" in schema()["required"]
    with pytest.raises(ValidationError):
        validator.validate({"title": "write one file", "objective": "produce output"})
    validator.validate({"title": "write one file", "objective": "produce output", "execution_scope": {}})
    validator.validate({
        "title": "write one file", "objective": "produce output",
        "execution_scope": {"roots": ["coordination"]},
    })
    validator.validate({
        "title": "write one file", "objective": "produce output",
        "execution_scope": {"resources": [
            {"kind": "path", "root_id": "coordination", "segments": ["demo.txt"], "mode": "exclusive_write"},
        ]},
    })


def test_scope_documentation_survives_in_every_packaged_copy() -> None:
    scope = schema()["properties"]["execution_scope"]
    assert scope["description"] and scope["examples"], "the legal scope shapes have to be documented"
    raw = (ROOT / "protocol" / RELATIVE).read_bytes()
    for copy in ("src/tsunagou/protocol_data", "packages/bridge-server/protocol"):
        assert raw == (ROOT / copy / RELATIVE).read_bytes(), f"{copy} carries a stale scope contract"


def test_registry_agrees_that_scope_is_a_required_field() -> None:
    registry = json.loads((ROOT / "protocol/registry/commands.json").read_text(encoding="utf-8"))
    entry = registry["commands"]["task.create"]
    assert "execution_scope" in entry["required_fields"]
    assert set(entry["required_fields"]) == set(schema()["required"])
