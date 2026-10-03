# Implementation evidence — 2026-10-03

## Delivered
- Shared bridge reminder rules in reminders.ts; original JSON remains first MCP content block.
- Wake guidance in MCP instructions, generated context and relevant successful coordination tool results; native exception requires both sender and recipient Codex.
- Main-only completion guidance on context reads and acceptance, using fresh authenticated identity. Internal lookup suppresses original-host console arrival receipts. Failed optional lookup preserves successful result.
- No new wake/continuation/proposal/confirmation actions; domain protocols and frontend unchanged.
- Agent quick-start and adapter spec synchronized. Existing project templates use bootstrap refresh; already-running bridge needs reload.

## Verification
Trellis implement agent ran and reported passing:
- Reminder real stdio MCP tests: 3/3 for threadId, ai.opencode/sessionID and tsunagou.hostSessionId metadata.
- Existing bridge credential/arrival/message regression tests: 39/39.
- tests/unit/test_project_integration.py: 9/9, including template parity and refresh preservation.
- Workspace TypeScript checks: all 8 packages; targeted Ruff passed.
- Bridge build output is ignored; tracked generated protocol files unchanged.

Independent trellis-check agent reviewed all changes and ran bridge TypeScript check, node syntax check on the new stdio test, targeted Ruff, mypy for project_integration.py and git diff --check: all passed; no blocking findings or fixes.

Parent ran python tools/docs/validate_docs.py: PASS (48 unchanged archived sources, 424 Markdown files, 1082 links, 1194 context entries). git diff --check passed.

## Limits and disposition
- Actual stdio process with simulated authenticated daemon responses, not three live host or frontend acceptance. No user project was refreshed or enrolled, no active bridge process restarted.
- Extra post-acceptance authenticated context query inherits existing transport waiting behavior; a slow daemon can delay successful tool output. No dedicated reminder timeout was added; review judged nonblocking for this scope.
- Source checkout has no .tsunagou/agent-context.md or enrolled runtime context; no identity was fabricated. Native Trellis helpers are not new project members.
- No Git commit/push requested or performed. Implementation/review finished; task retained for review rather than claiming committed delivery.

## Follow-up: host operation guide and failure self-check
The original hooks were committed outside this agent's work as c5edb36 (`hooks`). This follow-up remains uncommitted; no commit/push was performed by the implementation helpers or coordinator.

User requested practical host operation pointers and less reliance on incomplete Tsunagou automatic wake, then clarified failures must trigger self-investigation of misidentified host/vendor rather than asking the user to manually wake. Updated both inline/template reminder text, source-local guide path, and added docs/overview/agent-wake-guide.md with Codex/OpenCode/DeepSeek sections. OpenCode example omits historical --auto to preserve existing approval settings; DSH web evidence is not represented as universal Desktop support. Reminder rules and completion hook are unchanged.

Passing checks reported by implementer:
- `uv run pytest -q tests/unit/test_project_integration.py`: 9 passed.
- `corepack pnpm --filter @tsunagou/bridge-server test:reminders`: 3 actual stdio scenarios passed.
- `corepack pnpm run check`: passed.
- `python tools/docs/validate_docs.py` and `git diff --check`: passed.

Independent reviewer verified command/evidence accuracy and reran targeted Ruff, mypy, bridge TypeScript, node syntax and diff checks: passed with no source fixes needed. Online guide is a publication fallback; new content currently exists in local source only. No real wake, host enrollment or user-project refresh was executed; no stronger live-host reliability claim is made.
