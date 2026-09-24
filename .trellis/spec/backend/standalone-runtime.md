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

Execution Lease is an execution fence, not a background liveness signal. Before `task.start` changes an Attempt to `running` or issues an execution grant, recheck every active Lease under the ResourceService lock and reject an expired Lease even if the maintenance tick has not run. Worker progress may renew its own active Lease; daemon maintenance must never renew a silent worker. WakeAttempt deadlines are a separate mechanical state machine: maintenance may expire/retry wakes and persist Main-visible events, but it must not acquire, renew, or release execution Leases.

When an execution Lease expires, the mechanical fence covers all three public coordination views: the Attempt becomes `orphaned`, its Task returns to `open`, and the matching coordination Assignment becomes `blocked` with `claimed_attempt_id` and `started_at` cleared. The reconciliation is keyed by the current Attempt id, is idempotent, preserves WakeAttempt history, and never creates a replacement wake implicitly. Project integration lock names must be derived from the full root digest while replacing filename-unsafe digest punctuation (including `:`) so per-root isolation remains stable on Windows.

`task.submit` follows the same execution workflow boundary. It must recheck the Attempt's Lease under the resource lock before creating a result; an active Lease that has crossed its deadline is fenced and the submit produces no result. A successful submit releases all Lease rows for that Attempt. Do not call `TaskService.submit` directly from the command handler.

Worker lifecycle responses may expose `lease_guidance` with `renewal_owner=worker`, `renew_with=[task.progress, resource.renew]`, active Lease expiry facts, and `daemon_heartbeat=false`. Main reminders reuse durable `message.send` with assignment/task/attempt references; a reminder never changes Lease state.

Package protocol files as distribution resources and read them with importlib.resources. Repository-relative parents traversal cannot be required at runtime. Only explicitly implemented CLI actions may report success. Local M1 admission still requires valid bound tickets and private credentials; host capability reporting is outside its completion criteria.

## 4. Validation & Error Matrix

- Foreign task owner: 403; owner/status/revision unchanged.
- Missing/stale revision: 428/412; no write.
- Reused command ID with changed semantics: 409; original result preserved.
- Invalid attempt in start: reject before any Task/Grant/Lease mutation.
- Active Lease expired at `task.start`: fence the Attempt, revoke execution authority, return the task to recovery/open handling, and never report `running`.
- Active Lease expired at `task.submit`: reject with `resource_lease_expired`, create no TaskResult, and run normal orphan/revocation recovery; successful submit leaves the Attempt Lease `released`.
- WakeAttempt deadline passed: reject late `host_accepted`/`worker.ready`; maintenance may create at most two retries after the initial attempt, then records an important failure event.
- Missing preflight/resources/workspace: 423 or stale-condition 409; never default ready.
- Missing daemon: CLI infrastructure failure, never fixed submitted/ok output.
- Failed audit prerequisites: diagnostic exit 2; reproduced defects: exit 1; no checked defects: exit 0.

## 5. Good / Base / Bad Cases

Good: create a task through HTTP, restart the process, query the same ID and replay the original command without duplication.

Good: a worker calls `task.progress` or `resource.renew` before expiry and receives the renewed expiry; a silent worker's Lease expires and is reclaimed normally.

Base: daemon restarts while an Attempt is running; preserve ownership and historical progress while invalidating execution authority until explicit recovery preparation.

Bad: MessageStore survives in JSON but TaskService is reconstructed empty, or a wrong-attempt start returns 400 after the task became running.

Bad: a maintenance thread silently renews a worker's Lease, or `task.start` trusts a preflight captured before Lease expiry.

## 6. Tests Required

Run real uvicorn processes and requests in a disposable Git project. Assert restart persistence, atomic failures, same-ID replay, foreign-owner rejection, user decision waiting, resource expiration, actual file results and installed-wheel startup outside the repository. Existing unit tests remain required but cannot substitute for these assertions. The current audit is a regression reproducer of the legacy API, not the complete future M1 acceptance suite.

For Lease/Wake changes, use an injected clock or controlled expiry and assert: stale `task.start` never produces `running` or an active execution grant; Lease expiry synchronizes Task, Attempt, and Assignment exactly once; WakeAttempt retries are exactly three total and late callbacks are rejected; maintenance never changes a live Lease expiry; lifecycle responses expose worker-owned renewal guidance; and a Main `message.send` reminder is durable and correlated. Project bootstrap tests must also assert that lock paths are filename-safe and distinct for distinct roots.

## 7. Wrong vs Correct

Wrong: CLI calls build_application() and mutates a fresh in-memory service; append a JSON write after SQL commit and call it atomic.

Correct: CLI authenticates to the running project runtime; module public ports persist all related changes under one UoW. Use outbox/Jobs for post-commit external work and preserve unknown external outcomes.
