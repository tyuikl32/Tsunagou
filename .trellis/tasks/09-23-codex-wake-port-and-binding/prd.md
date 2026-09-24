# Codex host wake port、binding store 与能力证据

## Goal

确定 R1/R2/R4/R5 的 host-neutral 接口、私有 binding、evidence、错误码、脱敏和项目边界，提供 A/B 共用的数据与协议基线。

## Requirements

- TBD

## Acceptance Criteria

- [ ] TBD

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
# Codex host wake port、binding store 与能力证据

## Goal

建立 A/B 两阶段共用的 host-neutral contract、私有 binding、能力报告和证据模型；不接入具体 Codex transport。

## Scope

- 定义 `HostWakePort`、`HostBindingRef`、`HostWakeRequest`、`WakeAttempt`、`HostCapabilityReport`、`HostEvidence` DTO。
- 定义 host wake 错误码、状态转移、脱敏规则和 connection epoch 语义。
- 在用户级 adapter state 中保存原始 host binding，在项目事实中只保存引用、digest、状态和 revision。
- 提供 repository/transaction port，复用现有 SQLite/runtime 约定，不新增第二套领域真相。

## Acceptance

- A/B provider 可以只依赖同一组 Python port，不引用对方实现。
- `agent_id`、thread ID、session ID、message ID、wake attempt ID 均有独立类型/字段，互不替代。
- binding revision、scope digest、policy digest 或 connection epoch 不匹配时返回明确错误，不能命中旧授权缓存。
- 项目查询、日志、A2A payload 和模型 prompt 不包含 token、原始 endpoint、完整 transcript、原始私有路径或原始 thread/session ID。
- evidence 能区分 callback、thread resume/start、turn start、turn complete、Agent presented；callback 2xx 不得映射为 turn started。
- 单元测试覆盖相同 attempt 重放、不同输入幂等冲突、状态降级和未知能力。

## Dependencies

- 读取 `.trellis/spec/backend/database-guidelines.md`、`.trellis/spec/backend/entrypoint-contracts.md`、`docs/implementation/a2a-boundary.md`。
- 依赖现有 A2A delivery、session/epoch 和审计事件实现。
