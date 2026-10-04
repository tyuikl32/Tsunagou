# Implementation progress

## 2026-10-04

- User approved the minimal plan and task creation. Earlier broader design choices were revoked. Exclusive daemon only; exact completion checkpoint must succeed; no idle/historical/shared-project coordination.
- Initial worktree was clean. Repository `.tsunagou/agent-context.md` is absent (only evaluation directory); no live project onboarding or identity changes performed.
- Implementation delegated to native Trellis implement sub-agent; main owns task/spec/manual and existing Windows lifecycle fixture fix.
- Source shape: request-local committed completion receipt, daemon response-send barrier, maintenance-triggered deferred check, registration lock fence, server-owned graceful exit. Independent Trellis check completed with no findings or fixes.

## Validation

- `python tools/docs/validate_docs.py`: PASS, 433 Markdown files / 1094 local links (before this progress note).
- `.venv/Scripts/python.exe tools/dev/check_architecture.py`: PASS.
- `.venv/Scripts/python.exe tools/codegen/validate_protocol.py`: PASS, 104 policies / 120 schemas.
- Focused existing checkpoint_failure, m1_runtime_flow, runtime_maintenance, daemon_stop, daemon_port, daemon_advertised_url tests: PASS, one existing skip.
- `tests/integration/test_multi_project_daemon.py`: PASS with real subprocesses.
- `tests/integration/test_daemon_lifecycle.py`: initial four failures due to CliRunner combined output containing a port-fallback warning when real port 2810 was occupied. Test now uses `--port 0` and `result.stdout`; all four Windows Job scenarios PASS. Stopped only the detached process created by this failed test, via exact temporary project root and normal identity-verifying CLI.
- New `tests/integration/test_completion_daemon_stop.py`: 7 passing cases, independently repeated. Actual Windows subprocess receives a complete completed/sealed result, exits with code 0, permits listener rebind/listen and database process lock reacquisition. Deterministic response/registration barriers cover both registration orderings, current-run replay after send failure (including replay finishing before the original), historical replay after restart, denied/stale/bad digest and exact-operation deferred retry. Unrelated checkpoint success cannot trigger shutdown.
- Full Ruff `check src tests tools/dev`: PASS. Independent reviewer also passed `check src tests tools`.
- Full mypy `src/tsunagou`: PASS, 95 source files.
- Full Python suite: **1032 passed, 8 failed, 12 skipped**, 199.47 seconds. All eight failures reproduced against unmodified HEAD `5bd1e1b` in a temporary baseline tree using the same unchanged built bridge assets. These are outside this repair; no unrelated source changes made.
- Full `ruff format --check src tests tools/dev` reports 167 files needing formatting before formatting the new test. All five modified pre-existing Python files also fail format check at HEAD (verified with `git show HEAD:<path>` piped to Ruff), so they retain local style to avoid repository-wide churn. New regression file formatted and its 7 tests rerun successfully; final Ruff lint passes.
- Final task context validation, whitespace diff check, docs validator: PASS (434 Markdown files, 1094 local links before archival/journal).

### Existing full-suite failures reproduced at HEAD

1. `test_console_opencode_flow.py::test_a_console_prepared_opencode_session_is_the_one_that_arrives`: legacy expectation of `ticket_file` from original-chat enrollment.
2. `test_remote_machine_end_to_end.py::test_a_remote_machine_imports_an_invitation_and_reports_itself`: bridge reply JSON parsing (unexpected trailing content).
3. `test_remote_machine_end_to_end.py::test_a_remote_worker_can_take_a_file_task_end_to_end`: legacy local enrollment `ticket_file` expectation.
4. `test_remote_machine_end_to_end.py::test_the_same_project_still_serves_a_local_session`: same legacy enrollment expectation.
5. `test_checkpoints.py::test_git_anchor_requires_manifest_content_on_local_ref`: fixture assumes `master`, machine defaults to `main`.
6. `test_console_glossary.py::test_every_registered_command_has_a_word`: four coordination wake command labels missing.
7. `test_host_registration.py::test_codex_finds_its_executable_the_way_the_host_hides_it`: installed Codex executable is found despite fixture expecting none.
8. `test_remote_invite.py::test_whichever_host_owns_the_name_reports_it`: real host identity remains discoverable despite fixture expecting outside-host failure.

Baseline reproduction used a temporary HEAD archive with an unchanged packages junction. Initial baseline run forced UTF-8 and changed the three remote tests' earlier failure point; repeating those three without that override reproduced the exact original failures above. No credentials or runtime state copied into task records.

## Completion

Implemented approved behavior without public protocol/schema changes, migrations, idle timers or startup/history scans. Synchronized entrypoint spec, command catalog, lifecycle description and CLI/HTTP manual. No TypeScript source or generated assets changed. Full-suite/format baseline limitations are explicit rather than represented as an all-green repository gate.

No Git commit or publication requested or performed. No existing user daemon stopped.
