---
name: tsunagou-agent-onboarding
description: "Join or recover the current coding Agent in a local Tsunagou project: discover the installation, prepare real host identity, connect the bridge and verify the current conversation. Use for project onboarding and enrollment failures, not ordinary task execution after readiness."
---

# Tsunagou Agent Onboarding

Use the user's selected project and role. An instruction to install/join authorizes the ordinary setup steps; do not ask again for each command. Appointing main still requires the user's explicit choice of main. A worker cannot promote itself. Never read credentials into the conversation.

## Locate and prepare

1. Read the project's `.tsunagou/agent-context.md` and managed `AGENTS.md` block when present. Find the installed source from `.tsunagou/project-integration.json` or `~/.tsunagou/installation.json`. Source remains in its installation directory, not copied into the business repository.
2. Use the installed `tsunagou` launcher. If absent from the current shell's PATH, use the full launcher path from installation.json, or the installed `.venv` Python with `-m tsunagou`. Read `docs/overview/agent-quick-start.md` at that source when needed.
3. If this is a new coordination project, initialize the user-selected Git repository with `project init --coordination-root <actual path>`, then `project bootstrap --coordination-root <actual path> --source-root <actual installed source> --host codex`. Preserve existing project identity and user file contents. Bootstrap writes project rules and selected-host resources; it creates no Agent.
4. The CLI discovers a project from its root or a nested directory. Outside it, use global `--project-root <actual path>`. Do not ask users to repeatedly set project/state environment variables.
5. If the user selected an existing daemon for another project, use `daemon start --reuse <that project's actual root>` from the new project. Otherwise connect starts the selected project's daemon if needed.

## Codex Desktop: one connection

Run `agent prepare --adapter codex --role worker` inside the actual conversation (use main only when the user selected it). This observes the host's real conversation and local app endpoint and writes a private request file. It creates no Agent or authority. Never invent a conversation ID or use a display profile as identity.

The prepare result includes one fully filled PowerShell command for `agent connect --request-file ...`. If the user already authorized joining, execute it yourself. If execution needs the user, show exactly that one command: no ID placeholders, token copying, separate enroll or appoint ceremony. Do not show raw request contents.

Connect reuses the conversation's private state, starts/verifies the daemon, enrolls, binds the original Desktop conversation and configures the shared MCP server named `tsunagou`. Its `enrolled` result confirms enrollment, **not that the original chat has loaded the MCP**. Repeated connect must preserve the Agent identity.

Then call `context__project_read` **from this original conversation's MCP tools**. Report ready_worker/ready_main only when it returns the expected project, own Agent, ready session, selected role and registered host binding. A headless bootstrap query or another Agent's query cannot satisfy this step.

The shared bridge routes every call by host-provided MCP thread metadata. Separate chats/subagents must use separate identities; do not share session files or substitute agent IDs in tool arguments. Display profiles do not control identity.

If tools are missing after first configuration, use a documented host reload operation if available. Otherwise explain one concrete first-load action (fully quit/reopen Codex, then return to the same chat and call context). Do not promise Ctrl+R restarts MCP. If one restart does not help, investigate the recorded error and server configuration instead of asking for repeated restarts. Existing loaded shared bridges read new route/ticket/endpoint state on each call.

## Other adapters

Use their actual host-provided conversation identity and an isolated bridge process/config per conversation. The current automatic Desktop prepare route is Codex-specific. Do not claim another host supports shared thread metadata or original-chat wake without a working implementation. Retain the registered low-level enroll/rebind path for diagnostics, not as the normal Codex onboarding ritual.

## After attachment

- Read own context, incremental inbox and blackboard. A worker selects eligible published work, calls `task.begin` with the current revision, works in the returned scope and calls `task.submit`. Begin captures the baseline/reserves resources; submit captures results/releases resources. Use `task.block` when actually blocked.
- Main proactively handles ordinary worker requests under existing authorization: check existing tasks and duplicate requests, publish suitable work or give a concrete reply, and fulfill response obligations. Reading or ACK alone is not a response. Do not ask whether to do ordinary scheduling again.
- Main handles Git writes and coordination. Major design/scope changes and project-completion confirmation stay user-controlled. Skill text and Full Access do not expand Tsunagou authority.
- Lack of recent activity does not mean a worker died. Resources remain owned until explicit release/recovery, not until a timer expires.

## Recovery

Inspect `daemon status`, `doctor` and `agent list --json` yourself where authorized. Keep diagnostics to statuses, IDs, timestamps and error codes. The bridge normally reuses its saved session; restart/epoch changes trigger reconnect. Re-run prepare/connect for this same conversation when the host endpoint or enrollment material needs repair. Do not issue new identities to hide a connection failure.

Use the installed source's `docs/overview/cli-http-manual.md` for real command syntax. Do not copy old profile-based onboarding examples from historical documents. Never print control.token, ticket.json, session tokens, Authorization headers or raw pipe addresses.

End with actual project_id, agent_id, role and state, or the exact unresolved error and one next action. Do not claim successful automatic wake from enrollment alone; wake is demonstrated by a daemon message causing the original conversation to run.
