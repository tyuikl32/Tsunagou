"""Generated from protocol/schemas/queries/checkpoint-verification.schema.json; do not edit."""
# Source digest: sha256:d27582948655e2985553635e0c5f254df7679764f88e5698dc15313698838dae; generator: query-v1

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GitAnchorModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    ref_name: str = Field(min_length=1)
    commit_oid: str = Field(min_length=1)


class CheckpointVerificationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    digest: str = Field(min_length=1)
    status: Literal['verified']
    project_id: str | None
    lineage_id: str = Field(min_length=1)
    through_event_seq: int = Field(ge=0)
    created_at: str | None = Field(pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$')
    verified_at: str | None = Field(pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$')
    git_anchors: list[GitAnchorModel]
