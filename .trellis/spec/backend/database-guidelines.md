# Database and durability

Sources: [architecture](../../../docs/implementation/architecture.md), [durability](../../../docs/implementation/modules/07-durability.md), [data model](../../../docs/implementation/data-model.md).

Use per-project SQLite WAL, synchronous FULL, foreign_keys ON, one writer queue and OS lock. BEGIN IMMEDIATE wraps identity/epoch fencing, idempotency, policy/revision checks, domain writes, events, outbox and job creation. No HTTP, Git, user/Agent waits or filesystem materialization inside write transactions.

Every module owns its prefixed tables and migrations mark owner. IDs are UUIDv7 text; runtime_epoch is UUID, numeric epochs are safe integers. Enforce project/lineage on foreign references. Attempt identity/owner is immutable; status is an event-backed projection.

SQLite is current truth, not full event sourcing. Export by each module's port. File checkpoint materialization uses staging and atomic replacement with a separate watermark. Completion remains completed if its checkpoint fails. Operation outcome_unknown remains historical; append Resolution.

Test real SQLite, concurrent claims and process-crash windows. No broad mock-based claims of durability. No automatic finalized blob GC in v1.
