# 原生唤醒补测：配置遗漏与 Desktop writer 冲突

时间：2026-09-28 06:09–06:17 UTC。范围：复用本轮已入会的两个 Worker 身份和现有会话，不创建替代 Agent，不修改业务代码，不删除或绕过宿主锁。

## 结论

原生唤醒仍未通过，但现在有实际调用与明确错误证据。初始测试的 daemon 是 `host_wake=disabled`，且没有 `host-bindings.json`；之前的 coordination waking/retry/blocked 不能证明调用过 Codex provider。`bindings.json` 是另一份存储，不能当作宿主绑定表。

补测启用了 managed wake 并通过 `desktop_attach` 绑定现有 WebUI、HTTP 会话。公开 listener 可以 `thread/read` 两个 thread；真实 A2A 消息到达后，HTTP Worker 的 `thread/resume` 被 Codex 以 RPC `-32600` 拒绝：`already has an active writer`。会话在 Desktop 中 idle 不表示其 writer 已释放。不能通过另起 listener 宣称已连接到正在持有会话的 Desktop 宿主。

公开接口依据：[Codex App Server](https://learn.chatgpt.com/docs/app-server) 的 Unix socket transport、initialize、thread/read、thread/resume 和 turn/start。公开文档证明这些接口存在；本机调用结果决定本轮是否成功，不能相互替代。

## 可追溯证据

| 阶段 | 证据 |
|---|---|
| listener 初次启动 | 进程终止，报 `socket directory is not private to the current user`；仅有 PID 不等于服务就绪 |
| listener 恢复 | 创建新的当前用户专用 socket 子目录，保留既有目录 ACL；PID 87044 实际运行 |
| 正确绑定 | [native-wake-binding-record.json](native-wake-binding-record.json)：两个现有会话 thread/read 成功；method catalogue 不足时保持 unknown |
| 真正 A2A 调用 | [native-wake-http-record.json](native-wake-http-record.json)：message `3f45ba48-0c79-47a5-b06a-1a43e1831aab` 已持久化；原生 wake failed |
| 底层原因 | [native-wake-diagnosis.json](native-wake-diagnosis.json)：公开 RPC 报已有 active writer，adapter 错误为 `desktop_thread_unavailable` |
| 失败恢复 | 同一个 HTTP Worker 于 06:17:18 UTC fetch/present/ACK，触发源是显式 Codex follow-up；消息未丢失 |
| 状态区分 | 补做 ACK 后 wake attempt 仍 failed，没有因 presentation 被改为 completed |

当前 diagnostic query 有 `wake_requested` 和后来 fallback 的 `agent_presented`，但缺少这个 provider 错误对应的 `wake_failed`。因此 presentation 不能证明原生唤醒成功，必须结合 wake-status 和实际启动来源。该诊断缺口已独立留档。

## 当前服务与查询

业务服务仍为 `http://127.0.0.1:5137/`。补测后的 daemon PID 为 70156、端口仍为 56876、`host_wake=managed`。本轮专用 listener PID 为 87044，绑定、socket、日志只保存在目标项目的 `.tsunagou/local`；原始日志没有复制进公开报告。

```powershell
$env:TSUNAGOU_PROJECT_ROOT = 'D:\ALL.NET\SegaImageManageTool'
$env:TSUNAGOU_STATE_DIR = 'D:\ALL.NET\SegaImageManageTool\.tsunagou\local'
uv run --project D:\Tsunagou python -m tsunagou host wake-status wake:369a92b4-659b-423a-b2e3-b1a5e46f70a6
uv run --project D:\Tsunagou python -m tsunagou project diagnostics 839bdb05-c7db-474c-9517-f0e837eb5096 --json
```

后续需要宿主提供对当前持有 writer 的进程的受支持控制连接，或明确的会话释放/交接流程。当前不通过删锁、替换身份、另开替代 Worker 或强制结束 Desktop 来把失败改成通过。业务交付确认仍与此平台缺口分开处理。
