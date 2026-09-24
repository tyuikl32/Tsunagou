# Codex host wake 阶段 A 与阶段 B

当前实现已经建立阶段 A 的 managed app-server 代码路径，并已用真实 Windows Codex 版本完成 disposable managed A2A 端到端验收。阶段 B 现在提供了显式 Desktop attach 的 provider、CLI/HTTP 入口、Unix socket proxy、只读 thread probe 和复用 A2A 唤醒状态机的代码路径。当前 Windows Codex Desktop 主进程仍以 stdio 启动，但官方公开的 `codex app-server --listen unix://...` 可以在同一 Codex 状态上暴露本机 endpoint；实测该 endpoint 能读取、恢复并驱动一个 `originator=Codex Desktop` 的既有 thread。自动从 Desktop 主进程发现 endpoint 仍不支持，不能宣称任意手动新建对话无需显式 endpoint 就能自动唤醒。`delivery=pushed` 仍只表示 A2A callback 收到 2xx；只有 `thread_started`/`thread_resumed`、`turn_started` 和后续 Agent presentation evidence 才能证明宿主行为。

## 运行边界

设置 `TSUNAGOU_HOST_WAKE=managed` 后，真实 daemon 会在 `TSUNAGOU_STATE_DIR` 下初始化 adapter-owned 的 `host-bindings.json` 和 `host-wake-attempts.json`。这两个文件不属于项目公共事实；原始 Codex thread/session ID 只能在 binding store 中保存，A2A payload、blackboard、普通查询和模型提示不会包含它们。

当前 managed provider 需要一个已经建立的私有 binding。binding 包含 Agent、profile、cwd/scope/policy digest 和 adapter 状态；原始 `thread_id` 在 provider 第一次 `thread/start` 成功后才写入私有 store。真实唤醒还应绑定 enrollment 生成的私有 bridge JSON；provider 将其转换为 app-server 的进程级 `mcp_servers.tsunagou.*` 配置覆盖，不读取或修改用户全局 `config.toml`。没有 binding 时，A2A durable message 仍然成功，但 host wake 返回 `host_binding_not_found`，目标 Agent 仍可通过 inbox pull 恢复。

## Host-neutral 接口

`src/tsunagou/hostwake/port.py` 定义 `HostWakePort`、`HostBindingRef`、`HostWakeRequest`、`HostCapabilityReport`、`HostEvidence` 和 `WakeAttempt`。managed provider 与 Desktop attach provider 实现同一组 `probe`、`ensure_thread`、`wake`、`poll`、`inspect`、`close` 操作，registry 只负责按 binding provider 路由，不复制消息或状态机。

`src/tsunagou/hostwake/dispatcher.py` 以 `(agent_id, message_id)` 做本地 wake 幂等键。重复 callback 只返回已有 attempt，不会第二次调用 `turn/start`。失败不会回滚已经提交的 durable message。

daemon 重启时，持久化但仍为 `running` 的 attempt 会被标记为 `unknown`，并保留原消息的 durable pull 路径；下一次同一消息重新到达时，只有旧 managed provider 已不存在的这个恢复标记才允许建立一次新的 attempt。真实 disposable E2E 已验证：daemon 停止后 attempt 变为 `unknown`（`host_wake_process_restarted`），使用完全相同消息语义重试后建立新 attempt 并完成；若只改变正文而复用 `messageId`，A2A durable 层拒绝为 `idempotency_conflict`。watcher 发现 app-server 进程或活动 turn 不再可观察时也写入 `unknown`，不会把未证实的终态伪造为 completed。

## Managed Codex 协议路径

`ManagedCodexProvider` 使用本地 `codex app-server --stdio`，完成：

1. `initialize`/`initialized` 握手；
2. `thread/start` 或 `thread/resume`；新建线程在首轮 turn 持久化前不能立即 resume，遇到当前版本的 `-32600/-32602` 时会重新 start 并替换私有 binding；
3. `turn/start`，输入固定为“读取 Tsunagou coordination context 和 inbox 后继续”；
4. 读取 `turn/*` 通知并记录脱敏 evidence digest。

请求/响应按 JSON-RPC ID 关联；Windows 匿名管道由独立 reader thread 消费。超时、断线、未知 method 和非对象结果均返回稳定 adapter 错误。provider 不创建 Task、不修改 Grant/Lease、不扩大 cwd、scope、sandbox、approval 或 Full Access。

官方协议示例见 [Codex App Server](https://learn.chatgpt.com/docs/app-server)。其中 `thread/start`、`thread/resume` 和 `turn/start` 的真实字段必须由当前版本 probe 证实；没有 method catalogue 的版本只报告 `unknown`，不能因为进程能启动就报告 `supported`。

## Desktop attach 协议路径（阶段 B）

Desktop attach 只接受用户控制面显式提供的三项材料：已经 enrollment 且处于 `active` 状态的 `agent_id`、现有 Codex thread id、以及本机 app-server 的 `unix://<absolute-socket-path>` endpoint。`host attach` 会要求 `--attach-confirmed`；没有 active Agent、确认标记、thread id 或绝对本地 socket 时，daemon 不登记 binding。系统不会通过窗口标题、PID、cwd、私有数据库、端口扫描或模型自报身份猜测对话。

attach provider 按官方协议对 Unix socket 完成 WebSocket Upgrade，并以 WebSocket text frame 发送 JSON-RPC。能直接使用 `AF_UNIX` 的平台直接连接；当前 Windows Python 通过 `codex app-server proxy --sock <path>` 传递握手和 frame，而不是把 socket 当作 JSONL 管道。建立 transport 后按以下顺序工作：

1. `initialize`/`initialized` 建立代理连接；
2. `thread/read` 且 `includeTurns=false` 确认返回的 thread id 与用户指定的 id 完全一致；
3. A2A durable delivery 到达后只调用 `thread/resume` 和 `turn/start`，绝不回退到 `thread/start`；
4. 复用 A 阶段的 `WakeDispatcher`、幂等键、`thread_resumed`/`turn_started`/`turn_completed`/`agent_presented` evidence 和 durable pull。

原始 endpoint、thread/session id 和本地 bridge 材料仍只进入 adapter-owned 私有 `host-bindings.json`。公开 binding、A2A payload、日志和模型提示只包含 digest、状态和 capability。Desktop socket 不存在、thread 不可读、认证/代理失败或 daemon 重启时，binding 返回 `degraded`/`unknown`，消息仍保留在 inbox，用户或主 Agent 可以重新 attach。

当前实现的首版边界是 `unix://`。官方资料列出 Unix socket、WebSocket 和 stdio，但没有给出从运行中的 Desktop stdio 进程自动发现 endpoint 的稳定 API；用户可以先按官方命令显式启动一个本机 listener，再把既有 thread id 交给 `host attach`：

```powershell
$socket = Join-Path $env:USERPROFILE '.codex\app-server-control\tsunagou-public.sock'
codex app-server --listen "unix://$socket"
```

listener 保持运行期间，另一个终端执行 `host attach --endpoint "unix://$socket" --thread-id <existing-thread-id> --attach-confirmed`。`ws://`、`wss://` 和任意网络地址首版均报告 `desktop_attach_transport_unsupported`。相关实测结果和脱敏证据见 [Desktop attach probe](../research/evidence/codex-desktop-attach-2026-09-23.json)。

## A2A 连接点

`A2AGateway` 接受可选 `WakeDispatcher`。durable `message/send` 完成后调用 `on_delivery`，响应的 `result.message.metadata.tsunagou.host_wake` 会包含脱敏的 attempt 状态；配置了 A2A callback 时，attempt evidence 还会记录 `callback_received`，随后记录 `thread_started`/`thread_resumed`、`turn_started`，后台 watcher 观察到终止事件后补 `turn_completed`。Agent 调用 `inbox.presented` 后再补 `agent_presented`。没有配置 provider 时为 `not_configured`。host wake 是增强路径，不能覆盖 durable delivery、presentation 或用户确认边界。

## 当前验收状态

- 已通过：binding 私有字段隔离、managed provider 模拟 probe/wake、turn evidence、重复 delivery 幂等、A2A 回归测试。
- 已补充：当前 Windows Codex 版本的 initialize/thread/turn probe，以及 disposable managed E2E 的真实 `message/send -> durable message -> managed thread -> turn_started -> context__project_read -> inbox__claim/fetch/presented -> turn_completed` 链路。HTTP 请求在有界等待内返回 `running`，私有 watcher 随后将终态 evidence 写回同一 attempt。
- 已补充：daemon 重启恢复证据；重启会把未决 attempt 标记为 `unknown`，同语义消息可以建立新 attempt 并完成，改变同一 `messageId` 的消息正文会被幂等保护拒绝。
- 已补充：本机 loopback `taskPushNotificationConfig` 的真实 HTTP callback 证据；receiver 收到 `message.accepted`，回调体摘要不含凭据，并在同一 attempt 上记录 `callback_received`。
- 阶段 A（managed app-server）R1–R7 已达到验收条件；Codex method catalogue 仍由当前版本报告为 `unknown`，这是能力探针结果而不是被伪造的支持声明。长 turn 的后台 watcher、私有 bridge 配置路径、旧 epoch 拒绝和 presentation/evidence 竞态已有单元与 disposable E2E 验证。
- 阶段 B 的显式 attach provider、CLI/HTTP 登记、thread/read probe、无隐式新 thread 约束和共享 dispatcher 已实现并有自动测试；真实公开 endpoint 已读取并恢复 Desktop-originated thread，且 Tsunagou A2A 已观察到 `thread_resumed`/`turn_started`。运行中的 Desktop 主进程自动 discovery 仍是 `unknown`；附着 thread 的终态和 presentation 继续依赖它自己的 MCP、插件和审批环境，不能从 turn_started 推导完成。
- 后续若 Codex Desktop 提供稳定的用户可访问 Unix socket 或等价公开 transport，只需把该 endpoint 和既有 thread id 交给 `host attach`，再运行 probe 和最小 A2A wake 验收；不得把 managed A 的 stdio 证据复制为 Desktop 支持证据。
