"""Generated from protocol/schemas/queries/audit-page.schema.json; do not edit."""
# Source digest: sha256:414ad447ce045e89d52ddcef2bb4b0f6adb1db8d3738b34697e03b3e0c2c6358; generator: query-v1

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AuditChangeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    subject_ref: str = Field(min_length=1)
    change_kind: Literal['created', 'updated', 'deleted']
    state_before: str | None
    state_after: str | None
    revision_before: int | None = Field(ge=0)
    revision_after: int | None = Field(ge=0)
    revision_source: Literal['domain', 'audit_observation']
    created_at: str | None = Field(pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$')
    updated_at: str | None = Field(pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$')


class AuditEventModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    event_id: str = Field(min_length=1)
    event_seq: int = Field(ge=1)
    source_event_id: str = Field(min_length=1)
    source_event_seq: int = Field(ge=1)
    project_id: str = Field(min_length=1)
    lineage_id: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    projection_version: str = Field(min_length=1)
    actor_ref: str = Field(min_length=1)
    actor_session_id: str | None
    subject_ref: str = Field(min_length=1)
    action: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    reason_code: str | None
    evidence_refs: list[str]
    occurred_at: str | None = Field(pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$')
    recorded_at: str | None = Field(pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$')
    caused_by_command_id: str | None
    revision_before: int | None = Field(ge=0)
    revision_after: int | None = Field(ge=0)
    evidence_level: Literal['agent_asserted', 'host_observed', 'system_verified', 'user_confirmed', None]
    changes: list[AuditChangeModel]


class AuditPageModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    project_id: str = Field(min_length=1)
    items: list[AuditEventModel] = Field(max_length=200)
    next_cursor: str | None = Field(max_length=2048)
    projection_version: Literal['v1']
    as_of_event_seq: int = Field(ge=0)
    snapshot_event_seq: int = Field(ge=0)
