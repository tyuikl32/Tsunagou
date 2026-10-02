# Windows Python 路径兼容修复与控制台创建项目回归

## Goal

记录并验证 Windows 浅层 Python 安装路径导致 Tsunagou 控制台创建项目返回 500 的修复；保留真实 HTTP 创建项目和 daemon 启动证据，明确尚未覆盖的检查与页面复验。

## Requirements

- `running_source_root()` must tolerate a shallow Windows interpreter path such as `D:\python\python.exe` without raising `IndexError`.
- Source-tree discovery must keep the existing source-file candidate first and retain the executable-based fallback only when its parent depth is available.
- The console project-create path must complete bootstrap and start the project daemon after the fix.
- The record must distinguish verified behavior from checks not run; it must not claim a full UI or host-onboarding acceptance.

## Acceptance Criteria

- [x] Add a focused regression test for the shallow interpreter path.
- [x] Run the focused runtime-context tests: 7 passed.
- [x] Run project integration and bootstrap tests: 9 passed.
- [x] Run console projects and relay tests: 27 passed.
- [x] Exercise the real console HTTP project-create path: response `200 OK`, project status `created`, and daemon status `running`.
- [x] Stop and remove the temporary smoke-test project and daemon after verification.
- [ ] Ruff and mypy were not run because Ruff is not installed in the active environment and no separate type-check command was configured.
- [ ] Browser-level visual retry and full multi-view acceptance remain outside this focused regression record.

## Notes

- This is a retrospective record of the already authorized fix; it does not reopen the FX1-FX7 plan.
- Root cause: `Path(sys.executable).absolute().parents[2]` was evaluated eagerly for `D:\python\python.exe`, before the valid source-tree candidate could be used. The resulting `IndexError` surfaced as console project-create `500` and dependent view `503` responses.
- Code changes are limited to `src/tsunagou/platform/runtime_context.py` and `tests/unit/test_runtime_context.py`.
- The source base was `7eec463` on branch `elysia`; the repair has not been committed yet.
