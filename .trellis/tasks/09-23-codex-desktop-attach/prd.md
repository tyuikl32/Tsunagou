# 已有 Codex Desktop 对话发现与 attach

## Goal

在 A 阶段完成后，实现阶段 B 的公开 endpoint discovery、认证、现有 thread 显式绑定和 Desktop 唤醒；没有稳定接口时保持 unknown/unsupported。

## Requirements

- B1：只接受用户控制面明确提供的 attach 材料；首版材料为公开 app-server Unix socket endpoint、既有 thread id、已 enrollment 的 `agent_id` 和用户确认标记。不得从窗口标题、PID、cwd、私有数据库或模型自报身份推断绑定。
- B2：attach 复用阶段 A 的 `HostWakePort`、`WakeDispatcher`、私有 binding store、A2A durable message 和五类 evidence；不得新增第二套消息或唤醒状态机。
- B3：首版只实现本机 Unix socket 上的标准 WebSocket Upgrade；Windows Python 不提供 `AF_UNIX` 时，通过 `codex app-server proxy --sock <path>` 传递握手和 WebSocket frame。`ws://`、`wss://`、自动端口扫描和 Desktop 私有控制面保持 `unknown`/`unsupported`。
- B4：attach probe 必须完成 app-server `initialize` 和指定 thread 的只读 `thread/read` 确认；失败时返回稳定诊断，不能创建隐式新 thread 或新 Agent。
- B5：A2A 消息到达后，已确认的 Desktop thread 才能走 `thread/resume`、`turn/start`；cwd、scope、approval、sandbox、MCP bridge 和 Agent role 只能沿用绑定材料。
- B6：原始 endpoint、thread/session id 和本地认证材料只写 adapter-owned 私有 store；公开 binding、A2A payload、日志和模型提示只暴露 digest/status。
- B7：attach 失败、Desktop 退出、daemon 重启、旧 binding revision 或 endpoint 不可用时，保留 durable pull，并返回 `unknown`/`unsupported`/`degraded` 诊断。

## Acceptance Criteria

- [x] `host attach` 和等价 HTTP U 入口能够登记显式 Desktop binding，并返回脱敏 binding ref。
- [x] Unix socket app-server 的 probe 能证明 initialize、thread/read 和 thread identity；无 endpoint 时不扫描、不猜测。
- [x] 统一 dispatcher 能对 attach binding 产生 `thread_resumed → turn_started`；真实 A2A probe 已验证这两类 evidence，presentation/terminal 仍取决于附着 thread 的 MCP、插件和审批环境。
- [x] attach binding 不会在 probe/wake 中创建第二个 thread；thread 不存在时保持失败和 durable pull。
- [x] A 阶段回归、权限边界、私有状态隔离、旧 revision、重复消息和 daemon 重启测试保持通过。
- [x] 当前 Windows Desktop 主进程若没有公开 attach endpoint，实测保持 stdio-only；用户启动官方 Unix listener 后，Desktop-originated thread 的显式 attach/wake 已有真实证据，文档不宣称无需 endpoint 的自动发现。

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Official protocol reference: https://learn.chatgpt.com/docs/app-server
- The current official documentation describes `unix://` and `codex app-server proxy`; it does not establish a stable Desktop conversation discovery API. B therefore starts with explicit endpoint/thread attach and truthful downgrade.

## Dependencies

- 强依赖 `codex-wake-e2e-recovery` 阶段 A 验收通过。
- 真实 Desktop E2E 依赖官方/稳定的 Codex Desktop app-server attach endpoint；没有该接口时，交付范围是显式 attach、transport/provider 验证和 truthful downgrade，不宣称任意 Desktop 对话可自动唤醒。
