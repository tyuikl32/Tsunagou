# PT5 查询与责任时间线复核

- reviewed_at: 2026-09-28T01:26:49Z
- reviewer: tyuikl32 / Codex
- scope: CLI、HTTP、SQLite read projection、checkpoint verification

## Contract review

1. Project history and task history use the same `AuditPageModel`, signed event-sequence cursor, UTC millisecond timestamps, `as_of_event_seq`, and visibility policy.
2. A task timeline expands only persisted refs belonging to the task: task, attempts, results, preflights, progress records, workspace/isolation decisions, cognition reports, and visible messages/obligations. It does not infer unrelated project events.
3. Single-event reads and checkpoint reads authenticate before lookup and re-check project/lineage ownership. Queries do not call the command dispatcher and do not append events, operations, or revisions.
4. Checkpoint list/verify returns public metadata only. Manifest/file digests are verified; local Git anchors are limited to heads/tags. A non-Git project remains verifiable with an empty anchor list.
5. Export is `tsunagou.audit-export.v1`; it contains source project/lineage, export timestamp, projection version, high-water mark, cursor, and only currently visible projected events.

## Implementation evidence

- `src/tsunagou/bootstrap/container.py`: one query provider owns authorization, cursor context, task relation expansion, event projection, checkpoint verification and export envelope.
- `src/tsunagou/shared_kernel/query_models.py` plus generated checkpoint DTOs: strict shared response validation for HTTP and CLI.
- `src/tsunagou/platform/db/sqlite.py`: direct event lookup closes its read connection and returns only the safe event envelope.
- `src/tsunagou/platform/checkpoints.py`: missing local Git repository is a normal no-anchor result, not a checkpoint verification failure.
- `src/tsunagou/cli/app.py`: `project history`, `task history`, `audit event`, `checkpoint list --verify`, and `checkpoint verify` all use the daemon HTTP query routes and reject invalid response shapes.

## Limits retained

- The CLI still requires the user control credential; it does not expose Agent-only mutation commands.
- Private message bodies, credentials, host conversation content, and absolute paths are never added to the projection.
- An old event with no reliable time remains `null`/`unknown_time` and cannot be placed by migration time.
