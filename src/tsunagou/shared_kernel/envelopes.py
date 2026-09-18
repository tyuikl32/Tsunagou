from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CommandEnvelope:
    command_id: str
    protocol_version: str
    schema_bundle_digest: str
    payload: dict[str, Any]
    expected_revision: int | None = None
    attempt_id: str | None = None
    expected_execution_epoch: int | None = None


@dataclass(frozen=True, slots=True)
class CommandResult:
    command_id: str
    result: dict[str, Any]
    replayed: bool = False
    event_seq: int | None = None
    operation_id: str | None = None
