from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError
from tools.codegen import generate_protocol

from tsunagou.interfaces.runtime import PAYLOAD_FIELDS

ROOT = Path(__file__).resolve().parents[2]
COMMANDS = ("message.send", "message.respond", "inbox.claim", "inbox.fetch", "inbox.presented", "inbox.ack")


def read(relative: str):
    return json.loads((ROOT / "protocol" / relative).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", COMMANDS)
def test_message_fixtures_match_catalog_runtime_and_packaged_schema(name):
    relative = f"schemas/commands/{name.replace('.', '/')}.schema.json"
    fixture = f"fixtures/valid/{name.replace('.', '-')}.json"
    schema = read(relative)
    Draft202012Validator(schema).validate(read(fixture))
    for path in (relative, fixture):
        assert (ROOT / "protocol" / path).read_bytes() == (ROOT / "src/tsunagou/protocol_data" / path).read_bytes()
    assert (ROOT / "protocol" / relative).read_bytes() == (ROOT / "packages/bridge-server/protocol" / relative).read_bytes()
    registry = read("registry/commands.json")["commands"][name]
    assert set(registry["payload_fields"]) == set(schema["properties"]) == PAYLOAD_FIELDS[name]
    assert set(registry["required_fields"]) == set(schema["required"])


def test_table_parser_preserves_escaped_pipe_and_following_fields(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.md"
    catalog.write_text(
        "| command | URI | permission | payload | result |\n"
        "|---|---|---|---|---|\n"
        r"| message.send | `/messages` | B / message.send | kind:notification\|request,recipient_agent_id,summary,payload? | message |"
        "\n", encoding="utf-8",
    )
    monkeypatch.setattr(generate_protocol, "CATALOG", catalog)
    command = generate_protocol.extract_commands()["message.send"]
    assert command["payload_fields"] == ["kind", "payload", "recipient_agent_id", "summary"]
    assert command["required_fields"] == ["kind", "recipient_agent_id", "summary"]


@pytest.mark.parametrize("name,payload", [
    ("message.send", {"recipient_ids": ["worker"], "summary": "unsupported plural receiver"}),
    ("message.send", {"recipient_agent_id": "worker"}),
    ("message.send", {"recipient_agent_id": "worker", "summary": "", "payload": {}}),
    ("message.send", {"recipient_agent_id": "worker", "summary": "ok", "sender_agent_id": "forged"}),
    ("message.respond", {"obligation_id": "o", "response_payload": {"status": "done"}}),
    ("inbox.claim", {"max_bytes": 1000}),
    ("inbox.claim", {"limit": 201}),
    ("inbox.fetch", {"delivery_lease_id": "m"}),
    ("inbox.fetch", {"message_id": "m", "delivery_lease_id": "other"}),
    ("inbox.presented", {"evidence_digest": "digest-without-message"}),
    ("inbox.ack", {"reason": "missing-message"}),
])
def test_message_schemas_reject_unsupported_fields_and_missing_required_values(name, payload):
    schema = read(f"schemas/commands/{name.replace('.', '/')}.schema.json")
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(payload)


def test_optional_message_fields_match_actual_defaults():
    Draft202012Validator(read("schemas/commands/message/send.schema.json")).validate({
        "recipient_agent_id": "worker", "summary": "minimal message",
    })
    Draft202012Validator(read("schemas/commands/inbox/claim.schema.json")).validate({})
    Draft202012Validator(read("schemas/commands/inbox/presented.schema.json")).validate({"message_id": "m"})
    Draft202012Validator(read("schemas/commands/inbox/ack.schema.json")).validate({"message_id": "m"})
