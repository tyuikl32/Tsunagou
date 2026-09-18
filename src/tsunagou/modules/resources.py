"""Resource intents, deterministic conflict checking, and execution leases."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from tsunagou.shared_kernel.digests import canonical_digest
from tsunagou.shared_kernel.ids import new_id


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
class ResourceIntent:
    intent_id: str
    task_id: str
    attempt_id: str
    owner_agent_id: str
    scope_digest: str
    resources: tuple[ResourceRequest, ...]
    reason: str
    revision: int = 1


@dataclass(slots=True)
class LeaseSet:
    lease_set_id: str
    attempt_id: str
    execution_epoch: int
    scope_digest: str
    request_digest: str
    resources: tuple[ResourceRequest, ...]
    status: str = "active"
    expires_at: float = 0.0
    last_renewed_at: float = 0.0


@dataclass(frozen=True, slots=True)
class ResourceObservation:
    resource_key: str
    source: str
    evidence_digest: str
    observed_at: float
    kind: str


class ResourceService:
    def __init__(self, *, ttl_seconds: int = 120) -> None:
        self.ttl_seconds = ttl_seconds
        self._lock = threading.RLock()
        self.intents: dict[str, ResourceIntent] = {}
        self.lease_sets: dict[str, LeaseSet] = {}
        self.observations: list[ResourceObservation] = []
        self.waiting: list[tuple[float, str]] = []

    def declare_intent(
        self, *, task_id: str, attempt_id: str, owner_agent_id: str,
        scope_digest: str, resources: list[ResourceRequest], reason: str,
    ) -> ResourceIntent:
        if not resources:
            raise ValueError("resource_intent_empty")
        keys = [request.key.canonical for request in resources]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate_resource_key")
        intent = ResourceIntent(new_id(), task_id, attempt_id, owner_agent_id, scope_digest, tuple(resources), reason)
        with self._lock:
            self.intents[intent.intent_id] = intent
        return intent

    def check_conflicts(
        self, requests: list[ResourceRequest], *, attempt_id: str | None = None,
        now: float | None = None,
    ) -> list[str]:
        now = time.time() if now is None else now
        conflicts: list[str] = []
        for lease in self.lease_sets.values():
            if lease.status != "active" or lease.expires_at <= now or lease.attempt_id == attempt_id:
                continue
            for incoming in requests:
                for held in lease.resources:
                    if self._conflict(incoming, held):
                        conflicts.append(held.key.canonical)
        return sorted(set(conflicts))

    def reserve_set(
        self, intent_id: str, *, execution_epoch: int, attempt_status: str = "running",
        now: float | None = None,
    ) -> LeaseSet:
        if attempt_status not in {"claimed", "running"}:
            raise ValueError("blocked_attempt_has_no_execution_lease")
        now = time.time() if now is None else now
        with self._lock:
            intent = self.intents[intent_id]
            conflicts = self.check_conflicts(list(intent.resources), attempt_id=intent.attempt_id, now=now)
            if conflicts:
                self.waiting.append((now, intent_id))
                raise RuntimeError("resource_conflict:" + ",".join(conflicts))
            ordered = tuple(sorted(intent.resources, key=lambda item: item.key.canonical))
            lease = LeaseSet(
                new_id(), intent.attempt_id, execution_epoch, intent.scope_digest,
                canonical_digest({"intent_id": intent_id, "revision": intent.revision}), ordered,
                expires_at=now + self.ttl_seconds, last_renewed_at=now,
            )
            self.lease_sets[lease.lease_set_id] = lease
            return lease

    def renew(
        self, lease_set_id: str, *, attempt_id: str, execution_epoch: int,
        scope_digest: str, now: float | None = None,
    ) -> LeaseSet:
        now = time.time() if now is None else now
        with self._lock:
            lease = self.lease_sets.get(lease_set_id)
            if lease is None or lease.status != "active":
                raise ValueError("lease_not_active")
            if lease.expires_at <= now:
                lease.status = "expired"
                raise ValueError("lease_expired")
            if lease.attempt_id != attempt_id or lease.execution_epoch != execution_epoch or lease.scope_digest != scope_digest:
                raise PermissionError("stale_execution_epoch_or_scope")
            lease.last_renewed_at = now
            lease.expires_at = now + self.ttl_seconds
            return lease

    def release_for_attempt(self, attempt_id: str, *, reason: str = "attempt_left_running") -> int:
        with self._lock:
            count = 0
            for lease in self.lease_sets.values():
                if lease.attempt_id == attempt_id and lease.status == "active":
                    lease.status = "released"
                    count += 1
            return count

    def expire_due(self, *, now: float | None = None) -> list[str]:
        now = time.time() if now is None else now
        expired: list[str] = []
        with self._lock:
            for lease in self.lease_sets.values():
                if lease.status == "active" and lease.expires_at <= now:
                    lease.status = "expired"
                    expired.append(lease.lease_set_id)
            return expired

    def observe_external(self, key: ResourceKey, *, source: str, evidence: dict[str, Any], kind: str) -> ResourceObservation:
        observation = ResourceObservation(key.canonical, source, canonical_digest(evidence), time.time(), kind)
        with self._lock:
            self.observations.append(observation)
        return observation

    def next_waiting(
        self, *, now: float | None = None, base_priority: dict[str, int] | None = None,
    ) -> ResourceIntent | None:
        """Return the fairest waiting intent; callers still must explicitly reserve/start it."""
        now = time.time() if now is None else now
        base_priority = base_priority or {}
        with self._lock:
            candidates = [
                (enqueued_at, intent_id) for enqueued_at, intent_id in self.waiting
                if intent_id in self.intents
            ]
            if not candidates:
                return None
            candidates.sort(
                key=lambda item: (
                    -min(3, base_priority.get(item[1], 0) + int(max(0, now - item[0]) // 300)),
                    item[0], item[1],
                )
            )
            return self.intents[candidates[0][1]]

    @staticmethod
    def _conflict(left: ResourceRequest, right: ResourceRequest) -> bool:
        if left.key.kind != right.key.kind:
            return False
        if left.key.kind == "named":
            return left.mode == "exclusive_use" and right.mode == "exclusive_use"
        if left.key.root_id != right.key.root_id:
            return False
        left_segments = left.key.segments
        right_segments = right.key.segments
        overlap = left_segments[: len(right_segments)] == right_segments or right_segments[: len(left_segments)] == left_segments
        if not overlap:
            return False
        if left.mode == "read" or right.mode == "read":
            return False
        return left.mode in {"consistent_read", "exclusive_write"} or right.mode in {"consistent_read", "exclusive_write"}
