"""Generated from protocol/registry/commands.json; do not edit."""

from pydantic import BaseModel, ConfigDict, Field


class CommandEnvelopeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command_id: str
    protocol_version: str
    schema_bundle_digest: str
    payload: dict[str, object] = Field(default_factory=dict)
