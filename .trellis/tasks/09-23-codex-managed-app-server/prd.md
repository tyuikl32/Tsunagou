# Managed Codex app-server provider 与真实 probe

## Goal

实现阶段 A 的 Codex app-server transport、JSON-RPC client、thread lifecycle、turn events、版本/能力 probe 和连接恢复。

## Requirements

- TBD

## Acceptance Criteria

- [ ] TBD

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
# Managed Codex app-server provider 与真实 probe

## Goal

实现阶段 A 的 Codex app-server transport/client/provider，验证 R1、R2、R5、R7，并为阶段 B 保留同一 adapter port。

## Scope

- 本地 stdio JSONL transport；其他 transport 只做 capability enumeration，未经证据不得报告支持。
- `initialize`/`initialized`、`thread/start`、`thread/resume`、`turn/start` 和 `turn/*`/`item/*` 事件。
- request/response correlation、超时、断线、connection epoch、一次重试上限、未知 method 和协议错误分类。
- Managed provider 的 app-server 进程/连接生命周期、thread handle 和 probe 输出。
- 版本、transport、可用 methods、thread state、失败原因的脱敏 evidence fixture。

## Acceptance

- 模拟 app-server 可完成 initialize、thread start/resume、turn start、事件终态和关闭。
- 真实当前 Codex 版本 probe 能给出版本、transport、method capability 和失败原因；未知字段/能力明确为 `unknown`。
- app-server 重启后能 probe 并 resume 原 binding；不能静默生成第二个 Agent 或重复 thread。
- 超时/断线不会把 `turn_started` 或 `turn_completed` 写成成功；stdout、stderr 和 prompt 均不泄密。
- provider 不决定项目权限、不创建 Task/Message、不绕过 HostWakePort。

## Dependencies

- 依赖 `codex-wake-port-and-binding` 的 DTO、错误和 evidence。
- 参考官方 [Codex App Server](https://learn.chatgpt.com/docs/app-server)；若实际版本与文档不一致，以 probe 为准。
