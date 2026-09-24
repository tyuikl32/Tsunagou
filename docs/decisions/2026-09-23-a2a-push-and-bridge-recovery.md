# A2A push notification 与 bridge 会话恢复决策

日期：2026-09-23

## 外部事实

官方 A2A 1.0 的 `SendMessageRequest` 包含 `configuration`，其中的 `taskPushNotificationConfig` 可携带回调 URL、token 和 HTTP authentication；Agent Card 的 `capabilities.pushNotifications` 表示服务端是否能发送异步通知。相关定义见 [A2A specification](https://a2a-protocol.org/latest/specification/) 和协议源文件中的 `SendMessageConfiguration`/`TaskPushNotificationConfig`。

这是一种服务端到客户端的异步 HTTP 通知机制。它给客户端一个唤醒信号或任务状态更新入口，但不替任意 IDE 暴露“启动新 LLM 回合”的统一系统 API。A2A 与 MCP 的职责仍然不同：A2A 表达 Agent 间协作，MCP 是宿主向 Agent 提供工具。

## Tsunagou 决策

1. `message/send` 接受标准 `configuration.taskPushNotificationConfig`；消息先通过既有 `CommandDispatcher` 持久提交，再以有界超时尝试 HTTP callback。当前是 post-commit inline notifier，持久重试队列另列后续 durability 任务。
2. callback 失败不回滚消息，inbox pull 是可靠恢复路径。响应区分 `delivery`、`push.status`、`presentation` 和 `host wake`，禁止把任一状态冒充另一状态。
3. token/credentials 仅在当前 notifier 调用中存在，不进入项目 SQLite、消息 payload、事件或日志。Agent Card 只有在 notifier 装配时才返回 `pushNotifications=true`。
4. 当前 generic Codex stdio bridge 没有经过验证的宿主反向唤醒 API，因此 `wake=requested` 只代表 callback 请求；真正的 `host_wake=started` 必须由具体 adapter 提供可复现证据。
5. bridge 进程不能把 admission 文件只读一次。启动后晚到的 ticket/session 必须在下一次 MCP tool call 重新加载；旧 epoch 仅进行一次恢复并复用原 command id 重试。

## 任务与证据

- F1：`.trellis/tasks/09-23-bridge-session-self-healing`，进程级 `smoke-late-ticket.mjs` 验证无需重启即可 enrollment。
- F2：`.trellis/tasks/09-23-a2a-message-wake`，Python A2A 单测验证标准配置、callback 状态和凭据脱敏。
- 父任务：`.trellis/tasks/09-23-a2a-wake-bridge-recovery`。

本决策不把任务 push config CRUD、streaming 或具体 IDE 的 host wake API 提前标记为已完成；它们仍须独立的接口研究和宿主实证。

## 2026-09-23 本机实测补充

在 `D:\Tsunagou-a2a-demo` 上完成了一次真实 loopback 验证：daemon 重启后
`daemon status` 与 `/api/v1/health` 均正常；一个独立的 `a2a-wake-worker`
profile 兑换得到新的 ready worker identity。随后由该 worker 向主 Agent 发送
A2A `message/send`，响应同时给出 `delivery=pushed`、`wake=requested`，临时
HTTP receiver 收到 `message.accepted` callback。callback token 只用于当前请求，
没有写入 durable payload。

同一实测中，目标 Codex 会话保持 idle，没有出现新的 Codex turn。这是预期的
宿主能力边界：Codex generic stdio MCP bridge 能提供工具和 pull inbox，但当前
没有经过验证的 daemon-to-Codex“启动新回合”接口。因此该结果确认 callback
投递成功，不能确认 host wake。

这里需要区分两个 Codex 层次。当前 Codex 应用向主会话提供的
`create_thread`/`send_message_to_thread` 属于应用控制面：它可以创建一个宿主
thread、向已有 thread 注入用户可见的后续消息，并触发新的 turn。这已经是可用
的宿主编排/唤醒能力，但它不是 Tsunagou daemon 通过 A2A callback 自动获得的
权限。OpenAI 的 Codex 平台文档也把 app-server 定义为可创建 threads、启动
turns、接收事件并管理审批的独立客户端协议，见
[Codex as a platform](https://developers.openai.com/blog/codex-as-a-platform)。

因此准确结论不是“Codex 不能唤醒”，而是“当前 Tsunagou generic stdio bridge
路径没有接入 Codex app-server，不能宣称 host wake”。后续可新增一个 Codex
app-server host adapter：维护 `agent_id -> thread_id` 的私有绑定，接收 durable
A2A push 后通过 app-server 启动对应 turn，并以可追踪事件证明
`host_wake=started`。这个 adapter 必须独立于 MCP bridge，不能让 daemon 直接
调用本会话的 Codex app 工具，也不能把 `thread_id` 当作 Tsunagou `agent_id`。

实测还发现一个接入运维条件：`agent connect` 为新 profile 注册的 MCP entry
不会替换已经运行的 Codex 进程内 MCP inventory。若新会话仍调用旧 entry，看到
的会是旧 profile 的 `agent_id`，这不是 daemon 合并身份，而是宿主配置缓存。
CLI 现在会优先使用 `CODEX_CLI_PATH`，并在 Windows 上回退发现
`%LOCALAPPDATA%\OpenAI\Codex\bin\*\codex.exe`，避免因 Agent shell 的 PATH
缺失而出现 `codex_not_found`。完成新 profile 的 `agent connect` 后，必须让
Codex host 重新加载 MCP；重启前应确保 daemon 以独立进程运行，避免旧终端
关闭时连带终止 daemon，造成 stale endpoint 和 `daemon_unreachable`。
