# Standalone execution contract (FX2)

## 1. Scope / Trigger

Apply to Task execution, resource reservations, workspace observation, coordination assignments and their HTTP/MCP paths. FX-D01/02 replace the earlier M1 TTL/preflight contracts. See [FX2 design](../../tasks/09-28-fx2-execution-flow/design.md).

## 2. Signatures

- HTTP: POST /api/v1/commands/task.begin, B/task.claim. Payload: task_id:string, expected_task_revision:integer.
- HTTP: POST /api/v1/commands/task.submit, B/task.execute. Payload: task_id, attempt_id, summary; optional artifact_refs, evidence_refs, validation_metadata.
- MCP: task__begin / task__submit map to the same dispatcher/handlers.
- Main workspace.select: task_id, driver_kind, optional root_binding_refs/repository_id/external_locator/hard_constraints/evidence_refs/reason.
- ResourceService.reserve_set(*, task_id, attempt_id, owner_agent_id, execution_epoch, scope_digest, requests) -> ResourceReservation | None.
- release_for_attempt(attempt_id, *, reason) -> count; idempotent, no timer.
- CommandDispatcher.register_preparer(kind, handler); ProjectDatabase.dispatch(..., prepare=callback) invokes preparation after replay lookup, before BEGIN IMMEDIATE.

## 3. Contracts

Task/Attempt owns execution truth. Assignment records designated worker/takeover, message reference and main's plan only; query derives status from Task. No worker.ready or assignment execution state.

begin returns task_id/attempt_id/owner_agent_id/status=running/revision/scope_revision/execution_scope/workspace_id/reservation_id. No cached execution token or Grant ID. Scope {} means no file work; named-only scope needs no workspace. Required contracts default empty and only explicitly listed IDs gate execution.

SQLite module_state is the sole live domain store. File/Git scans and immutable patch materialization run before the write UoW under the existing process serialization lock. UoW revalidates and commits Task/Attempt, workspace, reservations, Grant, events/outbox atomically. Replay skips preparation. Failure restores all domain state; unreferenced content-addressed bytes are not an accepted result.

Reservations have active/released and UTC millisecond created_at/released_at/release_reason. No expiry/renewal/heartbeat. submit, owner block/fail/cancel_ack, main recover/takeover release and revoke together. Cancellation request and pending UserDecision do not assert that a running host stopped.

Same-database restart preserves owner/Attempt/baseline/reservation and revokes old execution Grants. Original owner issues a new begin command to reuse the Attempt and obtain current authority. New checkpoint replica imports no live credential/reservation. Job execution leases retain their internal deadlines.

CLI addresses the running daemon. Never fabricate Agent ownership using control credentials. Package protocol resources and preserve full-root filename-safe integration locks. No Git mutation in daemon.

## 4. Validation & Error Matrix

| Input/state | HTTP/error | Mutation |
|---|---|---|
| Missing/non-integer expected_task_revision | 400 expected_task_revision_required | none |
| Stale task revision | 409 task_revision_conflict | none |
| Different running owner | 403 attempt_owner_required | none |
| Wrong assigned worker | 403 assignment_worker_mismatch | none |
| Overlapping exclusive resources | 409 resource_conflict, blockers with owner/task/attempt/resource | none |
| Missing file-task workspace policy | 400 main_workspace_selection_required | none |
| Required contract pending | 400 required_contract_not_accepted:<id> | none |
| Related pending user decision | 400 user_decision_pending:<id> | none |
| Duplicate command ID, changed input | 409 idempotency_conflict | original result preserved |
| Old Grant submit after restart/reclaim | 403 capability_denied | none |
| Same owner running begin | same Attempt; fresh Grant if needed | no second baseline/reservation |
| Terminal task new begin | 400 task_not_beginable | none |

## 5. Good / Base / Bad Cases

Good: main chooses shared once; Worker begins, blocks, then begins a new Attempt with a fresh baseline. Main does not repeat unchanged policy.

Base: a long build has no API traffic. Ownership stays active. User or main may request cancellation, but only owner acknowledgement or explicit main recovery releases it.

Bad: pending user decision or a wall clock tick silently releases resources while the Worker can still write.

## 6. Tests Required

- test_execution_begin.py: parallel owner, file conflict/all-or-none, replay/no scan, failure rollback, preparation outside SQLite write transaction, policy reuse/new baseline, assigned worker, explicit contracts, user wait, all release paths, same-DB restart.
- test_resources.py: path prefix/physical aliases, shared consistent readers, distinct named resources, no elapsed-time expiry, idempotent release.
- test_runtime_maintenance.py: no task mutations; expired internal Job still recovered.
- tools/dev/execution_flow_probe.py --output <report>: actual CLI daemon stop/start, two HTTP workers and two independent Node MCP bridges; save UTC times/IDs/status. This is execution acceptance, not Desktop wake acceptance.
- Full Python/TypeScript checks, protocol generation/mirrors, architecture/docs validation.

## 7. Wrong vs Correct

Wrong: issue claimed ownership, ask the LLM to select/acquire/preflight/start in separate calls, then expire it while it is planning.

Correct: begin prepares observations before the transaction and commits the whole execution once. submit automatically captures file results and releases. Main handles semantic decisions; code enforces only declared identity, scope, version, dependency, owner and status.
