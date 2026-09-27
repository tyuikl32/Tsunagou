# PT1 时间戳、责任主体与审计契约

- created_at: 2026-09-27T14:39:38Z
- status: completed；parent: persistence-traceability

## 目标

让八模块所有新业务事实都有同一种服务端时间、actor、subject、因果、revision 和 evidence 引用；让重试、分页和旧数据迁移可解释。

## 范围与约束

- DB 内部使用整数 UTC 毫秒，HTTP/CLI 使用 RFC3339 UTC 毫秒；事件 `occurred_at` 不可变，实体另有 `created_at`/`updated_at`。
- actor 必须指向实际登记的 user/Agent/session/conversation；同 IDE 的不同对话不能合并。客户端时间只能保留为观测字段，不能替代 daemon 时间。
- 相同 command ID + request digest 重试原 receipt，不新增业务事件；无变化的查询不推进 revision。
- 旧记录无法证明时保持 `null`/`unknown`，迁移执行时间另记；不伪造历史发生时间。

## 交付与验收

1. 更新 Schema、数据库投影、事件写入、HTTP/CLI 查询和 fixtures，字段名完全采用总设计第 3 节。
2. 添加 actor/subject/caused_by/revision/evidence 的正反例以及 UTC、未知时间、跨时区和游标分页测试。
3. 用同一 command 重试和冲突 digest 测试无重复事件；验证项目 scope、私有消息和 actor 过滤不越权。
4. 输出一份不含秘密的 schema/迁移说明，明确旧表哪些时间未知。

## 不做

不引入全量 Event Sourcing、不解释 CoT、不从迁移时间推断发生时间，不替 PT2 设计秘密存储。
