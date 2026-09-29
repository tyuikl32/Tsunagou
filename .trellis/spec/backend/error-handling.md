# Errors and retries

Source: [protocol](../../../docs/implementation/protocol.md) and [lifecycle](../../../docs/implementation/lifecycle.md).

Domain errors are typed values with stable machine codes. Transport renders RFC 9457 Problem; MCP structured error carries identical details. Human text is not control input. Preserve revision_conflict, stale_epoch, scope_denied, user_only, action_blocked and resource_conflict distinctions.

A duplicate command_id with the same semantic hash replays the original result after current identity fencing; a different hash conflicts. Do not re-run external effects blindly. Job handlers declare pure/idempotent/reconcilable/unverifiable; ambiguous unverifiable effects become outcome_unknown.

UserDecision and resource reservations have no timeout. Internal Job deadlines must not turn user silence into rejection or transfer task ownership. Return scoped blockers and remediation without leaking other projects or private recipients. Resource conflicts return 409 with the held owner/task/attempt/resource. No secret inputs in validation errors.
