# Push notification 设计

A2A 服务端接收 `configuration.taskPushNotificationConfig` 后，在 durable `message.send` 提交之后投递一个 HTTP 事件。事件是 Tsunagou 对 message accepted 的扩展，不伪装成没有 task id 的 TaskStatusUpdateEvent。token 与 authentication 仅存于调用栈；durable state 只保留是否请求以及 URL digest。

默认 notifier 使用 Python 标准库 HTTP 客户端并设置 2 秒超时。实际宿主 adapter 可注入自己的 notifier，将事件转成宿主可理解的通知；adapter 如果能证明启动新回合，应在后续状态端口上报告该事实，gateway 本身不推断。
