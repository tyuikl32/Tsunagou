"""When a host can be woken: one declared capability, one honest report.

Every wake path in this repository used to be described only by *whether* it
exists. Nothing said **when** the reminder is read, so a caller could not tell
"the host will interrupt the running turn" from "the host will wait until the
turn ends" from "the host will not send anything while the session is busy".

This module is that missing dimension. It is deliberately host-neutral: the
vocabulary lives here, each provider declares what its host can actually do, and
:func:`plan_delivery` turns "what was asked", "what the host declares" and "what
was actually used" into one report that never claims more than the evidence.

Unknown is a real answer. A host whose busy behaviour has never been observed
reports ``unknown``, never the more flattering guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

# ``turn_boundary``  — read at the next turn boundary (DSH ``queue``, OpenCode ``delivery='queue'``).
# ``step``           — read at the running turn's next step boundary (DSH ``steer``).
# ``idle_only``      — not sent at all while the session is busy (Codex Desktop original conversation).
# ``none``           — no wake path exists at all (Claude Code, ZCode, any remote machine).
# ``unknown``        — a path exists, but nothing we can read says when it delivers.
DeliveryTiming = Literal["turn_boundary", "step", "idle_only", "none", "unknown"]

DELIVERY_TIMINGS: tuple[DeliveryTiming, ...] = ("turn_boundary", "step", "idle_only", "none", "unknown")

# What the host is doing, not who named it. Lower is "sent later or not at all".
_TIMING_ORDER: dict[str, int] = {
    "none": 0, "idle_only": 1, "turn_boundary": 2, "step": 3, "unknown": 2,
}

# The one host vocabulary that already exists, interpreted rather than replaced.
DEEPSEEK_WAKE_MODES: dict[str, DeliveryTiming] = {"queue": "turn_boundary", "steer": "step"}

# Human wording for the tool/caller surface. Kept next to the vocabulary so a new
# timing cannot be added without saying what it means to a reader.
TIMING_DESCRIPTION: dict[str, str] = {
    "turn_boundary": "the reminder is read at that session's next turn boundary (the running turn is not interrupted)",
    "step": "the reminder is read at the running turn's next step boundary; the turn continues and nothing in flight is cancelled",
    "idle_only": "the reminder is only delivered while that session is idle; while it is busy nothing is sent",
    "none": "this host has no wake path at all; the message stays in the inbox and that Agent must come and collect it",
    "unknown": "nothing readable here says when (or whether) the host delivers the reminder",
}

# Tool-surface vocabulary: the shape a caller may ask for once the protocol gains a
# per-message mode. ``coordination.wake`` accepts no such field today, so this is used
# only to judge a request that already exists, never to invent one.
REQUESTABLE_TIMINGS: tuple[str, ...] = ("turn_boundary", "step")


def timing_at_least(used: str, declared: str) -> bool:
    """Whether ``used`` delivers at least as early as ``declared`` claims.

    Used for exactly one judgement: a host that declared one timing and then
    delivered at a later one has degraded, and the caller must be told.
    """
    return _TIMING_ORDER.get(used, 0) >= _TIMING_ORDER.get(declared, 0)


def deepseek_timing_for_mode(mode: Any) -> DeliveryTiming:
    """The delivery timing the managed DSH plugin gets for one ``wake_mode``.

    The plugin admits a prompt with that mode; an unrecognised mode is a
    configuration error on the plugin side, so nothing is claimed here.
    """
    return DEEPSEEK_WAKE_MODES.get(mode, "unknown") if isinstance(mode, str) else "unknown"


@dataclass(frozen=True, slots=True)
class DeliveryPlan:
    """What was asked for, what the host has, and what the attempt actually used.

    ``declared`` is a capability statement; ``used`` is an observation. They are
    separate fields because they can disagree, and when they do the caller sees
    :attr:`degraded_from` rather than a silent downgrade.
    """

    requested: str | None
    declared: str
    used: str
    source: str
    degraded_from: str | None = None
    reason: str | None = None

    def to_public(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "requested": self.requested,
            "declared": self.declared,
            "used": self.used,
            "description": TIMING_DESCRIPTION.get(self.used, TIMING_DESCRIPTION["unknown"]),
            "source": self.source,
        }
        if self.degraded_from is not None:
            value["degraded"] = True
            value["degraded_from"] = self.degraded_from
            value["reason"] = self.reason
        return value


def _weaker(candidate: str, other: str) -> bool:
    return _TIMING_ORDER.get(candidate, 0) < _TIMING_ORDER.get(other, 0)


def plan_delivery(
    *,
    used: str = "unknown",
    declared: str = "unknown",
    requested: str | None = None,
    source: str = "unknown",
) -> DeliveryPlan:
    """Report the timing honestly, and say so when it is worse than it should be.

    Degradation is reported on two occasions, both explicit:

    * the caller asked for a timing the host does not have (``requested`` weaker
      than what was asked) — the request cannot be honoured as made;
    * the attempt delivered later than the host declared it would.
    """
    used_value = used if used in DELIVERY_TIMINGS else "unknown"
    declared_value = declared if declared in DELIVERY_TIMINGS else "unknown"
    requested_value = requested if requested in DELIVERY_TIMINGS else None
    if requested_value is not None and _weaker(used_value, requested_value):
        return DeliveryPlan(
            requested=requested_value, declared=declared_value, used=used_value, source=source,
            degraded_from=requested_value,
            reason=(f"the host delivered at {used_value} instead of the requested {requested_value}; "
                    f"{TIMING_DESCRIPTION.get(used_value, TIMING_DESCRIPTION['unknown'])}"),
        )
    if _weaker(used_value, declared_value):
        return DeliveryPlan(
            requested=requested_value, declared=declared_value, used=used_value, source=source,
            degraded_from=declared_value,
            reason=(f"the host declared {declared_value} but delivered at {used_value}; "
                    f"{TIMING_DESCRIPTION.get(used_value, TIMING_DESCRIPTION['unknown'])}"),
        )
    return DeliveryPlan(requested=requested_value, declared=declared_value, used=used_value, source=source)


def declared_timing(*values: Any) -> str:
    """The best timing a set of capability statements supports.

    Providers publish slightly different vocabularies (a method catalogue, one
    explicit timing); anything unrecognised contributes ``unknown`` rather than
    being read as a capability.
    """
    found = [value for value in values if isinstance(value, str) and value in DELIVERY_TIMINGS]
    if not found:
        return "unknown"
    return max(found, key=lambda value: _TIMING_ORDER.get(value, 0))
