# Standalone runtime repair contract

## 1. Scope / Trigger

Apply to R1–R6 changes in bootstrap, CLI, HTTP, dispatcher, repositories or workflow wiring. Source: [implementation plan](../../../docs/standalone/implementation-plan.md), [runtime audit](../../../docs/standalone/status-and-gaps.md), [D183](../../../docs/decisions/2026-09-20-standalone-priority.md). This is the current M1 runtime contract; delivered behavior is evidenced in `docs/standalone/`, and remaining gaps stay tracked by the active R1-R6 tasks until their acceptance evidence is recorded.

## 2. Signatures

- Existing diagnostic: `python tools/dev/audit_standalone.py [--output <path>]`.
- Writes: `handle(command: TypedCommand, ctx: PrincipalContext, uow: UnitOfWork) -> CommandResult`.
- Reads: `query(query: TypedQuery, ctx: PrincipalContext, read: ReadSnapshot) -> TypedView`.
- CLI is an HTTP client of the running daemon; it must not instantiate a separate application for business writes.

## 3. Contracts

Project SQLite is the sole live fact store. All participating domain writes, grants, leases, events and idempotency records share one transaction. Validate actor/owner/revisions before mutation; recheck current authorization before serving cached results. Attempt ownership is immutable. Block/resume require current owner; resume cannot create a foreign owner's replacement Attempt.

Package protocol files as distribution resources and read them with importlib.resources. Repository-relative parents traversal cannot be required at runtime. Only explicitly implemented CLI actions may report success. Local M1 admission still requires valid bound tickets and private credentials; host capability reporting is outside its completion criteria.

## 4. Validation & Error Matrix

- Foreign task owner: 403; owner/status/revision unchanged.
- Missing/stale revision: 428/412; no write.
- Reused command ID with changed semantics: 409; original result preserved.
- Invalid attempt in start: reject before any Task/Grant/Lease mutation.
- Missing preflight/resources/workspace: 423 or stale-condition 409; never default ready.
- Missing daemon: CLI infrastructure failure, never fixed submitted/ok output.
- Failed audit prerequisites: diagnostic exit 2; reproduced defects: exit 1; no checked defects: exit 0.

## 5. Good / Base / Bad Cases

Good: create a task through HTTP, restart the process, query the same ID and replay the original command without duplication.

Base: daemon restarts while an Attempt is running; preserve ownership and historical progress while invalidating execution authority until explicit recovery preparation.

Bad: MessageStore survives in JSON but TaskService is reconstructed empty, or a wrong-attempt start returns 400 after the task became running.

## 6. Tests Required

Run real uvicorn processes and requests in a disposable Git project. Assert restart persistence, atomic failures, same-ID replay, foreign-owner rejection, user decision waiting, resource expiration, actual file results and installed-wheel startup outside the repository. Existing unit tests remain required but cannot substitute for these assertions. The current audit is a regression reproducer of the legacy API, not the complete future M1 acceptance suite.

## 7. Wrong vs Correct

Wrong: CLI calls build_application() and mutates a fresh in-memory service; append a JSON write after SQL commit and call it atomic.

Correct: CLI authenticates to the running project runtime; module public ports persist all related changes under one UoW. Use outbox/Jobs for post-commit external work and preserve unknown external outcomes.
