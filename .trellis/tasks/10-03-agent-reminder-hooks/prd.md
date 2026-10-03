# Agent coordination reminder hooks

## Goal and approval
User approved the final design and explicitly requested implementation on 2026-10-03. Prior task-creation consent persists. Two reminder-only hooks help Agents remember wake guidance and main remember the formal completion proposal required by the frontend.

## Requirements
- All Agents receive: 需要唤醒其他 Agent 时，请通过 PowerShell 执行对应宿主的唤醒操作；发起方和接收方都为 Codex 时，沿用 Codex 已有的唤醒机制。请确认是否确实需要唤醒，避免重复操作。
- Deliver wake guidance in persistent generated project context, MCP instructions, context reads and successful assignment/submission/review/message operations.
- Only authenticated current main receives targeted completion guidance: 如果所有工作已经完成，且合并与验收已通过，请记得调用 `project__completion_propose` 发起任务完成提案，不要仅在聊天中宣布完成。已有待确认的提案时不要重复提交，最终完工由用户确认。
- Deliver completion guidance on main context reads and successful review acceptance/self acceptance. Main interprets whether all work/merge/acceptance is complete; no semantic completion detector.
- Preserve original JSON tool result; append separate MCP text content. Failed/unrelated operations do not gain post-success reminders.
- No automatic wake, continuation, proposal, confirmation, shell execution, recipient message, new authority or protocol command. Existing wake and frontend behavior stay intact.
- Follow-up approved by user: enrich the first reminder with per-host commands or operational documentation entrypoints. Explicitly discourage relying on incompletely implemented Tsunagou automatic wake and repeatedly trying its configuration/binding/probe path. Prefer existing host-native original-session operations and verifiable evidence; do not invent unsupported commands. This is reminder/runbook enhancement only.
- Additional user steering: when wake fails, first recheck whether the target vendor/host was misidentified; independently verify actual host, original session and operation, correct mistakes and validate again. Do not ask the user to manually wake the Agent. Genuine unsupported/permission blockers remain explicit unresolved facts; never fabricate success or bypass authority.

## Acceptance
- Both main and worker see wake guidance with BOTH-Codex exception; only current authenticated main sees targeted completion guidance.
- Actual bridge output verifies operation selection, failure handling, unchanged JSON and no reminder side effects; cover role handoff/session isolation.
- Template tests, docs/spec updates, relevant tests/type checks/docs validation pass. Existing projects use bootstrap refresh.
- Do not claim live multi-host/frontend acceptance from mock tests.

## Environment
Clean source checkout on elysia at start. `.tsunagou/agent-context.md` absent (only evaluation directory); no local enrolled project session to read. No enrollment or tickets authorized or needed for native Trellis helpers. Never fabricate runtime identity. No commits/publishing requested.
