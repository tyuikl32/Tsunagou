# PT 总体设计入口

- created_at: 2026-09-27T14:39:38Z
- status: in_progress / implementation_authorized

唯一细化契约为 [持久化溯源修复方案](../../../docs/implementation/persistence-traceability-plan.md)。它规定时间/责任模型、secret receipt、scope 证据、checkpoint、查询、降噪、迁移及验收矩阵；子任务 design 只细化自己的责任，不另造同名字段。

## 设计不变量

1. 事实先由 daemon 在项目 scope 内以服务端时间、actor、subject、command 和 revision 记录；语义解释由主 Agent/用户完成。
2. 业务事务和事件引用一起提交；文件、Git、A2A callback 等外部副作用在提交后以可重试 operation 处理。
3. 可用 secret 只在私有 delivery bucket 短暂交付；SQLite、checkpoint、artifact、日志和公共响应只保存安全 receipt。
4. 共享 checkpoint 使用白名单 DTO；runtime epoch、grant、lease、宿主 conversation 和私有消息留在本机动态层。
5. 所有查询均是权限受限的只读 projection；CLI、HTTP、bridge 不各自造语义。

[原始证据与校正](research/evidence.md)说明哪些是当前实现缺陷，哪些只是演示未覆盖。
任务依赖在 [机器计划](../../../docs/implementation/persistence-traceability-tasks.json) 与各 task.json 的 `meta.depends_on` 中一致维护。当前不启动任何 task 或迁移。
