# Implementation progress — 2026-10-02

Implementation and automated verification are complete. The implementation checkpoint did not include a Git commit or push; the user subsequently authorized local commit and delivery to GitHub tsunagouDev on 2026-10-02. Real Codex Desktop acceptance remains separate from fixture integration.

## Delivered

- Private, persistent per-user Codex console selection, atomic real-chat claim and one active request across projects. Pending cancellation/expiry, same-chat retry and completed record retention.
- No-argument `agent join`, taking root and main/worker only from the console record. Actual Desktop identity verification, real manifest and prior-route validation before claim. No missing-request fallback to initialization or worker.
- Shared application connection service preserves explicit `agent connect`; no new daemon authorization or Agent lifecycle.
- Private original-context receipt from shared bridge, excluding CLI helper and startup restoration; exact Agent/role/ready/epoch plus fresh roster checked before arrived.
- Current-enrollment recovery, idempotent same-selection prepare and receipt reconciliation after refresh. Late retry failure cannot undo an enrolled result.
- Frontend deferred/failed/cancel-conflict handling and recovery using existing JS components; no HTML/CSS edits. Repository onboarding Skill, user docs and entrypoint code-spec updated.

## Verification

- Final focused Python run: **106 passed** (store, console enrollment/agents, join, original onboarding, real daemon+bridge integration).
- `pnpm --filter @tsunagou/bridge-server run test:credentials`: **33 passed**, plus both late-ticket/restart smoke modes passed.
- Node workspace build and package checks passed. Final full Vitest run: **62 passed**, including **28 frontend smoke tests** for progress, cancellation, conflicts, nickname preservation and refresh recovery.
- Ruff lint passes. `mypy src`: no issues in 90 source files. Architecture and documentation checks pass.
- Full Python suite at the first integrated checkpoint: **790 passed, 11 skipped, 1 failed**. The unchanged `test_host_registration.py::test_codex_finds_its_executable_the_way_the_host_hides_it` expects no PATH fallback for a nonexistent configured executable; this machine has a real Codex executable on PATH. Both that test and `platform/host_registration.py` are unchanged from HEAD. Subsequent recovery changes are covered by the focused final run above.
- Required `tools/dev/check.ps1` ran: lint passed, stopped on formatting. Both HEAD and working tree require formatting in the same **139** tracked Python files (HEAD verified through formatter stdin with original Git blobs). Existing files were not mass-formatted. The later script command `mypy` also lacks a target in current pyproject configuration; `mypy src` was run directly.
- Diff whitespace checked with `core.whitespace=cr-at-eol` because existing JS/console source files use CRLF.

## Independent review

Review identified and fixed lost pending IDs on page refresh, prior route conflicts consuming a claim, and late failure downgrading enrolled state. Follow-up read-only review confirmed all three are resolved. All tests use isolated enrollment/route directories and fixture Desktop identity. No actual chat was enrolled, and no global MCP/installed user Skill was changed.

## Runtime adoption

Restart/reload the running console after updating its Python process. Install/update the repository onboarding Skill through the normal setup path. First MCP loading and upgrading an already-running older bridge require one host reload; after that, the shared bridge discovers new routes at call time. Actual Desktop chat acceptance must confirm one original `context__project_read` and frontend arrived; fixture success is not claimed as that evidence.
