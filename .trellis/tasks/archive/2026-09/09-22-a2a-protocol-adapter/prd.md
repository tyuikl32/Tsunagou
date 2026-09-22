# 实现 A2A 协议适配与消息唤醒边界

## Goal

实现初版设计要求的 Agent-to-Agent 边界协议：Agent Card、A2A 消息/任务映射、流式或推送能力声明，并保持 Tsunagou 内部任务、权限、租约和持久化事实为唯一真相。

## Requirements

- The daemon must expose a versioned A2A boundary with an Agent Card and a documented HTTP/JSON-RPC binding; the generic MCP bridge must not be described as the A2A implementation.
- A2A Message, Task, Context and Artifact concepts must map to Tsunagou facts without replacing Project, Task, Attempt, Grant, Lease, Contract, Operation or event history as the source of truth.
- A2A ingress and egress must use the same session authentication, project scope, owner, revision, connection epoch, idempotency and user-only policies as HTTP/MCP commands. No actor fields in A2A payload may override the authenticated principal.
- The initial local profile must support agent-to-agent request/response and task progress visibility. Streaming and push notification capabilities must be explicitly declared as supported, unsupported or unknown with evidence.
- A2A delivery must remain durable when a target host is idle. A2A push may notify a client that exposes a real endpoint; it must never claim that a Codex conversation was awakened when the host has no verified wake API.
- A2A cancellation, failure, retry and duplicate delivery must translate to internal transitions with auditable outcomes; an external A2A task cannot delete or bypass internal facts.

## Acceptance Criteria

- [ ] Agent Card is served from a stable local endpoint and includes protocol/version, supported interfaces, declared skills and truthful streaming/push capability status.
- [ ] An authenticated A2A request creates/updates the corresponding internal message or task through the common dispatcher/UoW; unauthorized project, owner, revision and user-only cases are rejected.
- [ ] A2A response/progress can be queried or streamed with stable context/task identity, idempotent retry and no duplicate internal message/action.
- [ ] Push notification configuration is either implemented with a local test receiver or explicitly reported unsupported; an idle Codex session is never reported awakened without host evidence.
- [ ] A2A and MCP expose equivalent business outcomes for the same authenticated action, while internal state remains the sole source of truth.
- [ ] Protocol fixtures, schema/HTTP tests, bridge smoke and documentation include positive and negative A2A cases and distinguish delivery, presentation and host wake.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
