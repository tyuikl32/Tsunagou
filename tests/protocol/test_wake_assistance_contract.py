import json
from pathlib import Path

from jsonschema import Draft202012Validator

from tsunagou.interfaces.runtime import PAYLOAD_FIELDS

ROOT = Path(__file__).resolve().parents[2]


def test_wake_assistance_payloads_are_message_scoped_and_never_accept_identity() -> None:
    registry = json.loads((ROOT / "protocol/registry/commands.json").read_text(encoding="utf-8"))
    for command, field in {"peer_hosts": None, "wake_candidates": "source_command_id",
                           "wake_status": "message_id", "wake": "message_id"}.items():
        kind = "coordination." + command
        entry = registry["commands"][kind]
        assert entry["principal"] == "B"
        schema_path = "schemas/commands/coordination/" + command + ".schema.json"
        schema = json.loads((ROOT / "protocol" / schema_path).read_text(encoding="utf-8"))
        assert schema == json.loads((ROOT / "src/tsunagou/protocol_data" / schema_path).read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        valid = {field: "opaque-reference"} if field else {}
        assert list(validator.iter_errors(valid)) == []
        assert PAYLOAD_FIELDS[kind] == set(valid)
        for name in ("agent_id", "sender_agent_id", "recipient_agent_id", "session_file", "endpoint", "command", "token"):
            assert list(validator.iter_errors({**valid, name: "forged"}))
        if field:
            for invalid in ({}, {field: ""}, {field: 1}):
                assert list(validator.iter_errors(invalid))
