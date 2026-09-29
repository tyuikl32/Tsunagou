from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from tsunagou.interfaces.runtime import PAYLOAD_FIELDS

ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str):
    return json.loads((ROOT / "protocol" / relative).read_text(encoding="utf-8"))


def test_user_decision_schemas_match_runtime_and_packaged_copies() -> None:
    cases = {
        "user_decision.propose": "user-decision-propose",
        "user_decision.resolve": "user-decision-resolve",
    }
    for command, fixture_name in cases.items():
        relative = f"schemas/commands/{command.replace('.', '/')}.schema.json"
        fixture = f"fixtures/valid/{fixture_name}.json"
        schema = _read(relative)
        Draft202012Validator(schema).validate(_read(fixture))
        assert (ROOT / "protocol" / relative).read_bytes() == (ROOT / "src/tsunagou/protocol_data" / relative).read_bytes()
        registry = _read("registry/commands.json")["commands"][command]
        assert set(registry["payload_fields"]) == set(schema["properties"]) == PAYLOAD_FIELDS[command]
        assert set(registry["required_fields"]) == set(schema["required"])


def test_user_decision_propose_computes_digest_when_omitted() -> None:
    schema = _read("schemas/commands/user_decision/propose.schema.json")
    payload = _read("fixtures/valid/user-decision-propose.json")
    Draft202012Validator(schema).validate(payload)
    with_digest = {**payload, "proposal_digest": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"}
    Draft202012Validator(schema).validate(with_digest)


def test_user_decision_propose_allows_default_initial_revision() -> None:
    schema = _read("schemas/commands/user_decision/propose.schema.json")
    payload = _read("fixtures/valid/user-decision-propose.json")
    payload.pop("expected_revisions")
    Draft202012Validator(schema).validate(payload)


def test_user_decision_resolve_requires_id_and_digest_but_not_reason() -> None:
    schema = _read("schemas/commands/user_decision/resolve.schema.json")
    payload = _read("fixtures/valid/user-decision-resolve.json")
    Draft202012Validator(schema).validate(payload)
    for missing in ("decision_id", "proposal_digest"):
        invalid = dict(payload)
        invalid.pop(missing)
        try:
            Draft202012Validator(schema).validate(invalid)
        except ValidationError:
            pass
        else:
            raise AssertionError(f"missing {missing} was accepted")
