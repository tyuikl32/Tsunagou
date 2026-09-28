import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from referencing import Registry, Resource
from tools.codegen.generate_audit import render_models

from tsunagou.generated.protocol.audit import AuditPageModel
from tsunagou.generated.protocol.checkpoint import CheckpointPageModel
from tsunagou.generated.protocol.checkpoint_verification import CheckpointVerificationModel

ROOT = Path(__file__).resolve().parents[2]


def _validator() -> Draft202012Validator:
    schema = json.loads((ROOT / "protocol/schemas/queries/audit-page.schema.json").read_text(encoding="utf-8"))
    timestamp = json.loads((ROOT / "protocol/schemas/common/timestamp.schema.json").read_text(encoding="utf-8"))
    registry = Registry().with_resources([
        ("https://tsunagou.local/schema/common/timestamp.schema.json", Resource.from_contents(timestamp)),
    ])
    return Draft202012Validator(schema, registry=registry)


def _fixture() -> dict:
    return json.loads((ROOT / "protocol/fixtures/valid/audit-page.json").read_text(encoding="utf-8"))


def test_known_and_unknown_times_validate_in_schema_and_python() -> None:
    value = _fixture()
    _validator().validate(value)
    assert AuditPageModel.model_validate(value).model_dump() == value
    assert value["items"][1]["occurred_at"] is None
    assert value["items"][1]["evidence_level"] is None


@pytest.mark.parametrize(("field", "invalid"), [
    ("occurred_at", "2026-09-27T16:00:00Z"),
    ("occurred_at", "2026-09-27T09:00:00.000-07:00"),
    ("occurred_at", 1790524800000),
    ("event_seq", True),
    ("revision_after", -1),
    ("evidence_level", "verified_by_agent"),
    ("secret_token", "fixture-never-usable"),
])
def test_wire_contract_rejects_ambiguous_times_and_unregistered_evidence(field: str, invalid: object) -> None:
    value = copy.deepcopy(_fixture())
    value["items"][0][field] = invalid
    assert list(_validator().iter_errors(value))
    with pytest.raises(ValidationError):
        AuditPageModel.model_validate(value)


def test_packaged_schema_and_generated_models_are_current() -> None:
    py, ts = render_models()
    assert py == (ROOT / "src/tsunagou/generated/protocol/audit.py").read_text(encoding="utf-8")
    assert ts == (ROOT / "packages/protocol-ts/src/generated/audit.ts").read_text(encoding="utf-8")
    for relative in ("schemas/queries/audit-page.schema.json", "schemas/common/timestamp.schema.json"):
        assert (ROOT / "protocol" / relative).read_bytes() == (ROOT / "src/tsunagou/protocol_data" / relative).read_bytes()


def test_audit_openapi_uses_canonical_dto_and_limits() -> None:
    from tsunagou.api.app import create_app

    spec = create_app().openapi()
    route = spec["paths"]["/api/v1/projects/{project_id}/audit"]["get"]
    assert route["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/AuditPageModel")
    params = {p["name"]: p["schema"] for p in route["parameters"]}
    assert params["limit"]["maximum"] == 200
    assert params["limit"]["minimum"] == 1
    assert params["cursor"]["anyOf"][0]["type"] == "string"


def test_checkpoint_query_models_are_generated_and_strict() -> None:
    page = {
        "project_id": "project-1", "current": None, "items": [],
        "projection_version": "v1", "as_of_event_seq": 0,
    }
    assert CheckpointPageModel.model_validate(page).model_dump() == page
    verification = {
        "digest": "sha256:checkpoint", "status": "verified", "project_id": "project-1",
        "lineage_id": "lineage-1", "through_event_seq": 0,
        "created_at": None, "verified_at": None, "git_anchors": [],
    }
    assert CheckpointVerificationModel.model_validate(verification).model_dump() == verification
    for source, generated_py, generated_ts in (
        ("checkpoint-page.schema.json", "checkpoint.py", "checkpoint.ts"),
        ("checkpoint-verification.schema.json", "checkpoint_verification.py", "checkpoint_verification.ts"),
    ):
        py, ts = render_models(ROOT / "protocol/schemas/queries" / source)
        assert py == (ROOT / "src/tsunagou/generated/protocol" / generated_py).read_text(encoding="utf-8")
        assert ts == (ROOT / "packages/protocol-ts/src/generated" / generated_ts).read_text(encoding="utf-8")
        assert (ROOT / "src/tsunagou/protocol_data/schemas/queries" / source).read_bytes() == (
            ROOT / "protocol/schemas/queries" / source
        ).read_bytes()
