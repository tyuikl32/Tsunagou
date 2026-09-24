# Desktop attach 阶段 B 设计

## 1. 结论

阶段 B 不扫描 Codex Desktop，也不读取 ChatGPT/Codex 私有数据库。用户控制面显式提交一个本机 app-server Unix socket、已存在的 thread id 和 attach confirmation；Tsunagou 通过该 socket 的标准 WebSocket transport 接入，在 Windows Python 没有 `AF_UNIX` 时用 `codex app-server proxy --sock` 传递原始握手和 frame，再复用阶段 A 的 host-neutral port。

首版只实现 Unix socket。官方文档列出 Unix socket、WebSocket 和 stdio，但 WebSocket 仍是实验能力；正在运行的 Windows Desktop stdio 进程没有可供自动发现的稳定外部 endpoint 时，B 的自动 discovery 能力报告必须保持 `unknown`/`unsupported`。用户显式启动官方 Unix listener 后，已有 Desktop-originated thread 可以走本 B 路径。

## 2. 数据流

```text
用户控制 CLI/HTTP host attach
        │ endpoint + thread_id + explicit confirmation
        ▼
DesktopAttachProvider
        │ codex app-server proxy --sock <path>
        ▼
已有 Codex app-server / Desktop thread
        │ initialize -> thread/read -> thread/resume -> turn/start
        ▼
WakeDispatcher（与阶段 A 相同）
        │ A2A durable message / evidence / presentation
        ▼
Tsunagou inbox/context
```

`DesktopAttachProvider` 是协议适配器，不拥有 Project、Task、Message 或用户决定。它与 `ManagedCodexProvider` 共享一个 `PrivateBindingStore`，由 `HostWakeProviderRegistry` 按 binding.provider 路由。

## 3. Attach binding

用户输入字段：

- `agent_id`：已 enrollment 的 Agent；只能由 U 控制面指定。
- `endpoint`：`unix://<absolute-socket-path>`；不接受任意网络地址。
- `thread_id`：用户明确选择的既有 Codex thread id；只保存到私有 store。
- `attach_confirmed=true`：显式确认该 thread 属于这个 Agent。
- `cwd/scope_digest/policy_digest`：继续沿用阶段 A 的权限快照。

私有记录额外保存 `endpoint`、`thread_id`、`session_id`、`provider=desktop_attach`、`transport=unix_proxy`。公开 ref 只返回 digest、status、revision、capabilities 和 probe evidence。

## 4. Probe 与 wake

1. 对 Unix socket 完成标准 HTTP WebSocket Upgrade；能直接使用 `AF_UNIX` 的平台直接连接，Windows 通过 `codex app-server proxy --sock` 传递字节流。JSON-RPC 作为 WebSocket text frame 发送，不把 Unix socket 当作 JSONL 管道。
2. `initialize`/`initialized`，记录 serverInfo 和版本摘要。
3. 对指定 thread 调用 `thread/read`，`includeTurns=false`；成功才记录 thread confirmation。
4. A2A durable delivery 到达后，执行 `thread/resume` 和 `turn/start`，不执行 `thread/start`。
5. 复用阶段 A 的 `turn_started`、`turn_completed`、`agent_presented` evidence。
6. socket 不存在、认证失败、thread 不存在或 Desktop 不支持时，返回稳定错误并保留 durable pull。

## 5. 路由与安全

- Managed 和 Desktop binding 共用 `WakeDispatcher`，唯一键仍为 `(agent_id, message_id)`。
- U attach endpoint 不接受 Agent bearer；Agent 不能替自己创建 Desktop binding。
- Endpoint 必须是绝对本机 Unix socket；`ws://`/`wss://` 及非 loopback endpoint 首版拒绝为 `desktop_attach_transport_unsupported`。
- Probe 不创建 thread；不能因为指定 thread 不存在而静默切换到 `thread/start`。
- 原始 endpoint/thread/session 不进入 A2A payload、项目 SQLite、普通日志或模型 prompt。

## 6. 降级状态

| 情况 | 状态 | 行为 |
|---|---|---|
| 用户未提供 endpoint/thread | `unknown` | 不 attach，要求显式材料 |
| Unix socket 不存在 | `degraded` | durable pull 保留，诊断 socket unavailable |
| endpoint 是 ws/wss | `unsupported` | 不连接，不做端口扫描 |
| thread/read 找不到 thread | `unknown` | 不创建新 thread |
| binding revision/scope 不匹配 | `stale`/`failed` | 拒绝 wake，要求重新 attach |
| probe 成功但 Desktop turn 不可用 | `degraded` | 记录失败 evidence，保留 pull |

## 7. 外部事实

官方 [Codex App Server](https://learn.chatgpt.com/docs/app-server) 当前说明 `unix://` transport、`thread/read`、`thread/resume` 和 `turn/start`；同时标明 WebSocket/app-server 仍为实验能力。官方资料没有给出 Desktop 已打开对话的稳定 discovery API，因此 B1 需要用户显式提供 endpoint/thread；本轮证据见 `docs/research/evidence/codex-desktop-attach-2026-09-23.json`。
