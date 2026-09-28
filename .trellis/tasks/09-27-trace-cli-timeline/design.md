# PT5 设计

created_at: 2026-09-27T14:39:38Z

在现有 command dispatcher 上增加只读 query service：`project history`、`task history`、`audit event`、`checkpoint list/verify`。CLI 与 HTTP 共用 DTO、权限和 cursor；cursor 由 `(event_seq,event_id)` 签发，默认 50、最大 200，响应给出 projection version 和 as-of seq。

私有消息和 artifact 先走原域权限，不能因 audit 查询而扩大可见范围。恢复仍是 preview/confirm user-only；导出带 source project/lineage、schema 和 exported_at。
