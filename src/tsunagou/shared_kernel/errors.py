from typing import Any


class TsunagouError(Exception):
    code = "tsunagou_error"


class ValidationError(TsunagouError):
    code = "schema_validation_failed"


class IdempotencyConflict(TsunagouError):
    code = "idempotency_conflict"


class RevisionConflict(TsunagouError):
    code = "revision_conflict"


class LockUnavailable(TsunagouError):
    code = "project_lock_unavailable"


class ResourceConflict(TsunagouError, ValueError):
    """A lease request that lost to a holder already in place.

    It is deliberately *also* a ``ValueError``: the HTTP layer already turns a
    structured ``ValueError`` into a rejection that carries the reason **and** records
    the refusal as a durable ``command.<kind>.denied`` event. Being turned away from a
    lease is a refusal, not an outage, so it must not be reported as one -- and "this
    attempt was turned away, by whom, and until when" is precisely the fact a later
    review, or the retrying agent itself, needs.
    """

    code = "resource_conflict"

    def __init__(
        self, conflicts: list[dict[str, Any]], *, requester: dict[str, Any] | None = None,
    ) -> None:
        keys = sorted({str(entry.get("held_key", "")) for entry in conflicts})
        # The message keeps its historical shape: callers and the bridge match on
        # "resource_conflict" and must keep working.
        super().__init__("resource_conflict:" + ",".join(keys))
        detail: dict[str, Any] = {"conflicts": conflicts}
        if requester is not None:
            detail["requester"] = requester
        self.detail = detail
