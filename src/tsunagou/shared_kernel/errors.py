from typing import Any


class TsunagouError(Exception):
    code = "tsunagou_error"


class ValidationError(TsunagouError):
    code = "schema_validation_failed"


class IdempotencyConflict(TsunagouError):
    code = "idempotency_conflict"


class RevisionConflict(TsunagouError):
    code = "revision_conflict"


class CommandRefused(TsunagouError, ValueError):
    """A command the domain refuses, together with the facts the person needs to act.

    ``code`` says what happened; ``detail`` carries the evidence (the tasks still in
    somebody's hands, the machine a retired Agent lives on). The HTTP layer answers 409
    with ``{code, …detail}``, so the page can show the list instead of inventing a
    sentence of its own. It is also a ``ValueError``: a refusal is recorded as a refusal,
    not reported as an outage.
    """

    def __init__(self, code: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail = dict(detail or {})


class ResourceConflict(TsunagouError, ValueError):
    """A reservation request that lost to a holder already in place.

    It carries **both** shapes the two callers in this tree expect:

    * ``blockers`` — what the holder list is called on the way *out* (the HTTP layer
      answers 409 with ``{code, blockers}``);
    * ``detail`` — ``{conflicts, requester}``, which is what the command route turns
      into a durable ``command.<kind>.denied`` event, and therefore what the console's
      conflict ledger reads back.

    It is deliberately *also* a ``ValueError``: a structured rejection is recorded as a
    refusal (409) rather than reported as an outage, and "this attempt was turned away,
    by whom" is exactly the fact a later review needs.
    """

    code = "resource_conflict"

    def __init__(
        self, blockers: list[dict[str, Any]], *, requester: dict[str, Any] | None = None,
    ) -> None:
        # Both spellings of "the key that was already held" have lived here: the older
        # ``held_key`` rows and the reservation-era ``resource_key`` rows.
        keys = sorted({
            str(entry.get("held_key") or entry.get("resource_key") or "") for entry in blockers
        })
        # The message keeps its historical shape: callers and the bridge match on
        # "resource_conflict".
        super().__init__("resource_conflict:" + ",".join(keys))
        self.blockers = blockers
        detail: dict[str, Any] = {"conflicts": blockers}
        if requester is not None:
            detail["requester"] = requester
        self.detail = detail


class LockUnavailable(TsunagouError):
    code = "project_lock_unavailable"
