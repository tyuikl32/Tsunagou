class TsunagouError(Exception):
    code = "tsunagou_error"


class ValidationError(TsunagouError):
    code = "schema_validation_failed"


class IdempotencyConflict(TsunagouError):
    code = "idempotency_conflict"


class RevisionConflict(TsunagouError):
    code = "revision_conflict"


class ResourceConflict(TsunagouError):
    code = "resource_conflict"

    def __init__(self, blockers: list[dict[str, str]]) -> None:
        super().__init__(self.code)
        self.blockers = blockers


class LockUnavailable(TsunagouError):
    code = "project_lock_unavailable"
