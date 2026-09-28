# Database and durability

Sources: [architecture](../../../docs/implementation/architecture.md), [durability](../../../docs/implementation/modules/07-durability.md), [data model](../../../docs/implementation/data-model.md).

Use per-project SQLite WAL, synchronous FULL, foreign_keys ON, one writer queue and OS lock. BEGIN IMMEDIATE wraps identity/epoch fencing, idempotency, policy/revision checks, domain writes, events, outbox and job creation. No HTTP, Git, user/Agent waits or filesystem materialization inside write transactions.

Every module owns its prefixed tables and migrations mark owner. IDs are UUIDv7 text; runtime_epoch is UUID, numeric epochs are safe integers. Enforce project/lineage on foreign references. Attempt identity/owner is immutable; status is an event-backed projection.

SQLite is current truth, not full event sourcing. Export by each module's port. File checkpoint materialization uses staging and atomic replacement with a separate watermark. Completion remains completed if its checkpoint fails. Operation outcome_unknown remains historical; append Resolution.

Test real SQLite, concurrent claims and process-crash windows. No broad mock-based claims of durability. No automatic finalized blob GC in v1.

Close every temporary SQLite read connection explicitly (for example, `contextlib.closing`). A SQLite connection's own `with` block commits or rolls back transactions but does not close its file handles; do not depend on garbage collection to release Windows database/WAL files.

Credential migrations must fence startup before opening a writer or restoring authority: an absent or previously completed migration marker does not prove a legacy/restored database is safe. Inspect historical credential results and old plaintext escrow read-only; require explicit offline revocation before loading them. A completed migration replay may return its receipt only while the current database remains safe. Reconcile quarantine inventory from durable copied files after a copy/unlink/marker crash, and preserve the private backup as revoked historical evidence, never a runnable rollback.

Bridge credential session files require an interprocess compare/save boundary, not only atomic rename: a slow response can otherwise overwrite a newer connection epoch after passing an earlier read check. The bridge uses a process-owned loopback bind mutex for its short synchronous prepare and finalize sections; HTTP/ACK run outside it. Port collisions fail busy/retry, and process exit releases the lock. ACK metadata is separate from the credential file so a late ACK cannot rewrite a newer session.

Ticket replacement in the Python CLI and ticket digest-check/unlink in the Node bridge share the same canonical-path mutex algorithm. Acquire the ticket mutex only after releasing the session mutex; two path hashes may map to the same port. Windows private ACL setup replaces the complete protected DACL with the current user SID, including for an existing vault directory; granting that SID alone must not leave pre-existing explicit Everyone/Users ACEs. Apply ACLs before any credential bytes, including `control.token`.
