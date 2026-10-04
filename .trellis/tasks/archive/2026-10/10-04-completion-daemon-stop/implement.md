# Implementation checklist

- [x] Implement the reviewed completion/operation and response-sent linkage with process-local tracking.
- [x] Reuse checkpoint maintenance for deferred success, and registration locking for exclusive-daemon shutdown fencing.
- [x] Own uvicorn.Server in daemon runner and adapt CLI subprocess launch without changing launch isolation.
- [x] Add focused failure, concurrency, shared-project, replay/restart and real-process regression coverage.
- [x] Run relevant pytest suites, Ruff, mypy and required shared checks; no task regressions. Full-suite baseline failures documented in implementation-progress.
- [x] Independent Trellis check of the final diff and approved scope.
- [x] Update runtime specification, user operation documentation and implementation-progress with actual evidence.

User approved implementation in chat. No Git commit or publication authorized. Rollback is reverting this task's source changes; no data migration is introduced.
