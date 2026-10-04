# Fix DSH console project selection

## Goal

Make DSH console enrollment honor the pending project selection while preserving manual cwd fallback.

## Requirements

- When a pending DeepSeek enrollment exists, DSH onboarding must use its selected project root even when the chat cwd is another Tsunagou project.
- When no pending DeepSeek enrollment exists, preserve manual onboarding by resolving the project from the chat cwd or its parent directories.
- Explicit project selection remains authoritative and must not be silently overridden.
- A connected DSH conversation that conflicts with the pending project must fail with a stable project-mismatch error rather than creating a second identity.
- OpenCode and Codex enrollment behavior must remain unchanged.
- This task does not change enrollment observation, claim/receipt state transitions, frontend copy, or waiting-page behavior.

## Acceptance Criteria

- [ ] Pending project A wins over chat cwd project B.
- [ ] Pending project A is used when cwd is not a Tsunagou project.
- [ ] No pending record preserves cwd-based manual onboarding.
- [ ] Existing session/project mismatch is rejected without creating a second identity.
- [ ] Same-project cwd and pending enrollment continue to work.
- [ ] Existing adapter and CLI tests pass; OpenCode/Codex paths remain green.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
