# 技术设计

## 分层

`src/tsunagou/api/a2a.py`（或等价 adapter）只负责 A2A wire 解析、Agent Card、认证转译和响应映射；内部写入仍进入现有 `CommandDispatcher`/ProjectRuntime/UoW。不得在 A2A 路由里新建 MessageStore、TaskService 或第二套授权。

外部 A2A `contextId`、`taskId`、`messageId` 和 `artifact` 引用保存为边界关联/审计字段，映射到内部 project/task/attempt/message/operation ID。首版只把 `tsunagou:task:<internal_id>` 作为受命名空间保护的只读/受授权转换投影，不创建第二个外部 Task store；未来需要独立外部生命周期时再增加持久关联 manifest。所有状态转换必须先通过内部 owner/scope/revision/epoch 检查。

Agent Card 声明本地 daemon 可接受的协议版本、JSON/HTTP interface、skills 和 capability status。当前 generic Codex bridge 不提供可被 daemon 反向调用的宿主 wake endpoint，所以默认 `pushNotifications`/`streaming` 必须为 `unsupported` 或 `unknown`，不能填 `true`。支持真实 receiver 的 adapter 再单独启用 push/stream。

## 最小传输

首版先实现同步 A2A message/send 与 task/query/status 映射，随后实现流式/推送扩展。每个请求都绑定 authenticated agent/session/project，使用现有 protocol/schema digest 和 command id；同一 A2A message/retry 映射到同一内部幂等键。错误返回 A2A 层错误码，同时保留 Tsunagou command/event/audit 证据。

## 安全与恢复

不接受 A2A payload 中的 sender/role/authority 作为可信身份；不把外部 callback URL 自动加入 allowlist。push 配置需要用户/项目策略允许、loopback 或显式可信目标，并通过 outbox/Job 投递；投递失败不改变内部事实，pull 仍可恢复。旧 session/epoch、跨项目 context、过期 revision 和 user-only action 必须与 MCP/HTTP 得到同等拒绝。
