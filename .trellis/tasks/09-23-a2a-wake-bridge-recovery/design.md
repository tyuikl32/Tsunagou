# 设计：A2A 唤醒与 bridge 会话自愈

## 约束与事实边界

官方 A2A 1.0 的 `SendMessageRequest.configuration.taskPushNotificationConfig` 允许发送方提供回调 URL、token 和 HTTP authentication；Agent Card 的 `capabilities.pushNotifications` 只表示服务端可以发送异步通知。该协议不替具体 IDE/LLM 暴露“启动一个新回合”的机械 API。因此 Tsunagou 将事实分成四层：消息持久化、push callback 投递、宿主 adapter 收到通知、宿主实际开始/恢复回合。

## F1 bridge 自愈

`packages/bridge-server/src/server.ts` 保留每个 bridge 的私有 `sessionFile`，但把 ticket/session 读取和 enroll/rebind/reconnect 组合为可重复调用的 `attemptSessionRecovery()`。进程启动调用一次；`CallTool` 发现内存没有 session 时再次调用，并用单个 promise 合并并发调用。认证失败或旧 epoch 只允许恢复一次后重试原 command；不会为不确定的业务响应盲目生成新 command。

恢复顺序是：重新读取 ticket；计算 conversation binding digest；加载对应 session 文件；ticket 存在时执行 rebind/enroll 并消费 ticket；没有 ticket 但有 session 时执行 reconnect；失败则清空内存凭据并返回稳定错误。所有诊断只写 digest、状态和环境变量名。

## F2 A2A push

`A2AGateway` 解析标准 `taskPushNotificationConfig`，校验 URL、token 和 authentication 的形状。dispatch 先经过现有 `message.send`，因此消息幂等和项目 SQLite 事实仍是唯一真相；提交成功后调用注入的 `push_notifier`。默认 notifier 用短超时 HTTP POST，测试和宿主 adapter 可注入替代实现。

回调事件使用 Tsunagou 扩展包装已接受消息，不将 token/credentials 放入事件或 durable payload。回调异常只生成 `push.status=failed`，接收方仍可通过 inbox pull 恢复。Agent Card 的 push 能力取决于 notifier 是否装配；`wake=requested` 表示已请求异步通知，不表示 Codex 已经运行。

## 不在本任务内

- 不伪造 Codex、Claude 或其他宿主的隐藏唤醒 API。
- 不把 callback URL/token 做成全局配置或跨 conversation 共享凭据。
- 不引入新的任务/消息事实表；不绕过 `CommandDispatcher` 和现有幂等事务。
