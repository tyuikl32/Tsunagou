# 项目内自动安装与消息唤醒边界

## Goal

让 Agent 在明确当前业务项目后自动完成项目本地 Tsunagou bootstrap，并记录消息持久化、pull 与宿主唤醒边界，避免把 daemon 投递误称为 Codex 对话自动唤醒。

## Requirements

- When the user asks an Agent to install Tsunagou in the current business project, the Agent must preserve the business project root before cloning the Tsunagou source checkout and pass that root explicitly to the installer.
- An explicit installer `--project-root` is a project-selection signal. If the selected Git project has no `.tsunagou/project.json`, the installer initializes the project with deterministic, user-visible name/objective inputs before materializing project-local entries; an already initialized project is not reinitialized.
- The automatic path must still keep source checkout, project-shared entries, and `.tsunagou/local` private runtime data separate. It must not start the daemon, enroll a conversation, appoint main, publish a task, or print credentials.
- Installation output and skill documentation must distinguish source installation, project initialization, project bootstrap, and Agent readiness. A successful install must report the project root and each stage result.
- Durable `message.send`/inbox delivery must remain available without a live host conversation. The daemon must not claim it can wake a sleeping Codex conversation unless a host-specific wake channel has real evidence.
- Documentation must explain the current pull-first behavior: a connected Agent can see a message on its next inbox pull/turn, while an idle host conversation requires host-supported wake or user reopening it. Missing wake must not lose messages or block unrelated Agents.

## Acceptance Criteria

- [x] A dry-run with an explicit project root includes `project init` when the project manifest is absent and includes `project bootstrap`; a dry-run without `--project-root` includes neither.
- [x] A real temporary Git project can be installed with an explicit project root, producing `project.json`, `project-integration.json`, `agent-context.md`, the project skill and managed `AGENTS.md` content; a second run is idempotent.
- [x] Existing project initialization is detected and preserved; no second project ID is created and user-authored files remain unchanged.
- [x] Installer/skill docs provide a copyable current-project workflow and state the exact non-actions (no daemon start, enrollment, main appointment, task publication or secret output).
- [x] Tests and docs demonstrate that message persistence/delivery is pull-based and that no automatic Codex wake is promised by the generic bridge; the current limitation and host-specific extension point are explicit.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
