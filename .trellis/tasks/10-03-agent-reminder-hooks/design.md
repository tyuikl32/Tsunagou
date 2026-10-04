# Design

## Boundary
Reminder rendering lives at shared MCP presentation boundary, not domain mutation handlers or host wake providers. Centralize pure rules in bridge-server; append extra text blocks after original JSON. Add wake text to initialization instructions and generated project context. Existing protocols/domain records unchanged.

## Role source
Use successful authenticated context.project_read output: compare agent_id and main_agent_id; never use tool args or a global previous caller. For post-acceptance reminders obtain fresh context with same per-request configuration/session; optional role lookup failure must not change a successful mutation result. Context reads use own result. No cached global main role.

Internal role lookup passes `observeContext=false` to avoid writing the console's original-chat arrival receipt; it is not an Agent-originated context read.

## Events
Wake guidance: context.project_read, coordination.plan, coordination.takeover, task.publish, task.submit, task.review.accept, task.review.request_changes, task.self_accept, message.send and message.respond, successful results only. Completion guidance: context.project_read, task.review.accept and task.self_accept, authenticated current main only. Text is conditional; no inference of project completion from one task. Static shared context must not give workers the main-only action.

## Compatibility
Hints perform no shell commands, new messages, retries or wake calls. Preserve response JSON and error guidance. Template refresh uses existing bootstrap flow, preserving user content. Docs describe reminder-only guarantees and BOTH-Codex exception.

## Follow-up: actionable wake guidance
Keep the inline hint compact with an explicit warning that Tsunagou auto-wake is not a reliable prerequisite. Add a focused source runbook with Codex/OpenCode/DeepSeek sections and pointers to existing operational evidence. Include a source-relative guide path plus repository fallback in the shared hint; generated context can expose its resolved installed-source docs path. The unpublished working-tree guide is authoritative until published, so do not claim the remote URL already contains it. No unverified universal resume command, secret-bearing endpoint example or recovery loop. Host guidance must preserve the original conversation and validate actual turn/presentation rather than queued delivery.
