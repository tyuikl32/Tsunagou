---
name: tsunagou-agent-onboarding
description: "Guide a coding Agent through local Tsunagou onboarding, bridge attachment, role selection, and recovery. Use when a user asks to connect an Agent to a Tsunagou daemon, initialize a coordination project, attach a host conversation, or diagnose an onboarding session. Do not use it for ordinary task execution once the Agent is already ready."
---

# Tsunagou Agent Onboarding

Use this skill when the current Agent needs to join or recover a Tsunagou project. The Agent is a guide and protocol client; it is not the user control plane.

## Read the project instructions first

Read these files before giving project-specific commands:

- `docs/overview/agent-quick-start.md` for the user-facing sequence.
- `docs/overview/cli-http-manual.md` for the actual CLI and HTTP command surface.
- `docs/implementation/command-catalog.md` when a typed tool or command kind is unclear.

Use the current repository and daemon state as evidence. Do not reconstruct commands from historical docs or from a planned command catalog entry that is not registered in the current CLI/bridge.

## Separate the layers

Explain the stack in this order when the user asks how onboarding works:

1. The host adapter identifies the host and exposes its configured bridge entry.
2. The stdio MCP bridge redeems a one-time ticket or reconnects a saved session.
3. The local daemon authenticates the session, assigns the Agent identity and enforces command policy, owner, scope, revision and epoch rules.
4. This skill supplies the conversation workflow and tells the user which control CLI action is needed.
5. A host hook is optional context injection. It cannot replace the bridge, create an Agent, issue a ticket or grant authority.

Do not describe a skill or hook as a security boundary. The daemon and bridge are the security and identity boundary.

## Classify the current state

Before asking the user to do anything, determine which state applies:

- **No project**: there is no chosen Git coordination root or no `.tsunagou` state.
- **Daemon unavailable**: the coordination root exists but `daemon status` or `/api/v1/health` fails.
- **Ticket issued**: the user has an enrollment output, but the bridge has not redeemed it. This is not ready.
- **Bridge connected**: the current conversation can call `context__project_read` and receives its own Agent/session context.
- **Ready worker**: the Agent has its own identity and may wait for a task; it must not appoint itself main.
- **Ready main**: the user has explicitly run `agent appoint AGENT_ID`; the Agent may coordinate within its granted ceiling.
- **Recovering**: a saved `bridge-session.json` exists but reconnect or epoch checks fail. Do not reuse an old token manually; guide a rebind/re-enroll flow.

Never invent a project ID, Agent ID, conversation ID, revision, digest, choice, or path. Ask the user for the missing value or tell them which query produces it.

## User-control boundary

Guide the user to run these actions themselves:

- `project init`
- `daemon start|status|stop`
- `agent enroll`
- `agent appoint`
- `decision resolve`
- `project complete`
- `checkpoint retry`

The Agent may inspect public project context and use its own bridge tools after it is authenticated. It must not ask the user to paste `control.token`, `ticket.json`, `bridge-session.json`, an Authorization header, or a session token into the conversation. It must not print secrets from environment variables or private files.

## Bootstrap sequence

Keep the user interaction short and stateful:

1. Ask for the coordination root and whether it is already a Git repository. If it is not, show `git init --quiet <path>` and wait for the user to run it.
2. Show the exact `project init --coordination-root <path>` command, including the user-selected name and objective. Do not silently choose a project boundary.
3. Show `daemon start --coordination-root <path> --port 0`, then `daemon status` and `doctor`.
4. Ask the user to set `TSUNAGOU_PROJECT_ROOT` and `TSUNAGOU_STATE_DIR` in the shell that will run later CLI commands. Explain that a new shell needs the variables again.
5. For each host conversation, show one `agent enroll --adapter <kind> --mode attach --installation-id <id> --conversation-id <id> --output-dir <private-dir>` command. The user supplies the real host conversation identity; do not guess it.
6. Tell the user to load the generated bridge JSON into that host. The bridge must redeem the private ticket and then call `context__project_read`.
7. Report `ticket_issued` as pending. Report ready only after a successful bridge call and a non-degraded session status.
8. If the user wants this Agent to coordinate, obtain its actual `agent_id` from the bridge context and show `agent appoint <agent_id>`. Do not run or simulate this user-only action as the Agent.

Use `uv run python -m tsunagou` instead of `tsunagou` when the executable is not on `PATH`. Do not add unsupported flags such as `--project`, `agent list`, `authority show`, or `task list` to current commands.

## After attachment

On the first successful bridge call:

- Read `context__project_read` and state the returned role, session, project and owned tasks.
- A worker waits for a task and uses its typed tools to claim, report cognition, preflight, start, progress, submit and acknowledge review.
- A main Agent may create/ready/publish tasks, resolve coordination discrepancies, appoint work within its ceiling, and perform Git coordination. It still cannot perform user-only completion confirmation.
- Before file work, make the task, Attempt, scope, workspace baseline and Lease explicit. A host's Full Access does not grant a broader Tsunagou scope.
- ACK is not acceptance, a task completion is not project completion, and a bridge window being open is not proof of readiness.

If a user decision or project completion proposal is pending, summarize the exact ID, current revision and digest, then provide the corresponding user CLI command. Never substitute conversational consent for the control command.

## Recovery and diagnosis

Use this order:

1. Ask the user to run `daemon status --coordination-root <path>` and `doctor`.
2. If the daemon is healthy, let the bridge reconnect from its private session file. Do not copy an old token into a new configuration.
3. If the session is stale or the ticket was consumed without a saved session, issue a new enrollment/rebind ticket through the user CLI.
4. Use `recover` and `checkpoint list` for durable state. Use `operation show <operation_id>` for an existing operation.
5. If the Agent cannot call `context__project_read`, report `not_ready` or `degraded` with the observed error. Do not claim host compatibility from a simulator or from `tools/list` alone.

Keep diagnostics to IDs, status, error codes and digests. Do not paste daemon logs containing private paths or credentials into the model context.

## Completion response

End an onboarding turn with four items:

- current state (`not_initialized`, `daemon_unavailable`, `ticket_issued`, `ready_worker`, or `ready_main`);
- the next single user action, with one exact command;
- what evidence will change the state;
- the first safe Agent action after readiness.

When the user has not completed a control action, leave the Agent waiting. Do not keep polling, create a duplicate Agent, or take over a main Agent's task.
