"""Host-neutral contracts for turning a durable delivery into a host turn."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from tsunagou.shared_kernel.time import format_timestamp, now_ms

CapabilityStatus = Literal["supported", "unsupported", "unknown", "degraded"]
BindingStatus = Literal["ready", "degraded", "stale", "detached"]
WakeState = Literal[
    "received", "probing", "resuming", "starting", "queued", "running",
    "completed", "failed", "unknown",
]


def utc_now() -> str:
    return str(format_timestamp(now_ms()))


class CombinedBindingStore:
    """Several binding stores behind the **one** lookup ``WakeDispatcher`` performs.

    The dispatcher asks exactly one question -- "is there a usable binding for this
    Agent?" -- through ``provider.store``. A host registry that routes to more than one
    lane therefore has to answer that question for every lane, not just for the one that
    happened to be passed first.

    That is not a nicety: when the registry's ``store`` was a plain attribute holding only
    the Codex store, a lane added afterwards was invisible to the dispatcher and every
    delivery for it ended as ``host_binding_not_found`` -- the provider itself answered
    ``ready`` for the same Agent. That is the dead-channel symptom 待改 12 removed, and it
    reproduced live on 2026-10-10 while wiring DSH, so the merge lives here (host-neutral,
    in the layer both the Codex registry and the DSH store already depend on) instead of
    depending on a caller remembering to reassign an attribute.

    Nothing is merged into the members' own files: each store keeps owning its bindings,
    and a miss everywhere is still a miss (which is what keeps an unbound Agent
    fail-closed).
    """

    def __init__(self, *stores: Any) -> None:
        self.stores = stores

    def get(self, agent_id: str) -> tuple[HostBindingRef, dict[str, Any]] | None:
        for store in self.stores:
            getter = getattr(store, "get", None)
            item = getter(agent_id) if callable(getter) else None
            if item is not None:
                return item
        return None

    def list_refs(self) -> list[HostBindingRef]:
        refs: list[HostBindingRef] = []
        for store in self.stores:
            lister = getattr(store, "list_refs", None)
            if callable(lister):
                refs.extend(lister())
        return refs

    def update_status(self, agent_id: str, status: str, *, reason: str | None = None) -> HostBindingRef:
        for store in self.stores:
            getter = getattr(store, "get", None)
            if not callable(getter) or getter(agent_id) is None:
                continue
            updater = getattr(store, "update_status", None)
            if callable(updater):
                return updater(agent_id, status, reason=reason)
        raise KeyError("host_binding_not_found")


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
    pending_count: int | None = None
    oldest_pending_seconds: int | None = None

    @property
    def waiting_hint(self) -> str | None:
        """How much is waiting, in counts and ages only.

        The host boundary may learn *that* something waits, never *what*: bodies stay
        behind the authenticated pull. This is "the doorbell may ring, but the news stays
        in the inbox" expressed in code.
        """

        if not self.pending_count:
            return None
        if self.oldest_pending_seconds is None:
            return f"{self.pending_count} coordination message(s) are waiting for you."
        seconds = max(0, self.oldest_pending_seconds)
        age = f"{seconds // 60} min" if seconds >= 60 else f"{seconds} s"
        return (f"{self.pending_count} coordination message(s) are waiting for you; "
                f"the oldest has been waiting {age}.")

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
    # When this attempt's reminder is (or will be) read. ``{}`` means the provider
    # observed nothing, which is reported as ``unknown`` rather than assumed.
    # ``delivery_timing`` is only an annotation: see ``_serialize`` in the dispatcher.
    delivery: dict[str, Any] = field(default_factory=dict)


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
    # The "when is it delivered" dimension, kept out of ``capabilities`` because that
    # mapping is a method catalogue (``wake`` / ``turn/start``) that the dispatcher
    # acts on. Values come from ``hostwake.timing.DELIVERY_TIMINGS``.
    delivery_timing: str = "unknown"
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
