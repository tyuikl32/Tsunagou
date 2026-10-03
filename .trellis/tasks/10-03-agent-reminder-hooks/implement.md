# Implementation plan

- [x] Implement shared reminder renderer, instructions and per-request role resolution.
- [x] Update generated project context wake guidance.
- [x] Add actual stdio response and template regression tests: roles, handoff/isolation, operations, errors, JSON preservation, no extra mutations.
- [x] Synchronize adapter specs and user docs.
- [x] Run relevant Python/stdio tests, workspace type checks, docs validator and diff checks.
- [x] Independent Trellis check and evidence record. No automatic Git commit/publish.

Rollback: revert only task-owned reminder code/template/docs/test changes. No migration or persisted runtime changes.

Code is implemented and reviewed; kept uncommitted for user review. See implementation-progress.md for evidence and limits.
