# A2A message/send push notification 与宿主唤醒边界

## Requirements

- 采用 A2A 1.0 `SendMessageConfiguration.taskPushNotificationConfig`，不创造同义 Tsunagou 私有字段。
- 回调投递失败不能回滚已提交消息；pull inbox 是永久恢复路径。
- 返回值和 Agent Card 必须把 push delivery 与 host wake 分开表达。
- callback 凭据只能用于当前 HTTP 请求，禁止进入 SQLite module state、消息 payload、事件或日志。

## Acceptance Criteria

- [ ] 有效 push config 被 schema 和 gateway 接受并调用 notifier。
- [ ] 无效 URL、token、authentication 在 message.send 前返回稳定协议错误。
- [ ] 成功、失败、未请求三种状态可从 message/send 响应读取，消息仍可 pull。
- [ ] `pushNotifications` 与实际 notifier 装配一致；没有宿主唤醒证据时不报告 `host_wake=started`。
- [ ] 官方 A2A 规范链接和 Tsunagou 的四层状态解释进入实现文档。
