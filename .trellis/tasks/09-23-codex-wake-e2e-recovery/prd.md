# 宿主唤醒端到端验收与故障恢复

## Goal

建立 managed provider 的真实 Codex E2E、daemon/app-server 重启、旧 epoch、超时、权限边界和人工操作文档；完成 A 阶段 R1–R7 验收。

## Requirements

- TBD

## Acceptance Criteria

- [ ] TBD

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
# Managed host wake 端到端验收与故障恢复

## Goal

用真实 Codex managed app-server 完成阶段 A 的 A2A 唤醒验收，并形成可复现的人工调试文档。

## Scope

- worker -> `message/send` -> durable delivery -> callback -> managed thread -> real `turn/start` -> Agent context/inbox pull。
- daemon、app-server、bridge 重启，旧 epoch、重复 callback、timeout、活动 turn、scope mismatch 和目标离线。
- 记录版本、命令、时间、退出码、evidence 摘要和失败原因，不记录 token/transcript/private path。
- 更新 `docs/implementation/codex-host-wake.md`、A 阶段验收记录和操作手册。

## Acceptance

- 至少一条真实 E2E 记录完整呈现五类 evidence，且能按 message/attempt 追踪。
- daemon/app-server 重启不会丢 durable message，也不会造成重复 Agent、重复 durable message 或并发重复 turn。
- Agent 能在被唤醒 turn 中自主读取 context/inbox；消息正文不是 wake prompt 的直接注入。
- 权限/主从边界和 Full Access 语义保持不变。
- `python tools/docs/validate_docs.py`、相关 Python/TS 测试和 Windows smoke 均通过。

## Dependencies

- 依赖 port、managed provider 和 A2A dispatcher 三项任务完成。
- 阶段 A 完成后，父任务才可进入 Desktop attach。
