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
