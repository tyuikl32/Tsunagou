# Verification Record

## Diagnosis

The console started successfully, but `POST /api/v1/projects` failed while materializing a project. The backend reached `ProjectIntegration.bootstrap()` and then `running_source_root()`, where the eager expression `Path(sys.executable).absolute().parents[2]` raised `IndexError` for the installed interpreter `D:\python\python.exe`. The frontend only surfaced the resulting `500` and dependent `503` responses.

## Implementation

`running_source_root()` now builds the source-tree candidate first and adds the executable fallback only when the interpreter has more than two parent entries. A regression test patches `sys.executable` to the shallow Windows path and verifies the source root remains discoverable.

## Evidence

- Runtime-context unit tests: **7 passed**.
- Project integration and bootstrap tests: **9 passed**.
- Console project and relay tests: **27 passed**.
- Combined focused result: **43 passed**.
- Live console smoke test: `POST /api/v1/projects` returned **200 OK** with JSON status `created`; the created daemon reported **running**.
- Temporary project and daemon were stopped and removed after the smoke test.
- `git diff --check` passed.

## Limits

Ruff was not installed, so Ruff was not run. Mypy was not run. No browser screenshot or full ten-view live acceptance was performed in this focused regression. The current working tree still contains the two source/test edits and this Trellis record; no Git commit was created by the repair.
