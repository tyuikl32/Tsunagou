"""Explicit resource reservations; elapsed time never transfers ownership."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from tsunagou.shared_kernel.digests import canonical_digest
from tsunagou.shared_kernel.errors import ResourceConflict
from tsunagou.shared_kernel.ids import new_id
from tsunagou.shared_kernel.time import now_ms


@dataclass(frozen=True, order=True, slots=True)
class ResourceKey:
    kind: str
    root_id: str | None = None
    segments: tuple[str, ...] = ()
    namespace: str | None = None
    name: str | None = None

    @classmethod
    def path(cls, root_id: str, *segments: str) -> ResourceKey:
        return cls("path", root_id=root_id, segments=tuple(part.casefold() for part in segments))

    @classmethod
    def named(cls, namespace: str, name: str) -> ResourceKey:
        return cls("named", namespace=namespace.casefold(), name=name.casefold())

    @property
    def canonical(self) -> str:
        if self.kind == "path":
            return "path:" + str(self.root_id) + ":" + "/".join(self.segments)
        return f"named:{self.namespace}:{self.name}"


@dataclass(frozen=True, slots=True)
class ResourceRequest:
    key: ResourceKey
    mode: str


@dataclass(slots=True)
class ResourceReservation:
    reservation_id: str
    task_id: str
    attempt_id: str
    owner_agent_id: str
    execution_epoch: int
    scope_digest: str
    resources: tuple[ResourceRequest, ...]
    created_at: int
    status: str = "active"
    released_at: int | None = None
    release_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ResourceObservation:
    resource_key: str
    source: str
    evidence_digest: str
    observed_at: float
    kind: str


class ResourceService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        # Root IDs are project semantics; physical identities are local
        # bindings.  Keep both so callers can still report the declared root
        # while conflict checks treat aliases as the same resource.
        self.root_aliases: dict[str, str] = {}
        self.reservations: dict[str, ResourceReservation] = {}
        self.observations: list[ResourceObservation] = []

    def set_root_aliases(self, aliases: dict[str, str]) -> None:
        with self._lock:
            self.root_aliases = {str(root_id): str(identity) for root_id, identity in aliases.items()}

    def check_conflicts(
        self, requests: list[ResourceRequest], *, attempt_id: str | None = None,
    ) -> list[str]:
        conflicts: list[str] = []
        for reservation in self.reservations.values():
            if reservation.status != "active" or reservation.attempt_id == attempt_id:
                continue
            for incoming in requests:
                for held in reservation.resources:
                    if self._conflict(incoming, held, self.root_aliases):
                        conflicts.append(held.key.canonical)
        return sorted(set(conflicts))

    def reserve_set(
        self, *, task_id: str, attempt_id: str, owner_agent_id: str,
        execution_epoch: int, scope_digest: str, requests: list[ResourceRequest],
    ) -> ResourceReservation | None:
        if not requests:
            return None
        keys = [request.key.canonical for request in requests]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate_resource_key")
        with self._lock:
            ordered = tuple(sorted(requests, key=lambda item: item.key.canonical))
            for existing in self.reservations.values():
                if existing.attempt_id == attempt_id and existing.status == "active":
                    if (existing.task_id != task_id or existing.owner_agent_id != owner_agent_id
                            or existing.execution_epoch != execution_epoch or existing.scope_digest != scope_digest
                            or existing.resources != ordered):
                        raise PermissionError("reservation_context_mismatch")
                    return existing
            conflicts = self.check_conflicts(requests, attempt_id=attempt_id)
            if conflicts:
                raise ResourceConflict([
                    {"resource_key": held.key.canonical, "reservation_id": existing.reservation_id,
                     "task_id": existing.task_id, "attempt_id": existing.attempt_id,
                     "owner_agent_id": existing.owner_agent_id}
                    for existing in self.reservations.values() if existing.status == "active"
                    for held in existing.resources
                    if any(self._conflict(incoming, held, self.root_aliases) for incoming in requests)
                ])
            reservation = ResourceReservation(
                new_id(), task_id, attempt_id, owner_agent_id, execution_epoch,
                scope_digest, ordered, now_ms(),
            )
            self.reservations[reservation.reservation_id] = reservation
            return reservation

    def release_for_attempt(self, attempt_id: str, *, reason: str = "attempt_left_running") -> int:
        with self._lock:
            count = 0
            for reservation in self.reservations.values():
                if reservation.attempt_id == attempt_id and reservation.status == "active":
                    reservation.status = "released"
                    reservation.released_at = now_ms()
                    reservation.release_reason = reason
                    count += 1
            return count

    def observe_external(self, key: ResourceKey, *, source: str, evidence: dict[str, Any], kind: str) -> ResourceObservation:
        observation = ResourceObservation(key.canonical, source, canonical_digest(evidence), time.time(), kind)
        with self._lock:
            self.observations.append(observation)
        return observation

    @staticmethod
    def _conflict(left: ResourceRequest, right: ResourceRequest, aliases: dict[str, str] | None = None) -> bool:
        if left.key.kind != right.key.kind:
            return False
        if left.key.kind == "named":
            return left.key == right.key and left.mode == "exclusive_use" and right.mode == "exclusive_use"
        aliases = aliases or {}
        left_root = aliases.get(str(left.key.root_id), str(left.key.root_id))
        right_root = aliases.get(str(right.key.root_id), str(right.key.root_id))
        if left_root != right_root:
            return False
        left_segments = left.key.segments
        right_segments = right.key.segments
        overlap = left_segments[: len(right_segments)] == right_segments or right_segments[: len(left_segments)] == left_segments
        if not overlap:
            return False
        if left.mode == "read" or right.mode == "read":
            return False
        return left.mode == "exclusive_write" or right.mode == "exclusive_write"
