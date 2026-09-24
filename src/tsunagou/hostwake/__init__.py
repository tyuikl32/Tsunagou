"""Host wake adapters used by the A2A delivery boundary.

The package is intentionally independent from the task state machine.  A host
adapter may start a new turn, but it can only do so with an already enrolled
Agent binding and a caller-provided policy/scope snapshot.
"""

from tsunagou.hostwake.binding import PrivateBindingStore
from tsunagou.hostwake.codex_app_server import (
    CodexAppServerClient,
    DesktopAttachProvider,
    HostWakeProviderRegistry,
    ManagedCodexProvider,
    UnixWebSocketAppServerClient,
)
from tsunagou.hostwake.dispatcher import WakeDispatcher
from tsunagou.hostwake.port import (
    HostBindingRef,
    HostCapabilityReport,
    HostEvidence,
    HostWakeError,
    HostWakePort,
    HostWakeRequest,
    ThreadHandle,
    WakeAttempt,
)

__all__ = [
    "CodexAppServerClient",
    "DesktopAttachProvider",
    "HostBindingRef",
    "HostCapabilityReport",
    "HostEvidence",
    "HostWakeError",
    "HostWakePort",
    "HostWakeRequest",
    "ManagedCodexProvider",
    "HostWakeProviderRegistry",
    "UnixWebSocketAppServerClient",
    "PrivateBindingStore",
    "WakeDispatcher",
    "ThreadHandle",
    "WakeAttempt",
]
