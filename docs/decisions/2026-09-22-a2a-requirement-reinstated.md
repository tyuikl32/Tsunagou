# A2A 要求恢复与当前缺口

## 事实核对

初版设计明确要求 Agent 之间通过 A2A 进行需求澄清、任务依赖询问、设计讨论、异议提出、变更通知、冲突协商、资源影响询问和验证结果共享。结构化消息表达身份、任务、项目版本、设计版本和影响范围；自然语言承载理解、假设、不确定性和方案比较；重要事实仍必须落到 Project State/Decision Log。

历史研究同时正确指出 MCP 与 A2A 分层：MCP 连接模型/Agent 与工具、资源，A2A 连接相互独立的 Agent；A2A Task 不能替代 Tsunagou 内部任务、权限、租约、契约和事件事实。后续实施计划把这条边界误读成“首发可以没有 A2A”，实现因此只完成了内部持久消息和 MCP inbox。

## 恢复前的实现差异

- `message.send`、`inbox.claim/fetch/presented/ack` 是 Tsunagou 内部消息投影，不是 A2A wire protocol。
- bridge 是 MCP stdio server，当前没有 Agent Card、A2A JSON-RPC/HTTP binding、A2A task/context 映射、streaming 或 push notification endpoint。
- daemon 能持久化消息，但不会把消息转换成 A2A push，也不能让空闲 Codex 对话自动开始新一轮。
- 因此此前“这是正常的”只适用于当前未完成实现的能力边界，不能作为初版设计的验收结论。

## 已落实的首版边界

首版 A2A adapter/gateway 已增加，内部领域状态仍是唯一事实源：

1. 已暴露 Agent Card、版本化 JSON-RPC HTTP endpoint，并声明消息、任务查询、streaming/push 和 wake 能力。
2. 已将 A2A Message/Task/Context 映射到内部 message、Task 和项目 context；保留 owner、scope、epoch、认证和幂等约束。原始 parts/metadata 进入内部消息 `a2a` 审计区域。
3. A2A 入站写入复用 daemon 的 authenticator、dispatcher 和事务/持久化路径，不能通过 A2A 绕过用户控制命令或主 Agent 边界。
4. 当前没有可验证的宿主反向唤醒 API。实现了 A2A 1.0 inline `taskPushNotificationConfig` 的 callback 投递；Agent Card 的 `pushNotifications` 只反映 notifier 是否装配，`wake=push-notification` 只表示 callback 请求，不伪造 host wake。
5. A2A Task 终态和内部 Task 终态保持独立；首版 `tasks/cancel`、`tasks/fail`、`tasks/retry` 已分别映射到内部取消请求、执行失败和 `task.recover(reopen)`，仍由内部 owner、authority、revision 和事务规则决定结果。

剩余工作是支持真实 receiver 的可选 streaming/push notifier、Artifact 专用 A2A 传输和把取消/失败进度扩展为更多 A2A 方法。这些扩展不改变首版内部真相和认证边界。

首版 A2A 已不再只是规划项；后续文档应把 message/send inline push 标为已支持，把 streaming、任务 push config CRUD 和 host wake 标为未支持，直到有可复现实证。
