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
    actor_id: str | None
    agent_id: str | None
    command_id: str | None
    task_id: str | None
    attempt_id: str | None
    message_id: str | None
    wake_attempt_id: str | None
    evidence_digest: str | None
    occurred_at: str | None = Field(pattern=_TIMESTAMP)
    recorded_at: str | None = Field(pattern=_TIMESTAMP)
    observed_at: str | None = Field(pattern=_TIMESTAMP)
    trigger_source: Literal["daemon_delivery", "user_followup", "developer_followup", "unknown"]
    error_code: str | None
    details: dict[str, str | int | None]


class DiagnosticPageModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    project_id: str = Field(min_length=1)
    items: list[DiagnosticEventModel]


class TimingElapsedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    elapsed_ms: int | None = Field(ge=0)
    clock_status: Literal["ok", "unknown", "clock_inconsistent"]


class AttemptTimingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    attempt_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    owner_agent_id: str = Field(min_length=1)
    state: str = Field(min_length=1)
    started_at: str | None = Field(pattern=_TIMESTAMP)
    submitted_at: str | None = Field(pattern=_TIMESTAMP)
    reviewed_at: str | None = Field(pattern=_TIMESTAMP)
    started_source: Literal["task_begin_event"] | None
    submitted_source: Literal["task_submit_event", "result_created_at"] | None
    reviewed_source: Literal["task_review_event"] | None
    begin_events: int = Field(ge=0)
    submit_events: int = Field(ge=0)
    review_action: Literal["task.review.accept", "task.review.request_changes"] | None
    work_elapsed: TimingElapsedModel
    review_wait_elapsed: TimingElapsedModel


class ProjectTimingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    project_id: str = Field(min_length=1)
    items: list[AttemptTimingModel]
