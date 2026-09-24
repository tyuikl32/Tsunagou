# A2A durable message 到 host wake 编排

## Goal

实现 R3/R6：callback 到 wake attempt、幂等、活动 turn 排队、重试、证据链和 durable pull 回退，接入阶段 A provider。

## Requirements

- TBD

## Acceptance Criteria

- [ ] TBD

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
# A2A durable message 到 host wake 编排

## Goal

把 durable A2A delivery 变成可重放、可审计的 host wake attempt，并接入任一 HostWakePort provider。

## Scope

- durable commit 后 callback/delivery 触发 dispatcher。
- `(agent_id, message_id, binding_revision)` 幂等键和 attempt 状态机。
- binding/epoch/scope/policy 校验、活动 turn 排队、超时、重试和 daemon 重启恢复。
- `callback_received` 到 `agent_presented` 的证据关联。
- 失败时保持 durable pull，禁止把 callback 2xx 当作宿主唤醒成功。

## Acceptance

- 同一 callback 重试不创建第二个 attempt 或第二个 turn；改变消息语义复用 ID 时返回冲突。
- 活动 turn 时默认入队，不能并发启动第二个 turn；后续策略由显式状态决定。
- daemon/app-server 重启后 `starting/running/unknown` attempt 会先 inspect/probe 再恢复，不能盲目重复 turn。
- 无 binding、binding stale、epoch 过期、权限 digest 不一致和 provider unknown 都返回可恢复状态。
- A2A 消息仍可由目标 Agent pull；任何 wake 失败不回滚已提交消息。

## Dependencies

- 依赖 port/binding 与 managed provider。
- 复用 `CommandDispatcher`、现有 delivery/outbox 和统一错误/审计机制。
