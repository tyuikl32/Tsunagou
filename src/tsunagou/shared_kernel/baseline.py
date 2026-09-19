"""The common host capability contract shared by admission and release gates."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Capabilities a host/bridge can prove before enrollment, via a native probe and
# an adapter installation self-check. These gate whether a session becomes ready;
# a ready session may then do the business work that produces the operational rows.
ADMISSION_CAPABILITIES = (
    "identity.session_isolation",
    "identity.continuity_evidence",
    "context.project_read",
    "command.typed_tools",
)

# Capabilities that can only be proven by a ready session doing real work. They
# feed the release gate (and the full baseline digest), never session admission.
OPERATIONAL_CAPABILITIES = (
    "task.lifecycle",
    "cognition.report",
    "contract.participation",
    "inbox.pull_fetch_ack",
    "response.structured",
    "recovery.idempotent_reconnect",
    "delivery.deduplicate",
)

BASELINE_CAPABILITIES = ADMISSION_CAPABILITIES + OPERATIONAL_CAPABILITIES


def _missing(evidence: Mapping[str, Any], names: tuple[str, ...]) -> tuple[str, ...]:
    """A boolean or a status without references is never admission evidence."""
    rows = evidence.get("baseline")
    if not isinstance(rows, Mapping):
        return names
    return tuple(
        name for name in names
        if not (
            isinstance(rows.get(name), Mapping)
            and rows[name].get("status") == "supported"
            and isinstance(rows[name].get("evidence_refs"), list)
            and bool(rows[name]["evidence_refs"])
            and all(isinstance(ref, str) and bool(ref.strip()) for ref in rows[name]["evidence_refs"])
        )
    )


def missing_baseline_capabilities(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    """All 11 capabilities; used by the release gate, not by session admission."""
    return _missing(evidence, BASELINE_CAPABILITIES)


def missing_admission_capabilities(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    """The 4 pre-enrollment capabilities that gate session readiness."""
    return _missing(evidence, ADMISSION_CAPABILITIES)
