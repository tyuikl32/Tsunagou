# Codex app-server 宿主唤醒实施计划

## 1. 实施顺序

严格按下列顺序推进，A 阶段全部通过后才开始 B 阶段：

1. 定义 host-neutral schema、错误码、capability/evidence 状态和私有 binding store。
2. 实现 app-server JSON-RPC client 和 managed provider，先完成真实版本 probe。
3. 实现 wake dispatcher、A2A callback 到 wake attempt 的事务边界和幂等。
4. 接入 Codex MCP/context/inbox，完成 A2 E2E 和故障恢复。
5. 固化命令、日志、诊断和人工验收文档。
6. 研究并实现 Desktop endpoint discovery，保持 B 未验证时的降级行为。
7. 实现显式 Desktop thread attach、binding confirm 和 B1 E2E。

## 2. 预计文件布局

```text
src/tsunagou/
  hostwake/
    __init__.py
    port.py                 # HostWakePort、请求/结果和状态类型
    models.py               # binding、attempt、evidence、capability DTO
    errors.py               # host_wake_* 错误码
    dispatcher.py           # callback -> wake attempt 编排
    repository.py           # 私有 binding/evidence/attempt 持久化端口
    providers/
      codex_app_server.py   # 通用 JSON-RPC app-server client
      managed.py             # A 阶段 provider
      desktop_attach.py     # B 阶段 provider
    discovery.py             # endpoint/version/capability probe
    redaction.py             # digest 和日志脱敏
  api/
    ...                      # 仅增加公开诊断/attach DTO，不复制领域 handler
packages/bridge-sdk/
  ...                        # 如需新增 host-neutral 命令类型，保持 schema-first
packages/bridge-server/
  ...                        # 仅在 host tool 需要时增加 stdio bridge 转发
tests/
  unit/hostwake/
  integration/hostwake/
  e2e/codex/
tools/dev/
  probe_codex_app_server.py
  smoke_codex_host_wake.ps1
docs/implementation/
  codex-host-wake.md
docs/acceptance/
  codex-host-wake-a-*.md
  codex-host-wake-b-*.md
```

实际落盘前先搜索现有 repository、dispatcher、schema 和日志工具，复用已有实现；不得为同一事实新增第二个 service 或第二套错误格式。

## 3. 数据与接口变更

### 3.1 Host binding

新增 adapter-owned binding store，至少提供：

- `create_binding(agent_id, provider, profile, policy_digest, scope_digest)`
- `get_binding(agent_id)`
- `rotate_binding_revision(binding_id)`
- `mark_binding_status(binding_id, status, reason)`
- `delete_binding(binding_id)`

公共项目只保存 `binding_ref`、provider、status、digest 和 revision；原始连接凭据和宿主会话标识不得由项目查询接口返回。

### 3.2 Wake attempt

新增可重放的 attempt 记录：

- `wake_attempt_id`
- `agent_id`
- `message_id`
- `binding_revision`
- `state`: `received|probing|resuming|starting|running|completed|queued|failed|unknown`
- `last_evidence_kind`
- `error_code`
- `created_at/updated_at`

唯一键为 `(agent_id, message_id, binding_revision)`；同键同输入返回原结果，改变 recipient、正文摘要或 binding revision 返回幂等冲突。

### 3.3 公开命令

在已有 CLI/API dispatcher 上增加最小诊断入口，具体命名在实现时按 command catalog 统一：

- `host probe --adapter codex --profile <profile>`
- `host binding show --agent <agent_id>`
- `host wake status --attempt <wake_attempt_id>`
- `host attach codex --conversation <conversation_id>`（仅 B 阶段，必须有真实发现和确认流程）

命令只返回脱敏状态和证据摘要。`host wake` 不提供绕过 A2A durable message 的任意 prompt 注入入口。

## 4. JSON-RPC client 实施细节

1. 建立 transport abstraction，先实现 Windows 本地 stdio；保留 WebSocket/Unix socket 的 capability 枚举，不在无证据时标记支持。
2. `initialize` 成功后缓存版本和 method capability，连接代次变化使所有旧 request 失效。
3. 每个请求使用内部 command/request correlation，不复用 A2A message ID 作为 JSON-RPC ID。
4. 将 response、notification、transport close、protocol error 统一转成 adapter event。
5. 为 `thread/start`、`thread/resume`、`turn/start` 编写 schema 校验和错误映射；未知字段和未知终态不能静默成功。
6. 处理 stdout/stderr 分流，日志只保留 method、RPC ID digest、状态和错误码，不保留 prompt、token 或 transcript。
7. 真实 probe 输出版本、transport、methods、thread state 和失败原因到脱敏 evidence fixture。

## 5. Wake dispatcher 实施细节

1. A2A durable commit 成功后触发 notifier callback；callback 失败不回滚 durable message。
2. 由 delivery 事件生成一次 `wake_attempt`，重复 callback 走幂等查询。
3. 调用 `HostWakePort.probe`，校验 binding revision、connection epoch、scope/policy digest。
4. 无活动 turn 时执行 resume/start + turn/start；活动 turn 默认 `queued`。
5. 监听终态并写 evidence；超时保留中间状态，下一次恢复前先 inspect。
6. daemon/app-server 重启后扫描 `starting/running/unknown` attempt，按 provider 可恢复规则重新 probe，不直接盲目重启 turn。

## 6. 阶段 A 验证清单

- 单元：RPC correlation、超时、断线、未知 method、错误映射、redaction。
- 单元：binding revision、scope/policy mismatch、重复 callback、并发 wake、活动 turn 排队。
- 集成：模拟 app-server JSONL 完成 initialize/thread/resume/turn/event 全流程。
- 真实 probe：在当前 Windows Codex 版本执行 app-server probe，保存版本和 capability evidence。
- 真实 E2E：worker 向目标 Agent `message/send`，观察 durable message、callback、`thread_resumed`、`turn_started`、Agent pull inbox、`agent_presented`。
- 故障：daemon 重启、app-server 重启、旧 epoch、重复 callback、turn timeout、目标离线。
- 权限：Full Access、cwd、scope、MCP 和 role digest 保持不变；worker 不能唤醒为 main。

## 7. 阶段 B 验证清单

- 发现：只使用公开/稳定的 Desktop app-server endpoint；否则结果为 `unknown/unsupported`。
- 认证：确认 endpoint 的本机身份和当前 Codex profile，不把 PID/cwd/窗口标题当身份。
- attach：现有 thread 显式绑定到一个已 enrollment `agent_id`，记录 binding revision。
- 重启：Codex Desktop 或 daemon 重启后 binding 可重新 probe；失效时不会创建隐式新 Agent。
- E2E：手动新建 Codex 对话，完成一次最小 attach，另一个 Agent 发送 A2A 消息，原对话真实收到新 turn 并 pull inbox。
- 回退：attach 失败时消息仍可 pull，诊断明确指出需要重新绑定或当前版本不支持。

## 8. 文档与验收产物

- `docs/implementation/codex-host-wake.md`：稳定接口、状态、错误和运行约束。
- `docs/acceptance/codex-host-wake-a-*.md`：阶段 A 的实际版本、命令、时间、退出码和证据摘要。
- `docs/acceptance/codex-host-wake-b-*.md`：阶段 B 的 Desktop discovery/attach 真实证据；未完成时记录为未支持，不写成成功。
- 更新 `docs/implementation/a2a-boundary.md`、`docs/implementation/adapter-codex.md` 和 CLI 命令目录，保持 delivery/presentation/host-wake 术语一致。
- 每次公共语义变更后运行 `python tools/docs/validate_docs.py`；代码变更后运行相关 Python、TypeScript 和真实 smoke。

## 9. 完成标准

阶段 A 完成必须同时满足：

1. R1–R7 每项有代码、自动测试和至少一条真实 probe/E2E 证据。
2. A2A durable message 与 host wake evidence 可按 `message_id`/`wake_attempt_id` 追踪。
3. 重复、断线、重启和权限边界测试通过。
4. 文档不把 callback 2xx 或 managed thread 描述成 Desktop attach。

阶段 B 完成必须额外满足：

1. 真实 Desktop endpoint discovery、认证和 thread attach 证据。
2. 手动新建对话、显式绑定、A2A 唤醒、inbox pull 的端到端记录。
3. Desktop 不支持时，版本 probe 和用户诊断仍然正确降级。
