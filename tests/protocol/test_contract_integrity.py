import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[2]


def read(relative: str):
    return json.loads((ROOT / "protocol" / relative).read_text(encoding="utf-8"))


def test_contract_wire_fixtures_and_packaged_schema_agree() -> None:
    for name, relative in [
        ("contract-propose", "schemas/commands/contract/propose.schema.json"),
        ("contract-accept", "schemas/results/contract-accept.schema.json"),
    ]:
        Draft202012Validator(read(relative)).validate(read(f"fixtures/valid/{name}.json"))
        assert (ROOT / "protocol" / relative).read_bytes() == (ROOT / "src/tsunagou/protocol_data" / relative).read_bytes()


@pytest.mark.parametrize("participants", [
    [], ["worker"], [{"slot": "writer"}], [{"slot": " ", "agent_id": "worker"}],
    [{"slot": "writer", "agent_id": "\t"}], [{"slot": "writer", "agent_id": "worker", "id": "invented"}],
])
def test_contract_wire_rejects_incomplete_participants(participants) -> None:
    validator = Draft202012Validator(read("schemas/commands/contract/propose.schema.json"))
    with pytest.raises(ValidationError):
        validator.validate({"payload": {}, "participants_required": participants})


def test_proxy_result_requires_both_actual_identities() -> None:
    result = read("fixtures/valid/contract-accept.json")
    result.pop("represented_participant")
    with pytest.raises(ValidationError):
        Draft202012Validator(read("schemas/results/contract-accept.schema.json")).validate(result)
