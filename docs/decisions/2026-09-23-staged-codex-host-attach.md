# 阶段 C：先 managed app-server，再显式 Desktop attach

## 决策

采用用户确认的阶段 C：

1. 阶段 A 先由 Tsunagou 管理 Codex app-server，完成并验证 R1–R7 所依赖的 host-neutral port、binding、私有凭据、A2A durable delivery、wake dispatcher、evidence、幂等、权限和重启恢复。
2. 阶段 B 再接入用户手动创建的既有 Codex 对话。B 只接受用户控制面明确提供的已 enrollment `agent_id`、已有 `thread_id`、公开本机 endpoint 和确认标记。
3. A、B 共用同一 `HostWakePort`、`WakeDispatcher`、私有 binding store 和 A2A 消息；B 不复制任务、黑板、权限或消息状态机。

## Transport 语义

Codex 官方 app-server 文档规定 Unix socket 使用标准 WebSocket Upgrade，JSON-RPC 作为 WebSocket text frame 传输。Windows 当前 Python 没有 `AF_UNIX` 时，B provider 启动 `codex app-server proxy --sock <path>`，在 proxy 的 stdin/stdout 上完成同一套握手和 frame；这不是把 socket 当 JSONL 管道。官方参考：[Codex App Server](https://learn.chatgpt.com/docs/app-server)。

一次 disposable 独立 app-server 实测已走通 `initialize → thread/start → thread/read → thread/resume → turn/start`；终态 turn 事件在 30 秒有界窗口内未观察到，故没有写成 `turn_completed`。随后用官方 `--listen unix://...` 在同一 Codex 状态启动公开 listener，真实读取并恢复了 `originator=Codex Desktop` 的既有 thread，并观察到一个无文件修改 probe 的 `turn/completed`。这证明的是显式公共 endpoint 的 Desktop-originated thread attach，不证明正在运行的 Desktop stdio 进程本身暴露该 endpoint。

## 当前 Desktop 结论

本机 Codex Desktop 主进程由 Desktop 以 stdio 启动 app-server，未探测到可供 Tsunagou 自动发现的稳定公开 socket；没有读取私有数据库、窗口标题、PID 或模型自报身份。因而“自动 discovery”保持 `unknown/unsupported`。用户若按官方命令显式启动本机 Unix listener 并提供既有 thread id，则 B 的 attach/wake 已有真实证据；用户不能提供 endpoint 时，继续使用 A 的 managed provider 或普通 durable inbox pull。

## 边界

- `host attach` 是 U 控制入口，要求 `--attach-confirmed`；Agent 不能替自己创建 binding。
- probe 只做 `initialize` 和只读 `thread/read`，不创建隐式 thread。
- wake 只做 `thread/resume` 和 `turn/start`；socket/thread 失效时保留 durable pull。
- 原始 endpoint、thread/session ID 只在 adapter-owned 私有 store；公开 ref、日志和 A2A payload 只含 digest/status/evidence。
- `ws://`、`wss://`、端口扫描和未记录 Desktop 私有 RPC 不属于首版 B。

实施细节和操作命令见 [Codex host wake](../implementation/codex-host-wake.md)、[CLI/HTTP 手册](../overview/cli-http-manual.md) 和 [Desktop attach evidence](../research/evidence/codex-desktop-attach-2026-09-23.json)。
