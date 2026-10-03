# Reminder-only coordination hooks

## 1. Scope / Trigger
Shared bridge MCP presentation and generated project context carry advisory wake/completion guidance for Codex, OpenCode and DeepSeek Harness. Domain commands, wake providers and user confirmation permissions remain unchanged.

## 2. Signatures
`tools/call` returns its original JSON in `content[0].text`; reminders are additional `{type: "text", text: ...}` items. `context.project_read` supplies authenticated `agent_id` and `main_agent_id`. No new command, argument, response JSON field or environment option is introduced.

## 3. Contracts
- All Agents get wake guidance in MCP instructions/generated context and successful context/coordination/submit/review/message outputs. PowerShell is the reminder default; the Codex-native exception applies only when BOTH sender and recipient are Codex.
- Wake guidance points to the installed-source host operation runbook (with source-relative/repository fallback for shared MCP). Explicitly state that Tsunagou automatic wake must not be assumed reliable; do not repeatedly configure/probe/rebind it to make progress. Per-host guide steps must distinguish demonstrated native operation from unknown capability, preserve the original conversation, and never equate queued delivery with actual wake. A docs entrypoint is preferable to an invented or unverified command.
- On failure, guidance must first require checking target host/vendor identification against real registration/host evidence (not model brand, nickname or caller host), original conversation and command, then correcting and verifying. Do not delegate wake back to the user as a manual fallback. Unsupported/permission blockers are recorded honestly for main; no fabricated success or authority expansion.
- Main-only completion reminder appears after context reads, `task.review.accept` and `task.self_accept`. Compare fresh non-empty authenticated `agent_id` and `main_agent_id`; never trust caller arguments, stale role labels or a process-global previous caller.
- A role lookup after acceptance uses the same request configuration/session. Internal role reads suppress original-host console arrival receipts (`observeContext=false`); they are not proof that the Agent read its context. Optional reminder lookup failure omits only the completion reminder and preserves successful original output.
- Main decides whether all work/merge/acceptance is complete and whether a proposal already awaits confirmation. Do not detect business completion by parsing chat or task counts.
- No reminder-driven shell execution, recipient message, wake, continuation, proposal or confirmation. Existing independent wake behavior is untouched. Static shared instructions must not direct workers to issue project-completion proposals.

## 4. Validation & Error Matrix
| Condition | Reminder behavior |
| --- | --- |
| Authenticated current main reads context/accepts result | Wake plus conditional completion reminder |
| Worker, missing/malformed identity or changed main | No completion reminder |
| Optional role read fails after successful acceptance | Successful JSON and wake hint preserved |
| Tool fails | Original error guidance, no success hints |
| Unrelated operation | Original output without post-tool hints |

## 5. Good / Base / Bad Cases
Good: a main receives a reminder to submit a completion proposal if all work is done; user confirms later. Base: worker submits results and receives wake guidance only. Bad: target-only Codex exception; treating `role: main` or tool args as authority; automatic proposal creation.

## 6. Tests Required
Exercise actual stdio MCP initialize/tool output, main/worker and shared-session isolation, main handoff, successful operation allowlist, failures and failed optional context lookup. Assert original JSON preservation and no extra mutation commands. Test generated context content and refresh preservation. Mock daemon responses do not prove live-host wake or frontend acceptance.

## 7. Wrong vs Correct
Wrong: store `lastRole = args.role` and use it for later callers. Correct: derive the recipient of a main-only hint from the current request's authenticated context. Wrong: run a shell command or submit a proposal in the reminder hook. Correct: append advisory text and leave execution to the Agent.
