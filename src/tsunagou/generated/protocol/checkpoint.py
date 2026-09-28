"""Generated from protocol/schemas/queries/checkpoint-page.schema.json; do not edit."""
# Source digest: sha256:640023b3c48e8fc5991116e1b7449279c03bd448482d9d471dd07d056480b400; generator: query-v1

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CheckpointPointerModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    digest: str = Field(min_length=1)
    status: Literal['sealed', 'verified']
    through_event_seq: int = Field(ge=0)


class CheckpointSummaryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    digest: str = Field(min_length=1)
    parent_digest: str | None
    project_id: str | None
    lineage_id: str = Field(min_length=1)
    through_event_seq: int = Field(ge=0)
    format_version: int = Field(ge=1)
    schema_bundle_digest: str = Field(min_length=1)
    created_at: str | None = Field(pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$')
    created_by: str | None
    reason: str | None
    projection_version: str = Field(min_length=1)
    verified_at: str | None = Field(pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$')
    status: Literal['sealed', 'verified']
    artifact_digests: list[str]


class CheckpointPageModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    project_id: str = Field(min_length=1)
    current: CheckpointPointerModel | None
    items: list[CheckpointSummaryModel]
    projection_version: Literal['v1']
    as_of_event_seq: int = Field(ge=0)
