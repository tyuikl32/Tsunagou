# PT5 CLI 查询与责任时间线

- created_at: 2026-09-27T14:39:38Z
- status: planning；parent: persistence-traceability；depends_on: PT4

## 目标

让用户无需读 SQLite 或手工拼 HTTP 就能查询项目/任务历史、审计事件、checkpoint 和证据，并得到稳定分页和责任时间线。

## 范围与约束

- 增加只读 projection：`project history`、`task history`、`audit event`、`checkpoint list/verify`；恢复仍是 preview/confirm user-only 动作。
- 默认 limit 50、最大 200；cursor 基于 event_seq；时间为 RFC3339 UTC；响应含 `next_cursor`、`projection_version`、`as_of_event_seq`。
- 查询沿用 project、actor、私有消息和 artifact 权限；unknown time 显式展示为 unknown，不用迁移时间补齐。
- HTTP 与 CLI 共享 dispatcher/DTO；查询错误不写业务事件。

## 交付与验收

1. 提供 JSON 和人类可读输出，字段包含 actor/subject/action/outcome/evidence level/causation。
2. 用超过 200 条事件、边界时间、无效 cursor、权限外私信和 artifact 测试无重复/缺页与拒绝。
3. 验证 CLI/HTTP 同一请求得到等价投影，导出含 schema、source project/lineage 和 exported_at。

## 不做

不开放任意 SQLite 查询、不绕过领域授权、不把 debug log 当 audit、不提供远程多租户审计后台。
