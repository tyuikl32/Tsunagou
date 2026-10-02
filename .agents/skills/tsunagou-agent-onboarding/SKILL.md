---
name: tsunagou-agent-onboarding
description: "Join or recover the current coding Agent in a local Tsunagou project: discover the installation, prepare real host identity, connect the bridge and verify the current conversation. Use for project onboarding and enrollment failures, not ordinary task execution after readiness."
---

# Tsunagou Agent Onboarding

Use the user's selected project and role. An instruction to install/join authorizes the ordinary setup steps; do not ask again for each command. The console role selection is the user's explicit choice of main or worker. Outside that flow, appointing main still requires the user's explicit choice of main. A worker cannot promote itself. Never read credentials into the conversation.

Enrolling a **new** Agent is the user's decision, not ordinary setup: never invite, ticket or enroll another conversation on your own initiative — only when the user asked for it or allowed it. If the work needs another Agent, ask the user and let them choose the host and the role; do not grow the team yourself.

## Which project and role? — ask the machine before asking the user

A conversation that has just been asked to join knows only its own host-provided
conversation id and its working directory. The coordination root is **not** derivable from
either one: a project may coordinate several folders, and the console creates projects
under its own root, so the working directory is often a business workspace rather than the
project. The machine holds the answer — the person's console decision, at most one active
request per local OS user.

1. Run the installed CLI's `agent pending --adapter <this host's adapter>` (for example
   `deepseek`). It answers with `project_root`, `project_id`, `role` and `nickname` — no
   credentials — or `status: none` plus the next action.
2. Join **that** project with **that** role. Do not pick a project out of a machine-wide
   list, do not `project init` to compensate, and do not treat the current working
   directory as the coordination root.
3. The role on that record is the user's choice and outranks anything you ask for: a
   connect that requests the other role is refused (`enrollment_role_conflict`) before any
   bridge material is written. Pass the record's role when the host tool takes one; never
   ask to be main on your own initiative.
4. `status: none` means nobody is waiting for this host: report it and ask the user to
   prepare the Agent in the console for the intended project. Enrolling is the user's call,
   so never invent a project just to have something to join.

## Console Codex join: the default for “请接入 Tsunagou”

When the user asks the current Codex Desktop conversation to join Tsunagou, or says the console has already prepared an Agent, use `tsunagou agent join` with no project or role arguments. Do this before any project initialization, cwd-based project selection, or default worker preparation. This applies to the one active console request for the same local OS user, including when the current conversation's working directory is outside the selected project.

1. Locate the installed launcher from PATH or `~/.tsunagou/installation.json`. If it is absent from PATH, use the recorded full launcher path or installed Python with `-m tsunagou`. Do not read credential files. If the installation or Skill is missing, report that prerequisite; do not create a coordination project to compensate.
2. Run `agent join` inside this actual Codex conversation. The program discovers the pending console request, reads its project/role/nickname, verifies the actual host conversation and atomically claims it. Never invent a conversation ID, override the selected role, or pass the current cwd as a replacement project.
3. If there is no pending request, or it is cancelled/expired, report the error and ask the user to prepare an Agent in the front end. Do not fall back to project init, `prepare --role worker`, or an unrelated existing project.
4. If this conversation has already claimed the request and joining failed, retry `agent join` in this same conversation after addressing the reported error. Do not issue a new identity. Another conversation cannot consume the same request; do not take over or share the claimant's private session files.
5. The command's enrolled result is not completion. Call `context__project_read` from this original conversation's MCP tools. Verify the project, own Agent, selected role, ready session and registered host binding match the join result. Only then report ready_main/ready_worker. That original call supplies the console receipt; a headless helper or another Agent cannot satisfy it.

The console has one active Codex request per local OS user across projects and browser windows. Cancelling an unclaimed request is separate from removing an enrolled Agent; do not unregister the global shared MCP to cancel it. First-time MCP loading may require the host reload step below. Having only one sentence to say does not remove the installation/loading prerequisites.

## Explicit installation or manual project selection

Use this section only when the user explicitly asks to install/initialize a new project or join a specified project without a console request. Never use it as an automatic fallback after `agent join` fails.

1. Read the selected project's `.tsunagou/agent-context.md` and managed `AGENTS.md` block when present. Find the installed source from `.tsunagou/project-integration.json` or `~/.tsunagou/installation.json`. Source remains in its installation directory, not copied into the business repository.
2. Use the installed `tsunagou` launcher. If absent from PATH, use its recorded full path or installed Python with `-m tsunagou`. Read `docs/overview/agent-quick-start.md` at that source when needed.
3. Only for a user-requested new coordination project, initialize the selected Git repository with `project init --coordination-root <actual path>`, then `project bootstrap --coordination-root <actual path> --source-root <actual installed source> --host codex`. Preserve existing project identity and user file contents. Bootstrap creates no Agent.
4. For explicit manual onboarding, the CLI discovers a project from its root or a nested directory. Outside it, use global `--project-root <actual path>`. Do not ask users to repeatedly set project/state environment variables.
5. If the user selected an existing daemon for another project, use `daemon start --reuse <that project's actual root>` from the new project. Otherwise connect starts the selected project's daemon if needed.

## Codex Desktop: explicit manual connection

Run `agent prepare --adapter codex --role worker` inside the actual conversation (use main only when the user selected it). This observes the host's real conversation and local app endpoint and writes a private request file. It creates no Agent or authority. Never invent a conversation ID or use a display profile as identity.

The prepare result includes one fully filled PowerShell command for `agent connect --request-file ...`. If the user already authorized joining, execute it yourself. If execution needs the user, show exactly that one command: no ID placeholders, token copying, separate enroll or appoint ceremony. Do not show raw request contents.

Connect reuses the conversation's private state, starts/verifies the daemon, enrolls, binds the original Desktop conversation and configures the shared MCP server named `tsunagou`. Its `enrolled` result confirms enrollment, **not that the original chat has loaded the MCP**. Repeated connect must preserve the Agent identity.

Then call `context__project_read` **from this original conversation's MCP tools**. Report ready_worker/ready_main only when it returns the expected project, own Agent, ready session, selected role and registered host binding. A headless bootstrap query or another Agent's query cannot satisfy this step.

The shared bridge routes every call by host-provided MCP thread metadata. Separate chats/subagents must use separate identities; do not share session files or substitute agent IDs in tool arguments. Display profiles do not control identity.

If tools are missing after first configuration, use a documented host reload operation if available. Otherwise explain one concrete first-load action (fully quit/reopen Codex, then return to the same chat and call context). Do not promise Ctrl+R restarts MCP. If one restart does not help, investigate the recorded error and server configuration instead of asking for repeated restarts. Existing loaded shared bridges read new route/ticket/endpoint state on each call.

## DeepSeek Harness Desktop

Use the ordinary Desktop conversation opened in the selected project. When `tsunagou_connect` is available, call it directly. Otherwise run the installed CLI's `agent prepare --adapter deepseek` to register the existing provider in the actual Desktop profile; this step does not enroll an Agent or start the daemon. Let native profile reload load the tool. If necessary, fully quit/reopen Desktop once and return to the same conversation; investigate a persistent failure instead of requesting repeated restarts or an external terminal command.

If that conversation's working directory is not the coordination root (common: the console creates projects under its own root, and a project may coordinate a business workspace), the project still resolves: `tsunagou_connect` invokes the installed CLI, which falls back to the pending console request for the `deepseek` adapter when the working directory names no project. Check it with `agent pending --adapter deepseek` if the join result looks unexpected, and ask the user to prepare that project's Agent in the console when it answers `status: none`.

Call `tsunagou_connect` without a role to preserve an existing role or join as worker. Pass main only when the user explicitly chose main. The tool reads the real conversation and working directory inside the host and invokes the fixed installed CLI. Never supply or copy session IDs, credentials, commands or another conversation's overlay. The shared profile contains no Agent credential; each tool call chooses its own private route using host metadata.

An enrolled result is only preparation. This same conversation must call `mcp__tsunagou__context__project_read` and verify the expected project, its own Agent, selected role and ready session before reporting success. DeepSeek does not claim Codex's original-chat automatic wake. If service startup, provider loading or enrollment fails, report that specific stage and preserve the existing identity.

## Other adapters

Use their actual host-provided conversation identity and supported bridge configuration. Do not claim another host supports shared thread metadata or original-chat wake without a working implementation. Retain the registered low-level enroll/rebind path for diagnostics, not as the normal Desktop onboarding ritual.

## After attachment

- Read own context, incremental inbox and blackboard. A worker selects eligible published work, calls `task.begin` with the current revision, works in the returned scope and calls `task.submit`. Begin captures the baseline/reserves resources; submit captures results/releases resources. Use `task.block` when actually blocked.
- Main proactively handles ordinary worker requests under existing authorization: check existing tasks and duplicate requests, publish suitable work or give a concrete reply, and fulfill response obligations. Reading or ACK alone is not a response. Do not ask whether to do ordinary scheduling again.
- Main handles Git writes and coordination. Major design/scope changes and project-completion confirmation stay user-controlled. Skill text and Full Access do not expand Tsunagou authority.
- Lack of recent activity does not mean a worker died. Resources remain owned until explicit release/recovery, not until a timer expires.

## Recovery

Inspect `daemon status`, `doctor` and `agent list --json` yourself where authorized. Keep diagnostics to statuses, IDs, timestamps and error codes. The bridge normally reuses its saved session; restart/epoch changes trigger reconnect. For a console request, retry agent join from the same conversation; use prepare/connect only for the explicit manual workflow when the host endpoint or enrollment material needs repair. Do not issue new identities to hide a connection failure.

Use the installed source's `docs/overview/cli-http-manual.md` for real command syntax. Do not copy old profile-based onboarding examples from historical documents. Never print control.token, ticket.json, session tokens, Authorization headers or raw pipe addresses.

End with actual project_id, agent_id, role and state, or the exact unresolved error and one next action. Do not claim successful automatic wake from enrollment alone; wake is demonstrated by a daemon message causing the original conversation to run.
