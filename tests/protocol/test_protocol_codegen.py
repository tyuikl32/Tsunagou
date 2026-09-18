import json
from pathlib import Path

from jsonschema import Draft202012Validator

from tsunagou.shared_kernel.digests import canonical_digest

ROOT = Path(__file__).resolve().parents[2]


def test_registry_has_schema_and_policy_for_every_command() -> None:
    registry = json.loads((ROOT / "protocol/registry/commands.json").read_text(encoding="utf-8"))
    assert len(registry["commands"]) >= 100
    for entry in registry["commands"].values():
        path = ROOT / "protocol/schemas" / entry["schema"]
        assert path.is_file()
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


def test_schema_digest_is_stable_and_fixture_rejects_actor() -> None:
    registry_path = ROOT / "protocol/registry/commands.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    commands = registry["commands"]
    digest = canonical_digest(commands)
    assert digest == registry["schema_bundle_digest"]
    json.loads(
        (ROOT / "protocol/fixtures/invalid/command-envelope-extra.json").read_text(encoding="utf-8")
    )
    assert "actor_id" not in {"command_id", "protocol_version", "schema_bundle_digest", "payload"}
