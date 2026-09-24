# A2A 唤醒与 bridge 会话自愈

## Goal

把 bridge 旧进程会话恢复与 A2A message/send push notification 纳入可验收任务，修复晚到会话文件和异步唤醒投递边界。

## Requirements

- F1: an already-running stdio bridge must re-read its private ticket/session files when a later tool call arrives. It must recover a late enrollment without requiring a Codex restart, and must fence the credential to the same conversation digest.
- F1: a daemon epoch/authentication failure must trigger at most one session recovery and one idempotent command retry. A failed recovery must remain an explicit typed `not_enrolled`/authentication error.
- F2: `message/send` must accept the A2A 1.0 `configuration.taskPushNotificationConfig` shape (`url`, optional `token`, optional `authentication`) in addition to Tsunagou's existing routing metadata.
- F2: durable message acceptance is independent from callback delivery. Callback credentials may be used for the request but must never be persisted in project state or written to logs.
- F2: the Agent Card may advertise `pushNotifications` only when a notifier is assembled. The response must distinguish durable delivery, push delivery, push failure, and host wake request.
- F2: a callback is a protocol notification request. It must not be reported as a resumed LLM turn unless a host adapter explicitly supplies that evidence.

## Acceptance Criteria

- [ ] A bridge process started before `agent connect` can successfully execute its first authenticated tool call after the ticket/session file is created, without process restart.
- [ ] The same bridge remains isolated from another conversation's session file and never logs a token or ticket.
- [ ] A2A schema validation accepts a standard push configuration and rejects malformed URL/authentication values before dispatch.
- [ ] A successful callback returns `push.status=delivered`; an unavailable callback returns `push.status=failed` while the message remains pullable.
- [ ] Agent Card capability, response metadata, and documentation agree about `pushNotifications`, `delivery`, `wake`, and the absence of generic host wake.
- [ ] Python unit tests, bridge TypeScript build, protocol/schema tests, and docs validation pass.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
