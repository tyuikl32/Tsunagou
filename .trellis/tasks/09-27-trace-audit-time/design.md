# PT1 设计

created_at: 2026-09-27T14:39:38Z

以 `AuditEnvelope` 作为跨模块唯一包络：数据库存整数 UTC 毫秒，协议转换为 RFC3339 UTC 毫秒；`event_seq` 为项目游标，`event_id` 为不变身份。先在 application boundary 生成 actor/session、subject、command、request digest 和因果引用，再由 SQLite UoW 分配序号并写事件、projection、safe receipt。实体时间和事件时间分开，历史未知值保持 null。

分页只按 `(event_seq, event_id)` 游标，时间和 actor/subject 是过滤条件；HTTP/CLI 使用同一个 query service。兼容迁移只新增 nullable 字段和 projection version，不重写过去的语义。禁止让 adapter、blackboard 或 debug log 另造时间/actor 字段。
