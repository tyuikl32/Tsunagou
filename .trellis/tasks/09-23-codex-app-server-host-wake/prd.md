# Codex app-server 宿主唤醒

## Goal

通过 Codex app-server 将 Tsunagou A2A push 转化为目标 Agent 的真实 Codex turn，并建立可验收的身份、权限和唤醒证据链。

## Background and confirmed facts

- Tsunagou 当前 A2A `message/send` 已能将消息持久化到 daemon，并在 durable commit 后发送标准 `taskPushNotificationConfig` HTTP callback；`wake=requested` 目前只表示 callback 请求。
- generic stdio MCP bridge 能让 Agent 调用 Tsunagou typed tools，但不能从 daemon 反向启动 Codex 对话。
- 本机 Codex app-server 官方协议是双向 JSON-RPC；连接后必须先 `initialize`/`initialized`，然后可使用 `thread/start`、`thread/resume`、`turn/start`，并读取 `turn/*`、`item/*` 等事件。官方文档还说明 app-server 支持 stdio JSONL、实验性 WebSocket 和本机 Unix socket 传输。
- Codex 应用控制工具可以创建 thread、发送后续消息并触发 turn，但这些工具属于当前 Codex 应用控制面，daemon 不能直接调用它们；Tsunagou 必须使用正式 app-server adapter。
- `agent_id`、Codex `thread_id`、Codex `sessionId` 和 A2A `messageId` 是不同标识，不能互相替代。一个 Agent 的私有映射必须持久化在本机私有 adapter 状态中，不能写入项目公共事实或 prompt。
- 当前真实测试已经证明 A2A callback 成功但 Codex 对话保持 idle；这正是本任务要补齐的行为缺口。

## User value

当一个 Agent 向另一个 Agent 发送需要及时处理的协作消息时，目标 Agent 不应依赖用户手动打开对话。daemon 保留持久消息，Codex adapter 在确认宿主可用后启动目标 Agent 的下一轮；目标 Agent 仍必须通过 Tsunagou inbox/context 工具读取消息并遵守主从、scope 和用户确认边界。

## Requirements

- R1：建立 Codex app-server adapter 的 host-neutral 端口，负责 app-server 进程/连接生命周期、JSON-RPC request/response correlation、事件订阅、超时、断线和重连；不复制 Tsunagou 任务状态机。
- R2：维护 `agent_id -> private host binding`，至少包含 adapter profile、Codex thread id、session id、连接状态和脱敏证据摘要；禁止把 token、原始 thread transcript 或私有路径写入项目 SQLite、A2A message payload 或模型上下文。
- R3：在 A2A durable commit 后由宿主 adapter 接收通知，只在目标 Agent 映射、app-server 连接和 thread 状态均有效时执行 `thread/resume`（必要时 `thread/start`）及 `turn/start`；turn 输入只能是最小恢复提示，要求 Agent 自己读取 context/inbox，不把消息正文直接注入模型。
- R4：区分并持久记录 `callback_received`、`thread_resumed`、`turn_started`、`turn_completed`、`agent_presented` 五类证据；任何一步失败都保留 pull 恢复路径，不把 callback 2xx 或 RPC acknowledgement 单独报告为 host wake 成功。
- R5：turn 启动必须使用该 Agent 已批准的 cwd、权限/沙箱 profile 和 MCP 配置；adapter 不能因为 wake 请求扩大 Full Access、项目 scope、Git 权限或主 Agent 权限。
- R6：重复 A2A message、重复 callback、断线重试和 app-server 重启必须幂等；同一 message 不得启动多个并发 turn，活动 turn 必须走显式 `turn/steer` 或排队策略。
- R7：为 Codex 版本/协议能力提供真实 probe，至少记录 app-server 版本、传输方式、可用 method、thread 状态和失败原因；未知能力保持 `unknown`，不能因为 JSON-RPC 连通就声明正式支持。

## Decision: staged dual path (C)

本任务采用 C，但不是同时把 A、B 视为同等成熟的正式实现，而是分两个阶段交付：

1. **A 阶段**：Tsunagou 管理 app-server 进程，先把 R1–R7、host-neutral port、私有身份绑定、证据链、幂等、权限边界和真实故障恢复全部建立并验证。A 阶段是基础设施和接口的验收基线。
2. **B 阶段**：在不改变上述 port、数据模型和 A2A 语义的前提下，增加对用户已经打开的 Codex Desktop app-server/thread 的发现、认证、绑定和唤醒。B 阶段优先保留用户手动创建的现有对话。

A 阶段完成后，B 阶段才可以开始；B 不能通过绕过 host-neutral port、写入公共项目事实或调用未记录的 Desktop 私有 RPC 来“快速接通”。

## Integration modes

### A. Tsunagou-managed app-server（第一阶段基础设施验收）

Tsunagou 为每个已接入 Agent 启动并维护一个 `codex app-server` 进程，使用 `thread/start`/`thread/resume` 建立私有 thread，再用 `turn/start` 响应 A2A push。优点是协议、权限、生命周期和nen测试边界可控；代价是它可能是 Tsunagou 管理的 Codex thread，不一定是用户当前 Desktop tab 中已经打开的同一个对话。

### B. Attach 到已有 Codex Desktop app-server（第二阶段目标）

适配器发现并连接用户已经运行的 Codex Desktop app-server 控制 socket，把现有 thread 作为目标。优点是保持用户当前对话和界面；代价是连接发现、认证、thread 映射和版本兼容必须有公开且稳定的接口，不能依赖当前 Codex 应用内部工具或未记录的 socket。

### C. 分阶段双路径

先完成 A 的完整闭环和 R1–R7 验收，再把 B 作为同一 port 的第二个 host binding provider。B 的能力状态必须单独记录；B 未取得真实连接、认证、thread resume 和 turn start 证据前，只能报告 `unknown` 或 `unsupported`，不能继承 A 的 `supported` 结论。

## Preliminary acceptance criteria

- [x] 在本机 demo 项目中，独立 worker 通过 A2A `message/send` 产生 durable message，managed adapter 能将 callback 映射到唯一 Agent/thread，并观察到真实 `turn/started` 事件；Desktop attach 的真实证据记录为 `thread_resumed`/`turn_started`。
- [x] 被唤醒的 managed Codex Agent 在新 turn 中调用 `context__project_read` 和 inbox 工具读取消息并呈现结果；测试记录的身份和 turn 仅保留脱敏摘要，不记录秘密或完整 transcript。
- [x] callback 重试、daemon 重启、app-server 重启和重复 message 不造成重复 Agent、重复 durable message 或并发重复 turn；未决状态会进入 `unknown` 并保留 pull 恢复路径。
- [x] 没有合法 host binding、app-server 不可用、活动 turn、权限不匹配或用户决定阻塞时，系统返回可恢复状态，消息仍可 pull，且不伪造 host wake 成功。
- [x] adapter 使用的 cwd、sandbox/approval policy、MCP bridge 和项目 scope 与 enrollment 记录一致；Full Access 不改变 Tsunagou authorization。
- [x] 在实际 Codex `0.155.0-alpha.16` 上完成从 enrollment 到 managed A2A wake 的端到端实测；probe 对未提供 method catalogue 的能力保持 `unknown`。阶段 B 另已在用户显式启动的本地 Unix listener 上读取/恢复 Desktop-originated thread，并记录自动 discovery 仍为 `unknown`。

## Out of scope for this task

- 不修改 A2A 核心消息事实、任务状态机或权限模型来绕过 host adapter。
- 不把 Codex 应用控制工具、Codex Desktop 私有内部 RPC 或人工 `send_message_to_thread` 当作产品运行时接口。
- 不为其他宿主同时实现 wake；其他 adapter 只保留 host-neutral port 和能力 unknown 记录。
- 不自动替主 Agent 完成重大设计、scope 扩大、Git 写操作或项目完成确认。

## Decision record

- 用户选择：**C，先 A 后 B**。
- A 的职责：确定并验证 R1–R7、基础设施、接口、证据和故障语义。
- B 的职责：接入用户手动创建的既有 Codex Desktop 对话，并复用 A 阶段已验证的 port 和数据模型。
- A 与 B 不能共用未经验证的身份映射；每个阶段分别记录 capability probe 和端到端证据。

## Notes

- 相关规范和证据：[A2A 边界实现](../../../docs/implementation/a2a-boundary.md)、[Codex 适配器](../../../docs/implementation/adapter-codex.md)、[本轮 push/recovery 决策](../../../docs/decisions/2026-09-23-a2a-push-and-bridge-recovery.md)。
- 官方参考：[Codex App Server](https://learn.chatgpt.com/docs/app-server)、[Codex as a platform](https://developers.openai.com/blog/codex-as-a-platform)。
- 在 Open Decision 解决前，不创建实现子任务、不运行 `task.py start`、不修改产品代码。
