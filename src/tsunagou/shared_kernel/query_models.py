"""Strict DTOs shared by the read-only HTTP and CLI query surfaces."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tsunagou.generated.protocol.audit import AuditEventModel
from tsunagou.generated.protocol.checkpoint import (
    CheckpointPageModel,
    CheckpointPointerModel,
    CheckpointSummaryModel,
)
from tsunagou.generated.protocol.checkpoint_verification import (
    CheckpointVerificationModel,
    GitAnchorModel,
)

_TIMESTAMP = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$"

__all__ = [
    "AuditExportModel", "CheckpointPageModel", "CheckpointPointerModel", "CheckpointSummaryModel",
    "CheckpointVerificationModel", "GitAnchorModel",
]


class AuditExportSourceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    project_id: str = Field(min_length=1)
    lineage_id: str = Field(min_length=1)


class AuditExportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_name: Literal["tsunagou.audit-export.v1"] = Field(alias="schema")
    exported_at: str = Field(pattern=_TIMESTAMP)
    source: AuditExportSourceModel
    projection_version: str = Field(min_length=1)
    as_of_event_seq: int = Field(ge=0)
    next_cursor: str | None = Field(max_length=2048)
    items: list[AuditEventModel] = Field(max_length=200)


class DiagnosticEventModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    diagnostic_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    project_id: str | None
    agent_id: str = Field(min_length=1)
    message_id: str = Field(min_length=1)
    wake_attempt_id: str | None
    evidence_digest: str | None
    observed_at: str = Field(pattern=_TIMESTAMP)
    details: dict[str, str | int | None]


class DiagnosticPageModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    project_id: str = Field(min_length=1)
    items: list[DiagnosticEventModel]
