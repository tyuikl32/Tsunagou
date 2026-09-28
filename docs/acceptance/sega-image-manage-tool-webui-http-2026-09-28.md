# SegaImageManageTool 实际协作验收单

版本：2026-09-28 · 项目：`D:\ALL.Net\SegaImageManageTool` · Tsunagou 源码：`D:\Tsunagou`

这是一份面向真实本机项目的验收单。它用于验证 Tsunagou 的安装、项目级约束、三 Agent 协作、A2A 传输、任务边界、资源冲突、持久化查询和因果追责，同时交付一个可运行的 Web UI + HTTP 后端。Tsunagou 源码保持在 `D:\Tsunagou`，不会复制到业务项目；业务项目只保存非秘密集成入口和 `.tsunagou` 持久化状态。

## 当前实测结果

截至 `2026-09-28T05:24:28.208Z`，WebUI 与 HTTP 两个 pull-first task 均已由各自独立 worker 提交，并由主 Agent `task.review.accept`；持久事件序号分别为 374 和 375。独立复验结果为：`dotnet build` exit 0、WebUI Node 测试 5/5 通过、HTTP acceptance exit 0。实际后端现运行在 `http://127.0.0.1:5137/`，真实浏览器已显示在线状态，并将 33 B fixture 经 multipart 送达后端，得到带 request ID 的 `file_too_small` 结构化错误。

后续复验截至 `2026-09-28T05:58:58.994Z`：真实后端与浏览器已成功解析无游戏数据的合成有效 BTID，返回 `TEST / 1.2.3 / headerCrcValid=true`。实际 `/api/v1/a2a` JSON-RPC 的发送、重复去重、任务查询和 Worker 越权拒绝通过；两个 Worker 各自 pull/present/ACK，并回复 main，main 也已 ACK。七项 CLI 查询在指定正确项目环境后全部成功，查询前后事件序号不变；daemon 重启后仍可读，genesis checkpoint 验证通过。

整体平台验收仍为部分通过：原生 host wake 未通过，继续执行使用 Codex follow-up；OTel instrumentation/exporter 未实现，diagnostics 为空；用户尚未确认项目完成，未创建最终项目完成 checkpoint。历史桥接 `message.send` 不能单独当作 A2A HTTP 证据，新测试明确标为验收 harness 发起。业务和平台结果分列于 [交付报告与操作命令](evidence/sega-image-manage-tool-2026-09-28/delivery-report.md)，完整 [偏差](evidence/sega-image-manage-tool-2026-09-28/unexpected-deviations.md) 与 [耗时](evidence/sega-image-manage-tool-2026-09-28/timing-record.json) 均保留。按用户要求，流程简化与架构复盘后置。

## 1. 参与者和不可改变的边界

06:17 UTC 后续修正见 [原生唤醒补测](evidence/sega-image-manage-tool-2026-09-28/native-wake-followup.md)：初始 provider 未配置；配置后真实调用因 Desktop 已持有会话 writer 而失败。后来的 explicit follow-up 已证明失败后的 durable pull，但没有产生原生 turn 成功证据。

| 角色 | 会话身份 | 允许做什么 | 禁止做什么 |
|---|---|---|---|
| 用户 | `user_control` | 初始化项目、任命 main、解决重大决定、确认项目完成、执行恢复/迁移 | 不把凭据粘贴到 Agent 对话 |
| 主 Agent | 独立 Codex conversation/session，角色 `main` | 创建/发布/拆分任务，决定普通实现细节，控制 Git，审查 worker 结果，组织协商 | 不能替用户确认项目完成；不能把 worker 会话当成自己 |
| Worker A | 独立 conversation/session，角色 `worker` | 只执行 Web UI 任务，报告理解、证据和结果，领取自己的 Attempt | 不能发布任务、任命 main、控制 Git 主线或确认项目完成 |
| Worker B | 独立 conversation/session，角色 `worker` | 只执行 HTTP 后端任务，报告理解、证据和结果，领取自己的 Attempt | 不能发布任务、任命 main、控制 Git 主线或确认项目完成 |

三个 Codex conversation 必须得到三个不同的 `agent_id`、`session_id` 和 `conversation_id`。IDE 类型 `codex` 不能作为 Agent 身份；验收报告必须保存这些标识的脱敏 digest 或公共 ID，不能合并成一个 `codex` Agent。

主 Agent 控制 Git。默认使用同一业务仓库工作区；隔离方式由主 Agent 按风险选择。Tsunagou scope 是机械边界，宿主 Full Access 不会自动扩大它。Task 长期 `open`/`blocked` 时不因租约阻止未来 worker 领取；Lease 只约束当前执行 Attempt，过期后必须留下旧 Attempt 证据并允许新的领取者。

## 2. 部署和接入验收

### 2.1 目标项目基线

- [ ] 目标路径存在且是 Git 仓库。
- [ ] 部署前保存 `git status --short`、当前 branch、HEAD、`dotnet --version` 和项目文件清单。
- [ ] 部署前 `dotnet build D:\ALL.Net\SegaImageManageTool\SegaImageManageTool.sln` 的结果已记录。
- [ ] 部署脚本没有复制 `D:\Tsunagou` 源码，没有写入 token、ticket 或 bridge session secret。

### 2.2 安装结果

使用仓库内安装器，不使用远程脚本管道：

```powershell
Set-Location D:\Tsunagou
uv run python tools/install/install.py --skill-scope all `
  --project-root D:\ALL.Net\SegaImageManageTool `
  --host codex `
  --project-name SegaImageManageTool `
  --project-objective "Implement and verify a Web UI and HTTP backend while exercising Tsunagou multi-agent A2A coordination, persistence, conflict handling, and traceability." `
  --json
```

验收应看到：

- [ ] 目标仓库出现 `.tsunagou/project.json`、`.tsunagou/agent-context.md` 和非秘密集成清单。
- [ ] 目标仓库出现项目级 `AGENTS.md`/`.agents/skills/tsunagou-project` 入口，明确 main/worker 边界、A2A pull/wake 约定和禁止伪造证据。
- [ ] `D:\Tsunagou\packages\bridge-server\dist\server.js` 可执行，Node syntax check 通过。
- [ ] `uv run python -m tsunagou --version`、`daemon status`、`doctor` 的结果带时间和退出码。
- [ ] 安装重复执行不会产生第二个项目、第二份身份或覆盖用户文件。

### 2.3 Daemon 和三会话

```powershell
$env:TSUNAGOU_PROJECT_ROOT='D:\ALL.Net\SegaImageManageTool'
$env:TSUNAGOU_STATE_DIR='D:\ALL.Net\SegaImageManageTool\.tsunagou\local'
uv run python -m tsunagou daemon start --coordination-root $env:TSUNAGOU_PROJECT_ROOT --port 0
uv run python -m tsunagou daemon status
uv run python -m tsunagou doctor
```

主 Agent 和两个 worker 使用不同 profile；正常路径不要求用户发现或粘贴 `conversation_id`/`agent_id`：

```powershell
uv run python -m tsunagou agent connect --adapter codex --profile codex-main --role main
uv run python -m tsunagou agent connect --adapter codex --profile codex-webui --role worker
uv run python -m tsunagou agent connect --adapter codex --profile codex-http --role worker
```

- [ ] 三条命令分别返回独立 profile/bridge 配置，且没有打印秘密。
- [ ] 每个 Codex 会话重载其 bridge 后，`context__project_read` 返回自己的 `agent_id`、`session_id`、角色和项目。
- [ ] main 任命是用户控制动作；worker 不能通过 bridge 自任 main。
- [ ] 如果宿主 wake 不可用，系统必须明确显示 `pull` 恢复路径，不能把 ticket issued 或 callback 2xx 报成 Agent 已执行 turn。

## 3. 总任务和实施边界

主 Agent 创建并发布一个总任务“实现 Web UI + HTTP 后端”，再拆成两个可独立领取的子任务：

### 3.1 Worker A：Web UI

- 页面能启动、显示后端健康状态和主要业务流程。
- 文件上传/选择、请求提交、成功/失败/加载状态和错误信息完整可见。
- 通过明确的 HTTP API 调用后端，不在前端复制业务解密/校验逻辑。
- 至少有一个自动化 UI 或浏览器验收，保存版本、命令、退出码和截图/摘要引用。
- 不修改后端权限、任务状态机或 Tsunagou 持久化格式。

### 3.2 Worker B：HTTP 后端

- 提供健康检查、业务操作、输入校验、结构化错误和 CORS/loopback 边界。
- 保留现有 .NET 8 业务入口的可验证行为；不能用假数据掩盖真实失败。
- 每个请求有 request/trace 关联，并记录安全摘要、耗时、结果状态和验证证据。
- 提供 API contract、后端测试和启动命令；前端可在干净环境中调用。
- 不绕过 Tsunagou scope，也不把 token、原始文件内容或私密 prompt 写入日志。

### 3.3 主 Agent 集成职责

- 先发布两个任务和资源范围，再允许 worker claim/preflight/start。
- 合并 API contract 与 UI 结果，处理冲突，控制 Git commit/branch/merge。
- 发起至少一次认知报告和契约协商；重大设计变化或任务完成提案交给用户确认。
- 最终运行端到端测试、checkpoint、history/diagnostics/audit 查询并提交验收报告。

## 4. A2A 实效验收

下面每项必须使用真实 daemon 的 `/api/v1/a2a` JSON-RPC 或宿主 bridge 产生，不能只调用 MCP 内部函数：

- [ ] Agent Card 声明的 `message/send`、`tasks/get`、`tasks/cancel`、`tasks/fail`、`tasks/retry` 与实际 HTTP 行为一致。
- [ ] main → Web UI worker 和 main → HTTP worker 的 `message/send` 都持久化；重复 `messageId` 和重复 request ID 返回同一安全结果，不新增业务消息。
- [ ] 两个 worker 的 A2A 身份与任务 owner 对应；worker 不能取消/接管另一个 worker 的 Attempt 或 main 的 Attempt。
- [ ] 每条消息至少能观察到 `accepted/delivered/presented/pull` 中的真实阶段；`callback_received`、`wake_requested`、`thread_*`、`turn_*` 分开记录。
- [ ] 若 managed wake 可用，必须观察到真实 host thread/turn 证据；若不可用，必须证明 worker 通过 durable inbox pull 继续工作，并将 wake 标为 unavailable/unknown。
- [ ] worker 请求开放任务时，main 能读取收件箱、判断任务边界并发布/回复；不能停留在只读收件箱而不产生可解释的决策记录。
- [ ] A2A 失败、断线或重启后，消息仍可查询，重试沿用原因果链，不生成第二个 Agent。

证据最少包括：A2A request/response 安全摘要、message ID/request ID digest、发送和接收 agent/session、diagnostic event ID、相关 task/attempt/result/event ID、时间戳和退出码。

## 5. 租约、冲突与关键操作

- [ ] 两个 worker 不能同时拥有同一个 Task/Attempt；重复 claim 是幂等或明确冲突。
- [ ] 人为终止/等待一个 worker，使执行 Lease 过期；daemon 维护后旧 Attempt 变为历史/orphan，Task 回到可领取状态，另一个 worker 可以领取，不要求旧 worker 先上线。
- [ ] 两个任务声明重叠资源范围；系统记录冲突、阻塞原因、Lease owner 和解决者。越权路径必须被拒绝。
- [ ] worker 只能报告理解、假设、不确定性和结果；main 处理分歧并提出契约。用户确认重大设计、项目完成和恢复/迁移。
- [ ] 关键操作（publish、claim、preflight、start、block、request changes、review、checkpoint、decision、completion）都有 actor、subject、command ID、causation、revision、reason、evidence level。
- [ ] 主 Agent 控制 Git 的实际操作能关联到 task/attempt/workspace；系统不声称逐行作者证明。

## 6. 持久化、查询和 blame/OTel

### 6.1 Tsunagou 查询

```powershell
uv run python -m tsunagou project history $projectId --limit 200 --json
uv run python -m tsunagou task history $taskId --project-id $projectId --limit 100 --json
uv run python -m tsunagou project diagnostics $projectId --json
uv run python -m tsunagou audit event $eventId --project-id $projectId --include-evidence --json
uv run python -m tsunagou checkpoint list $projectId --verify
```

- [ ] 查询前后 `as_of_event_seq`/domain revision 不变；查询本身不产生事件。
- [ ] 每个 A2A、租约、冲突、协商和关键操作能从项目 history 追到 task/attempt/message/diagnostic/evidence。
- [ ] 私信正文、token、nonce、绝对路径和隐藏思维链不出现在公共查询。
- [ ] daemon 重启后上述记录仍可读，旧执行授权不自动恢复。

### 6.2 OpenTelemetry 和责任链

本次验收中的 “blame” 指可复核的因果责任链，不指模型隐藏思维链，也不把日志中的最后一个人自动认定为代码作者。实现必须：

- [ ] 在本机显式开启 OTLP/OTel（默认关闭，禁止未经同意的外发），为 HTTP、A2A JSON-RPC、CLI command、Unit of Work、task/attempt、resource conflict、cognition/contract、workspace、checkpoint 和 host wake 建立 span。
- [ ] 每个持久事件和诊断事实至少能关联 `trace_id`/`span_id`（或安全的 trace reference）、`command_id`、`actor_ref`、`subject_ref`、`caused_by_command_id`、`event_id`/`event_seq`、`task_id`/`attempt_id`/`message_id`。
- [ ] 提供一个脱敏 blame 导出或查询视图，按 task/attempt/trace 展示时间线、参与者、决策、冲突、证据等级、结果和失败原因；不能输出 token、prompt 或完整文件内容。
- [ ] 能区分 `agent_asserted`、`host_observed`、`system_verified`、`user_confirmed`，不能用 OTel span 存在替代业务成功证据。
- [ ] 断线、重试、重复消息和重启产生可关联的新 span/diagnostic，但不伪造新的业务事实；trace exporter 失败不能阻塞核心 SQLite 事务。

如果当前实现尚未具备 OTel/blame 查询，验收状态必须是 `incomplete`，不能以“已有 actor_ref/audit event”声称满足本项。

## 7. 成品功能验收

- [ ] `dotnet build`、后端测试、前端构建和浏览器/HTTP E2E 全部通过。
- [ ] Web UI 能从空启动状态发现后端不可用，后端启动后恢复；错误不被静默吞掉。
- [ ] 业务操作使用真实输入和真实结果，保留现有 CLI/库行为回归证据。
- [ ] HTTP 仅监听预期 loopback/用户选择地址，敏感响应不缓存、不打印。
- [ ] 主 Agent 最终提交的任务结果包含 worker 两个结果、API/UI 版本、测试命令、退出码、workspace digest 和审查结论。
- [ ] 用户确认项目完成后生成 checkpoint；checkpoint verify、history、diagnostics 和 blame 证据可从干净重启后重新读取。

## 8. 证据目录和关闭条件

统一保存到 Tsunagou 仓库的 `docs/acceptance/evidence/sega-image-manage-tool-2026-09-28/`，只放脱敏 JSON、命令输出摘要、trace/blame 摘要和必要截图引用；目标项目只保存业务代码、项目级非秘密入口和 `.tsunagou` 状态。

关闭条件：

1. 安装/三会话接入证据完整，三个 Agent 身份 distinct。
2. Web UI + HTTP 后端实际运行，前后端测试和回归通过。
3. A2A 真实 message/send、task 映射、幂等、pull/wake/presentation/turn 分层证据完整。
4. 租约过期重领、资源冲突、权限边界、认知协商和关键操作查询通过。
5. history/diagnostics/audit/checkpoint 重启后可读，秘密扫描通过。
6. OTel/blame 满足第 6.2 节；若未实现，整体不得标记通过。
7. 用户确认重大设计和项目完成；未确认时保持 `pending_user_decision`，不由 Agent 代替。

验收报告必须记录：UTC 毫秒 `started_at`/`finished_at`、Tsunagou HEAD/版本、目标项目 HEAD、Node/.NET/Python 版本、每条命令退出码、task/attempt/message/event/trace 的公共 ID 或 digest、失败重试和遗留限制。不得记录任何可用凭据。
