"""Host-neutral contracts for turning a durable delivery into a host turn."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

CapabilityStatus = Literal["supported", "unsupported", "unknown", "degraded"]
BindingStatus = Literal["ready", "degraded", "stale", "detached"]
WakeState = Literal[
    "received", "probing", "resuming", "starting", "queued", "running",
    "completed", "failed", "unknown",
]


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class HostBindingRef:
    """A secret-free reference to a host binding.

    Raw thread/session/endpoint values live in the adapter-owned private store.
    The project runtime only needs this digest-bearing reference to fence a wake
    request against a stale enrollment or changed policy.
    """

    binding_id: str
    agent_id: str
    provider: str
    adapter_profile: str
    thread_id_digest: str | None = None
    session_id_digest: str | None = None
    endpoint_kind: str = "unknown"
    cwd_digest: str | None = None
    scope_digest: str | None = None
    policy_digest: str | None = None
    status: BindingStatus = "degraded"
    binding_revision: int = 1
    connection_epoch: int | None = None
    capabilities: dict[str, CapabilityStatus] = field(default_factory=dict)
    last_probe: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HostWakeRequest:
    """The minimum information a provider needs to start a coordination turn."""

    wake_attempt_id: str
    agent_id: str
    message_id: str
    project_id: str | None
    binding: HostBindingRef
    prompt_kind: str = "pull_coordination_inbox"
    cwd_digest: str | None = None
    scope_digest: str | None = None
    policy_digest: str | None = None
    connection_epoch: int | None = None

    def validate(self) -> None:
        if not self.wake_attempt_id or not self.agent_id or not self.message_id:
            raise HostWakeError("host_wake_request_invalid", "wake request identifiers are required")
        if self.binding.agent_id != self.agent_id:
            raise HostWakeError("host_binding_agent_mismatch", "binding does not belong to the requested Agent")
        if self.prompt_kind != "pull_coordination_inbox":
            raise HostWakeError("host_prompt_kind_unsupported", "host wake only accepts the coordination pull prompt")
        for name, expected, actual in (
            ("cwd", self.cwd_digest, self.binding.cwd_digest),
            ("scope", self.scope_digest, self.binding.scope_digest),
            ("policy", self.policy_digest, self.binding.policy_digest),
        ):
            if expected is not None and actual is not None and expected != actual:
                raise HostWakeError(f"host_{name}_digest_mismatch", f"{name} digest does not match binding")
        if self.connection_epoch is not None and self.binding.connection_epoch is not None:
            if self.connection_epoch != self.binding.connection_epoch:
                raise HostWakeError("stale_connection_epoch", "host binding connection epoch is stale")


@dataclass(frozen=True, slots=True)
class ThreadHandle:
    thread_id: str
    session_id: str | None = None
    resumed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HostEvidence:
    kind: str
    wake_attempt_id: str
    agent_id: str
    message_id: str
    status: str
    evidence_digest: str
    observed_at: str = field(default_factory=utc_now)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WakeAttempt:
    wake_attempt_id: str
    agent_id: str
    message_id: str
    state: WakeState
    thread_id_digest: str | None = None
    turn_id_digest: str | None = None
    evidence: tuple[HostEvidence, ...] = ()
    error_code: str | None = None
    error_message: str | None = None
    updated_at: str = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class HostCapabilityReport:
    provider: str
    status: CapabilityStatus
    version: str | None
    transport: str
    methods: tuple[str, ...] = ()
    capabilities: dict[str, CapabilityStatus] = field(default_factory=dict)
    evidence_digest: str | None = None
    reason: str | None = None
    observed_at: str = field(default_factory=utc_now)


class HostWakeError(RuntimeError):
    """A safe, serializable adapter error; it never carries secrets."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class HostWakePort(Protocol):
    """Port implemented by managed and Desktop attach providers."""

    def probe(self, binding: HostBindingRef) -> HostCapabilityReport: ...

    def ensure_thread(self, binding: HostBindingRef) -> ThreadHandle: ...

    def wake(self, request: HostWakeRequest) -> WakeAttempt: ...

    def poll(self, wake_attempt_id: str) -> WakeAttempt | None: ...

    def inspect(self, binding: HostBindingRef) -> dict[str, Any]: ...

    def close(self, binding: HostBindingRef, reason: str) -> None: ...
