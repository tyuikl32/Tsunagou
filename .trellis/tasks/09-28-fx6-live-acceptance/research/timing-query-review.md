# FX5 timing query / FX6 capture review

Date: 2026-09-28. Reviewer: dispatched trellis-check, Windows repository D:/Tsunagou.

Scope: `project_timings.py`, the new CLI `project timings` function, its query DTOs, their unit/HTTP tests, and `live_repair_acceptance.py` with capture tests. Existing concurrent FX edits were preserved. No live daemon, credentials, host conversations or Git commits were operated on.

## Finding fixed

The timing CLI printed arbitrary `RuntimeError` text. `_daemon_request` can construct that text from an HTTP error body's `detail.code`; it is not an authorized public timing projection. Four new sentinel cases reproduced the leak for HTTP 400, 403, 500 and a non-HTTP failure.

The timing command now reports the HTTP status category, two known local transport/configuration codes, or `timing_query_failed`. It preserves the existing authentication/input/service exit-code distinctions. Raw errors and private reference sentinels are absent from JSON output.

Changed files in this review:

- `src/tsunagou/cli/app.py`: only the timing command error handler.
- `tests/unit/test_project_timings.py`: four error privacy regression cases.
- `tests/integration/test_project_timings_http.py`: unchanged-running begin coverage and a real SQLite/HTTP rework + running restart/resume case.
- This review record.

## Verified behavior

- The public Result's persisted `created_at` supplies a submission time while U/main history, single-event read and export continue to deny the explicit-private submit audit fact. The timing output labels `result_created_at`, keeps `submit_events=0`, and omits private bodies, references, session values and credentials.
- Exact task/Attempt/Result joins separate a changes-requested Attempt from its replacement. The new assembled test checks both original begin/submit/review triplets, final statuses and separate work/review elapsed values.
- A fresh begin command against unchanged running ownership creates no new domain event. Same-database restart revokes process-local grants; begin restores execution authority without moving the Attempt's original start. Both paths are now covered through actual runtime commands rather than only synthetic audit rows.
- Missing timestamps stay null; multiple Results, conflicting submit clocks, duplicate facts and broken pagination are not promoted to successful durations. Reverse clocks retain actual timestamps with `clock_inconsistent`.
- The capture reads the installed CLI timing output, allowlists fields, and export preserves its sources/counts. It does not add a synthetic submit event. Separate HTTP reads remain non-atomic, as already documented in the query guide and acceptance instructions.
- Repeated reads and idempotent submit replay do not change the database snapshot; public Result timestamps survive same-database rebuild.

No unresolved timing/capture issue was found in this scope. Existing logging/privacy specs already require safe error categories and unchanged authorization, so no new spec rule was needed.

## Actual verification

1. Initial baseline: `uv run pytest -q tests/unit/test_project_timings.py tests/integration/test_project_timings_http.py tests/unit/test_live_repair_acceptance.py` — 36 tests passed.
2. The added error sentinel regressions failed before the handler fix, demonstrating the leak. Runtime test setup was corrected to reflect existing semantics: unchanged begin emits no new domain event; changes-requested work is readied and published by main before the next begin. These were test assumptions, not product changes.
3. Final regression command: `uv run pytest -q tests/unit/test_project_timings.py tests/integration/test_project_timings_http.py tests/unit/test_live_repair_acceptance.py tests/unit/test_history_cli.py tests/unit/test_trace_audit.py tests/integration/test_failure_timeline.py` — pass, 69 tests. Count independently confirmed using the same files with `--collect-only -q -o addopts=''`. Existing FastAPI `on_event` deprecation warnings remain outside this review's scope.
4. `uv run ruff check src/tsunagou/application/workflows/project_timings.py src/tsunagou/cli/app.py src/tsunagou/shared_kernel/query_models.py tests/unit/test_project_timings.py tests/integration/test_project_timings_http.py tools/dev/live_repair_acceptance.py tests/unit/test_live_repair_acceptance.py` — pass.
5. `uv run mypy src/tsunagou/application/workflows/project_timings.py src/tsunagou/cli/app.py src/tsunagou/shared_kernel/query_models.py tools/dev/live_repair_acceptance.py` — pass, four source files.

These code regressions do not certify remaining live FX6 scenarios or user completion confirmation. The main session owns installed-command evidence and the acceptance status.
