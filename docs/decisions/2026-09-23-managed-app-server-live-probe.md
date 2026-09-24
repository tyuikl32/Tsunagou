# Managed Codex app-server 首轮实测

## 结论

当前 Windows Codex `0.155.0-alpha.16` 可以由 Tsunagou 以 managed app-server 方式启动，并完成真实 JSON-RPC handshake、thread lifecycle 和 turn lifecycle。阶段 A 的 host-neutral port 不是空壳，已经能把 A2A durable message 映射到一个真实 Codex turn。

完整 A2A 协作闭环已经在 disposable managed E2E 中通过：后台 watcher 取得 `turn_completed`，worker 通过私有 bridge 调用了 typed context/inbox 工具并记录 `agent_presented`。随后真实 daemon 重启又验证了未决 attempt 标记为 `unknown`、durable pull 保留，以及同语义 `messageId` 重试后新 attempt 完成；另一轮真实 loopback callback 收到 `message.accepted` 并记录 `callback_received`。旧 epoch 已通过拒绝负例。阶段 B 的显式 Desktop attach provider 已补齐，但当前 Desktop 没有公开稳定 endpoint，仍不能声称任意 Desktop 对话可自动唤醒。

## 实测事实

- `initialize` 成功，但响应没有 method catalogue；不能从该响应推断 `turn/start` 支持。
- `thread/start` 使用当前版本接受的 legacy sandbox 值 `workspace-write`；`workspaceWrite` 会被拒绝为 unknown variant。
- `thread/start` 返回 thread/session 元数据；原始 ID 只写入 adapter 私有 store，CLI 只显示 digest。
- `thread/resume` 在同一 binding 的 provider 重启后可以恢复既有 thread。
- 真实只读 turn probe 返回 `turn/completed`，观察到 `turn/started`、item lifecycle、agent message delta 和 `turn/completed`。
- 真实 A2A 路径产生一条 durable message，host wake response 返回 `running`，证据至少包含 `thread_started` 和 `turn_started`；durable inbox 仍然可 pull。
- 新线程在首轮 turn 持久化前立即调用 `thread/resume` 会返回 `-32600`；provider 现在将这类未物化线程恢复为新的 `thread/start`，首轮 turn 完成后再走稳定 resume。
- daemon 重启会将持久化的 `running` attempt 标记为 `unknown`，错误码为 `host_wake_process_restarted`；使用完全相同的 A2A 消息语义重投后，provider 通过 `thread/resume` 建立新 attempt，并观察到 `agent_presented` 和 `turn_completed`。若正文与原消息不一致，durable message 层按设计返回 `idempotency_conflict`。

## 新的实现约束

1. capability probe 必须把“initialize 可连通”“thread lifecycle 可用”和“turn lifecycle 已实测”分开记录；method catalogue 缺失时使用 `unknown`。
2. managed binding 必须保留用户选择的 cwd、scope、approval 和 sandbox 语义；不能把 `workspace-write` 自动升级为 Full Access。
3. wake callback 采用短有界等待，返回 `running` 时继续保留 durable pull；不能让 A2A HTTP 请求无限等待模型回合。
4. 要完成 `agent_presented`，managed app-server 必须使用与该 Agent 对应的 Tsunagou MCP/bridge 配置。仅凭全局 Codex 配置启动 app-server 可能加载旧项目 bridge，造成 turn 阻塞或看不到目标 inbox。
5. provider 和 CLI 现在接受 enrollment 生成的私有 bridge JSON，并以进程级 `mcp_servers.tsunagou.*` 覆盖装入；不会修改用户全局 Codex 配置。阶段 A 的 managed 路径已经完成验收；阶段 B 只允许显式 endpoint/thread attach，并在 Desktop 没有公开 endpoint 时保持 `unknown/unsupported`。当前 loopback callback 证据不能被描述为远程网络安全或 Desktop attach 证据。

证据文件：[codex-app-server-managed-2026-09-23.json](../research/evidence/codex-app-server-managed-2026-09-23.json)。官方协议参考：[Codex App Server](https://learn.chatgpt.com/docs/app-server)。
