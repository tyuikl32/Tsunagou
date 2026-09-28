import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from referencing import Registry, Resource
from tools.codegen.generate_audit import render_models

from tsunagou.api.app import create_app
from tsunagou.generated.protocol.delivery import CredentialDeliveryModel

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "protocol/schemas/queries/credential-delivery.schema.json"


def fixture() -> dict:
    return json.loads((ROOT / "protocol/fixtures/valid/credential-delivery.json").read_text(encoding="utf-8"))


def validator() -> Draft202012Validator:
    timestamp = json.loads((ROOT / "protocol/schemas/common/timestamp.schema.json").read_text(encoding="utf-8"))
    registry = Registry().with_resources([
        ("https://tsunagou.local/schema/common/timestamp.schema.json", Resource.from_contents(timestamp)),
    ])
    return Draft202012Validator(json.loads(SOURCE.read_text(encoding="utf-8")), registry=registry)


def test_safe_delivery_contract_matches_schema_and_openapi() -> None:
    value = fixture()
    validator().validate(value)
    assert CredentialDeliveryModel.model_validate(value).model_dump() == value
    route = create_app().openapi()["paths"]["/api/v1/credential-deliveries/{delivery_ref}/ack"]["post"]
    assert route["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/CredentialDeliveryModel")


@pytest.mark.parametrize(("field", "invalid"), [
    ("secret_token", "never-a-real-secret"), ("reconnect_nonce", "never-a-real-nonce"),
    ("delivery_ref", "delivery:../wrong"), ("delivery_status", "ready"),
    ("created_at", 1790528400123), ("created_at", "2026-09-27T17:00:00Z"),
])
def test_delivery_wire_rejects_secrets_bad_refs_and_ambiguous_time(field: str, invalid: object) -> None:
    value = copy.deepcopy(fixture())
    value[field] = invalid
    assert list(validator().iter_errors(value))
    with pytest.raises(ValidationError):
        CredentialDeliveryModel.model_validate(value)


def test_generated_delivery_models_and_packaged_schema_match() -> None:
    py, ts = render_models(SOURCE)
    assert py == (ROOT / "src/tsunagou/generated/protocol/delivery.py").read_text(encoding="utf-8")
    assert ts == (ROOT / "packages/protocol-ts/src/generated/delivery.ts").read_text(encoding="utf-8")
    assert SOURCE.read_bytes() == (ROOT / "src/tsunagou/protocol_data/schemas/queries" / SOURCE.name).read_bytes()
