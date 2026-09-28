# PT1 兼容迁移和协议说明

记录时间：2026-09-27T16:28:21Z（文档记录时间，不用于补历史事件时间）。

- 沿用每项目 SQLite；事件新列和实体审计元数据通过兼容迁移增加，不进行全量 Event Sourcing。领域状态仍由原模块拥有，审计观察计数不能替代领域 CAS。
- 有可靠旧 `occurred_at` 时保持原值；原记录没有可靠发生/写入时间时保留空值。历史 actor、subject、revision 和证据未记录的部分保持 unknown/null，不从当前主 Agent 或迁移时刻反推。
- 新审计字段只输出已登记会话身份、安全原因码、版本和引用，不导出状态 payload、私信正文、原始宿主对话 ID 或凭据。
- `event_id/event_seq` 为规范字段，`source_event_id/source_event_seq` 暂为兼容别名。页级 `snapshot_event_seq` 与 `as_of_event_seq` 相等。Schema 位于 `protocol/schemas/queries/audit-page.schema.json`；Python/TS 和安装包镜像由 `tools/codegen/generate_audit.py` 生成。
- PT1 不处理历史明文凭据擦除。旧 command result、WAL 和备份中的秘密由 PT2 的撤销、脱敏迁移处理；PT1 通过不等于旧数据库可安全导出。
- 游标只存页位置、快照序号和上下文 digest，以本轮 daemon 的内存密钥签名；15 分钟后、daemon 重启后或改变认证身份/查询条件时重查首屏。SQLite 不存游标签名秘密。
- 实际字段/SQL 迁移测试和完成结论以 implement.md 最终记录为准。本说明不意味着真实外部项目已经迁移。
