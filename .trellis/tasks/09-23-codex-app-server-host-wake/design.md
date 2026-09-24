# Codex app-server 宿主唤醒设计

## 1. 设计结论

本任务采用分阶段双路径：

- **阶段 A：managed app-server**。Tsunagou 为一个已经 enrollment 的 Agent 管理 app-server 连接，并在该连接内创建/恢复 Codex thread。阶段 A 的目标是把 R1–R7、基础设施和公开接口变成可重复验收的实现。
- **阶段 B：Desktop attach**。在阶段 A 的 host-neutral port、绑定模型和证据语义稳定后，增加已有 Codex Desktop 对话的发现和 attach。阶段 B 只能复用阶段 A 的接口，不能直接新增一套 A2A 唤醒逻辑。

阶段 A 是实现基线，阶段 B 是产品体验目标。阶段 B 的“用户显式提供本机 Unix listener 与既有 thread”路径已有真实证据；正在运行的 Desktop stdio 进程自动 discovery 仍保持 `unknown`/`unsupported`，不得因为显式路径通过就报告任意新对话均可自动唤醒。

## 2. 边界

### 本任务包含

- Codex app-server 的本地传输、JSON-RPC 请求/响应关联和事件订阅。
- 由 `agent_id` 到私有 host binding 的持久化与恢复。
- A2A durable commit 后的 host wake 调度。
- thread 恢复、turn 启动、活动 turn 冲突、断线重连和幂等。
- 五类宿主证据：`callback_received`、`thread_resumed`、`turn_started`、`turn_completed`、`agent_presented`。
- 阶段 A 的真实 Codex 版本 probe 和端到端验收。
- 阶段 B 的 endpoint discovery、Desktop thread attach 和能力降级报告。

### 本任务不包含

- 修改 A2A 消息事实、Task 状态机、Grant/Lease 语义或主 Agent 权限。
- 用 Codex 应用控制工具、Codex Desktop 私有 RPC 或 UI 自动化替代 app-server adapter。
- 把 `agent_id`、Codex thread ID、Codex session ID、A2A message ID 混为一个身份。
- 把 A 阶段的 managed thread 当成用户手动创建的 Desktop 对话。
- 让唤醒动作扩大 cwd、sandbox、approval、MCP、Git 或项目 scope。

## 3. 分层架构

```text
A2A message/send
        │ durable commit
        ▼
WakeDispatcher（Tsunagou domain-neutral port）
        │ HostWakeRequest
        ▼
CodexHostAdapter
   ├── ManagedAppServerProvider（阶段 A）
   └── DesktopAttachProvider（阶段 B）
        │ JSON-RPC app-server
        ▼
Codex app-server / Desktop app-server
        │ thread/*, turn/*, item/* events
        ▼
Codex Agent turn
        │ MCP context/inbox pull
        ▼
PresentationEvidenceRecorder
```

`WakeDispatcher` 只负责任务触发、去重、状态和证据编排；`CodexHostAdapter` 负责宿主协议；`ManagedAppServerProvider` 和 `DesktopAttachProvider` 负责连接方式。任何层都不能复制 Project、Task、Message 的领域真相。

## 4. Host-neutral port

内部接口先定义为稳定 Python port，避免把 Codex JSON-RPC 结构传播到 A2A 和业务层。建议接口如下：

```python
class HostWakePort(Protocol):
    async def probe(self, binding: HostBindingRef) -> HostCapabilityReport: ...
    async def ensure_thread(self, binding: HostBindingRef) -> ThreadHandle: ...
    async def wake(self, request: HostWakeRequest) -> WakeAttempt: ...
    async def inspect(self, binding: HostBindingRef) -> HostInspection: ...
    async def close(self, binding: HostBindingRef, reason: str) -> None: ...
```

`HostWakeRequest` 至少包含：`agent_id`、`message_id`、`project_id`、`wake_attempt_id`、`binding_revision`、`cwd_digest`、`scope_digest`、`policy_digest` 和 `prompt_kind`。它不包含秘密、原始消息正文、完整 transcript 或用户私有路径。

`prompt_kind` 固定为 `pull_coordination_inbox`。唤醒 turn 的最小提示只要求 Agent 调用 Tsunagou context/inbox 工具读取新消息；正文留在 durable message 中，避免 callback 重复注入和越权摘要。

## 5. App-server 协议层

阶段 A 和阶段 B 都必须经过同一个 `CodexAppServerClient`：

1. 建立本地传输连接。
2. 发送 `initialize`，等待响应后发送 `initialized`。
3. 通过 `thread/start` 或 `thread/resume` 得到 thread handle。
4. 通过 `turn/start` 发送最小恢复提示。
5. 关联 JSON-RPC response ID 与内部 `wake_attempt_id`。
6. 订阅 `turn/*`、`item/*` 及连接错误事件。
7. 收到终态后关闭或保持连接，依据 provider 的生命周期策略处理。

JSON-RPC client 必须具备：请求超时、单次重试上限、未知 method 记录、协议错误分类、连接代次和 response ID 去重。`turn/steer` 只在设计明确允许活动 turn 接收追加指令时启用；否则进入本地排队，不能并发启动第二个 turn。

## 6. 两阶段 Provider 行为

### 6.1 ManagedAppServerProvider（阶段 A）

- 从当前用户配置的 Codex 可执行入口启动或连接 app-server。
- 每个 host binding 维护独立进程/连接和 thread handle。
- 记录实际 Codex 版本、传输、可用 method 和 `thread/start`/`thread/resume`/`turn/start` 结果。
- 允许自动创建 thread；其 thread ID 只能存入私有 binding store。
- 进程退出后保留 binding，重启时通过 probe 和 resume 恢复；不能静默创建第二个 Agent。

### 6.2 DesktopAttachProvider（阶段 B）

- 优先使用公开、稳定且可验证的本地发现接口；发现不到可自动发现的 endpoint 时返回 `unknown`，不扫描任意端口、不读取未定义内部数据库、不注入 UI。用户显式启动官方 Unix listener 后，使用已有 thread id 的 attach/wake 路径可报告真实 probe evidence。
- 通过已验证的 endpoint 建立 app-server handshake，再枚举或验证用户选择/注册的 thread。
- attach 前检查 `agent_id`、thread ID、Codex session ID、profile 和 scope digest 是否一致。
- 如果 Desktop 端没有可供 daemon 自动发现的稳定 attach 接口，则保留 A 的完整能力，并把自动 discovery 标记为 `unsupported`/`unknown`，给出可操作诊断；显式 endpoint 路径不能因此被伪装成自动发现。
- 不把“当前窗口存在某个对话”作为身份凭据；必须由 enrollment 产生或用户明确确认的绑定材料完成关联。

## 7. 私有身份与绑定

建议在用户级 Tsunagou state directory 保存 adapter-owned binding store；项目 SQLite 只保存不含秘密的引用和 digest。逻辑结构：

```json
{
  "binding_id": "hb_…",
  "agent_id": "…",
  "provider": "managed_app_server|desktop_attach",
  "adapter_profile": "codex-current",
  "thread_id_digest": "sha256:…",
  "session_id_digest": "sha256:…",
  "endpoint_kind": "stdio|unix_socket|websocket|unknown",
  "cwd_digest": "sha256:…",
  "scope_digest": "sha256:…",
  "policy_digest": "sha256:…",
  "status": "ready|degraded|stale|detached",
  "binding_revision": 3,
  "last_probe": {"version": "…", "capabilities": {"turn_start": "supported"}}
}
```

原始 thread ID、session ID、token 和 endpoint 私有路径留在受本机权限保护的 adapter store 或进程内存，不进入项目导出、A2A payload、模型上下文和普通日志。

## 8. A2A 到宿主唤醒流程

1. `message/send` 事务提交 durable message 和 delivery。
2. notifier 产生 `callback_received`，携带内部 delivery/message 引用。
3. `WakeDispatcher` 按 recipient `agent_id` 查询私有 binding 引用和当前 connection epoch。
4. dispatcher 为 `(agent_id, message_id, binding_revision)` 建立唯一 `wake_attempt`；重复 callback 只重放已有结果。
5. adapter 验证 provider capability、thread 状态、policy/scope digest 和活动 turn。
6. 有效 thread 执行 `thread/resume`，记录 `thread_resumed`；失效 thread 依据 provider 策略执行 `thread/start` 或返回 `host_binding_stale`。
7. 执行 `turn/start`，只发送 `pull_coordination_inbox` 提示，记录 `turn_started`。
8. 收到 turn 终态记录 `turn_completed`；Agent 实际调用 context/inbox 并呈现结果后记录 `agent_presented`。
9. 任一步失败，保留 durable message，设置可恢复状态并让 Agent 可通过 pull 恢复。失败响应不能伪造 `turn_started` 或 `agent_presented`。

## 9. 活动 turn、幂等和恢复

- 同一 Agent 同时只有一个默认 wake turn。
- 活动 turn 时，新的协作消息进入 durable inbox，并根据策略标记 `queued`；首版不默认使用 `turn/steer`。
- callback 重试、daemon 重启、app-server 重启和客户端重试使用稳定 `wake_attempt_id`；同一 attempt 的 RPC 重试复用 request ID。
- 连接代次变化会使旧请求失效；旧请求不能借用幂等缓存取得新授权。
- `thread/resume` 成功但 `turn/start` 超时必须记录中间证据，重试前先 probe thread 状态，避免重复 turn。
- 用户未确认的重大设计、任务完成、scope 变化和 Git 操作不会因为 wake 自动执行。

## 10. 证据与能力状态

能力状态分为 `supported`、`unsupported`、`unknown`、`degraded`。只有同一 provider 在真实 probe 和 E2E 中取得证据，才能报告 `supported`。

阶段 A 的最低证据链：

```text
callback_received
  -> thread_resumed | thread_started
  -> turn_started
  -> turn_completed
  -> agent_presented
```

`delivery=pushed` 只代表 HTTP callback 收到 2xx；`wake=requested` 只代表提交了宿主唤醒尝试；二者都不等于 `turn_started`。

阶段 B 的显式 attach 证据必须额外包含：用户提供的 endpoint、认证/握手成功、现有 thread 身份确认、Desktop-originated 对话与 `agent_id` 绑定确认。缺任何一项时，显式路径保持 `unknown`/`unsupported`；自动从 Desktop stdio 进程发现 endpoint 另行报告为 `unknown`。

## 11. 权限与用户边界

Host adapter 只能复用 enrollment 时确定的 cwd、项目 scope、sandbox/approval policy、MCP 配置和 Agent role。Full Access 只代表宿主自身能力，不代表 Tsunagou 授权扩大。唤醒提示不能要求 Agent接管主 Agent 任务、代替用户确认重大决策或操作未授权项目。

## 12. 风险与降级

| 风险 | 处理 |
|---|---|
| Desktop 没有可供自动发现的公开 attach endpoint | 自动 discovery=`unknown`/`unsupported`，保留 A，输出诊断，不使用私有 RPC；用户可显式启动官方 listener |
| Desktop endpoint 可连但 thread 不可枚举 | 要求一次用户确认/显式绑定；否则 B=`unknown` |
| 旧 Codex 版本缺 method | probe 记录缺失 method，阻止对应能力，不伪造兼容 |
| callback 到达但宿主离线 | durable pull 继续有效，wake attempt 可重试 |
| 活动 turn | 入队等待或显式 steer；首版默认不并发 |
| binding 与 scope digest 不一致 | 拒绝 wake，要求重新 enrollment/attach |

## 13. 验收分层

- **A0 协议探针**：initialize、thread lifecycle、turn lifecycle、事件和错误分类。
- **A1 基础设施**：binding store、dispatcher、evidence、幂等、重启恢复。
- **A2 A2A E2E**：独立 Agent 发送 message，目标 managed Agent 获得真实 `turn_started` 并 pull inbox。
- **B0 Desktop 探测**：发现、认证、版本和 endpoint 能力状态；当前自动 discovery 明确为 `unknown`，显式 listener 可探测。
- **B1 Desktop attach E2E**：手动创建对话并完成显式 binding，A2A 到达后该现有对话真实启动 turn；本轮已观察 `thread_resumed`/`turn_started`，终态依赖附着 thread 的 MCP/插件/审批环境。

B1 的显式路径已通过，但产品说明仍不得宣称“任意新建 Codex 对话可被 Tsunagou 自动唤醒”；自动 discovery 未通过时必须要求用户提供 listener 与 thread id。
