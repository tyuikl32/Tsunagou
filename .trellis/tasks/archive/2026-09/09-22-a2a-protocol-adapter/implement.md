# 实施计划

1. [x] 固定 A2A 1.0、Agent Card 字段、HTTP/JSON-RPC 路由和内部关联字段，补 `protocol/schemas/a2a/` 与脱敏 fixtures；保留官方参考链接。
2. [x] 实现 `src/tsunagou/api/a2a.py` gateway，复用 authenticator、dispatcher 和 query provider，不创建第二套 MessageStore/TaskStore/授权。
3. [x] 实现同步 `message/send`、`tasks/get`、`tasks/cancel`、`tasks/fail`、`tasks/retry` 和任务状态映射；同一外部 request/message ID 映射同一内部 command id，认证、project scope、epoch、owner 和 dispatcher 幂等规则复用。
4. [x] Agent Card 明确声明 `streaming=false`、`pushNotifications=false` 和 `wake=unsupported`。没有真实 host wake API 时不伪造唤醒；stream/push receiver 留作后续扩展。
5. [x] 将 A2A 接入 Agent Card、HTTP 文档和 standalone 状态说明，分别记录 delivery、presentation、host wake 三种证据。
6. [x] 运行 schema 校验、A2A 单元测试、真实 uvicorn loopback 测试和 `audit_standalone.py` 的真实 build_application 检查；A2A 检查结果见 `docs/standalone/a2a-audit-2026-09-22.json`。

回滚：A2A adapter 可独立关闭，内部 MCP/HTTP 协作事实不受影响；禁止通过回滚删除已经持久化的关联或事件。
