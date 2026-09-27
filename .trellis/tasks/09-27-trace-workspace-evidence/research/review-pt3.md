# PT3 Trellis review

reviewed_at: 2026-09-27T19:18:49.000Z

Reviewer: `pt3_workspace_check`; shared Windows checkout `D:\Tsunagou`, branch `codex/persistence-traceability`. No commit, deployment, or real user project mutation was performed. Parent implementation continued concurrently; the reviewer owned scanner internals and focused regression tests, with larger domain/interface repairs handed back to the parent.

## Findings fixed in reviewer-owned files

- `src/tsunagou/modules/workspaces.py`: porcelain v1 `-z` rename order was reversed. Destination is now preserved first and the source is separately scope-filtered; copies do not invent a source deletion.
- The tree digest previously included only Git status paths, and index digest only name/status. The scanner now records all admitted tracked and untracked content/type/mode and uses index mode/blob/stage identities. Clean commits and two staged versions of the same path cannot collapse to one digest.
- Special, unreadable, symlink and out-of-root entries previously remained eligible for Git patch generation. Only admitted regular/missing paths now reach patch generation; relative paths use literal pathspecs; external diff and textconv execution are disabled. Windows junctions cannot export their external target bytes.
- Private `.git`/`.tsunagou` segments at any depth and a custom artifact output directory are excluded from tree/index/patch inputs. Existing corrupt patch files are rejected rather than silently reused. Repeated scans do not recursively ingest earlier patches.
- Bound subdirectory scans now normalize Git's repository-relative status paths to the bound root. Plain directories use a scoped no-follow walker. `include_patch` returns bytes only as internal observation data; scans that do not request patches avoid patch subprocesses.
- Scope matching respects Windows case-insensitive paths without widening distinct POSIX directories.

`tests/unit/test_workspaces.py` adds real Git, plain directory, Unicode rename, index-content, literal-pathspec, recursion, unreadable file, symlink and Windows junction regressions; POSIX-only newline/case-sensitive/FIFO cases are explicitly skipped on Windows. It also proves symlink-only results preserve observation evidence without exporting target text, ordinary file results still require patch/commit, malformed timestamps and raw output strings are rejected, and worker-reported higher evidence levels remain `agent_asserted` with tool-version digest.

`tests/unit/test_trace_workspace_access.py` adds assembled-runtime tests with real SQLite and HTTP: anonymous 401, another worker 403, bare hash 404, permitted owner/main reads, independent project/lineage/domain/owner/scope checks, recipient-only denial even for main/user, safe corruption 409, and restart preservation of attachment access, scope and observation time.

## Findings handed to parent and verified in current code

- Task scope now controls multi-root selection, including roots outside the coordination directory; binding identity/revision and scope revision changes fence later scans. Invalid scope containers fail as input errors.
- ArtifactService is wired into the runtime/state snapshot. Domain references are independent even when blobs have identical bytes; project/lineage/owner/scope and content are revalidated. Recipient-only references cannot be promoted by hash possession, and corrupt pre-existing blobs are rejected.
- The obsolete bare-hash workspace validation route is removed. System observations override caller path claims; self-reported validation receipts do not become system test evidence.
- Baseline/result preserve root observations and their digest inputs. Observation-only changes can be recorded while missing ordinary file patches remain an error.

## Outstanding handoff / scope boundaries

- The workspace read projection was observed to label all results `observed_by=daemon`, including `agent_asserted` external/worktree results without a filesystem observation. Reported to parent at review completion for a conditional observer/evidence-subject projection; the parent owns that public projection edit.
- Filesystem observation is not a filesystem transaction or authorship proof. This review does not claim atomic snapshots against simultaneous external edits, line-level attribution, or macOS/Linux runtime coverage.
- Filesystem materialization/outbox crash windows belong to PT4. The current artifact producer remains synchronous; PT3 tests do not prove PT4's commit/rename/reconcile requirements.
- Existing FastAPI `on_event` deprecation warnings and repository-wide formatting drift predate this review; no blanket formatting or lifecycle rewrite was performed. The new access test file was formatted.

## Verification

- `uv run pytest -q -o addopts='' tests/unit/test_workspaces.py tests/unit/test_workspace_evidence.py tests/unit/test_artifacts.py tests/unit/test_trace_workspace_access.py tests/integration/test_m1_runtime_flow.py`: **55 passed, 3 skipped**, 84 existing FastAPI warnings, 8.58 seconds.
- After the final patch-subprocess optimization: `uv run pytest -q -o addopts='' tests/unit/test_workspaces.py tests/unit/test_workspace_evidence.py`: **39 passed, 3 skipped**.
- `uv run ruff check src tests tools`: pass. Focused scanner/new-test Ruff rerun after the final edit: pass.
- `uv run mypy src`: pass, 60 source files.
- `corepack pnpm run check`: pass for all 7 package workspaces at the earlier reviewer checkpoint; parent continues protocol/bridge synchronization and owns the final rerun.
- `uv run python tools/codegen/validate_protocol.py`: 111 policies, 124 schemas passed at reviewer checkpoint.
- `python tools/docs/validate_docs.py`: 308 Markdown files and 781 local links passed at reviewer checkpoint; parent continues documentation edits and owns final rerun.
- `uv run python tools/dev/check_architecture.py`: pass. `git diff --check`: pass, only CRLF/LF informational warnings.

Full task closure and the final source-bound verification manifest remain the parent session's responsibility. This report is a PT3 review record, not a completion claim for PT4–PT7 or the full persistence plan.
