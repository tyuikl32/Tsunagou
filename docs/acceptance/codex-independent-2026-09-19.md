# Codex 双会话独立复验：2026-09-19

本次仅复验 Codex 单宿主的十项缺口，不涉及 OpenCode、DeepSeek Harness、首发发布或 T24 实验。操作者是协同验收人员 `elysia080928`；仓库分支 `elysia`，HEAD `166045e`。完整脱敏结果见 [本轮 evidence](../research/evidence/codex-2026-09-19T2136-independent.json)。本轮没有修改产品代码、提交或推送。

## 环境与隔离

- 时间窗：2026-09-19 21:10–21:41（UTC+08:00）。宿主 `codex-cli 0.155.0-alpha.9.2`，Node `v24.20.0`，Tsunagou `0.1.0`，uvicorn `0.53.0`，bridge server `0.1.0`，协议 `1.0`，schema bundle digest `sha256:dfda63da8594b8a2e02d080ef33dd17a8259b74900cc69e3b605b5068e95b122`。
- 使用全新的 Codex main/worker thread、独立空项目目录、独立 loopback HTTP 端口和独立 Tsunagou 状态目录。CLI 以 `--ignore-user-config` 和参数覆盖装入该轮 bridge，未修改用户 Codex 配置。隔离 `CODEX_HOME` 的 `codex login status` 返回退出码 1 / `Not logged in`；真实模型轮次只借用 CLI 已登录的认证状态，不读取或复制凭据。两个测试 thread 因而保存在已登录的 Codex profile 中；本轮不删除或读取该 profile 的其他会话。
- 两个原始 thread ID 只在临时编排文件中使用。保存的 host conversation digest 分别为 `9e1ad0855065d6584d27bd05df3c1c591f80799288b21f35236b4e067a27f6d1`、`6604b05d79bf89d32bb9c9d9117ef59109839098512015b7dd60f69aa446d45a`，均与编排方观察的真实 thread ID 经 `sha256("conversation_id:" + id)` 计算结果一致且彼此不同。票据、session token、nonce、原始 ID、完整转录和私有绝对路径不进入本文件或 evidence。
- 所有原始 JSONL 和私有凭据仅放在临时验收目录，审查后销毁。下表中的“CLI 退出 0”只表示该轮结束；每项业务结论另以 MCP 工具状态及返回内容判定。

## 实际步骤、退出码与观察

| 时间（UTC+08:00） | 实际调用摘要 | 退出码 / HTTP | 观察 |
|---|---|---:|---|
| 21:10 | `codex exec --json --ignore-user-config --skip-git-repo-check -s read-only -C <isolated-project> <seed-prompt>`；随后 `agent.ticket.create.user`、`codex exec resume ...` | CLI 0；HTTP 200；CLI 0 | main 首次票据兑换入会，epoch 1，`degraded`。此前沙箱内直接启动 CLI 曾以退出码 1 / `Access denied` 失败；获授权的真实宿主运行才继续。 |
| 21:12 | 同一 main thread 的新票据、`codex exec resume ...`，模型调用 `inbox__claim` | HTTP 200；CLI 0；MCP completed | 同一 host digest，epoch 2，`ready`；空 inbox 返回 `count=0`。 |
| 21:13–21:16 | 第二个 seed thread、worker 入会、再用新票据 rebind，模型调用 `inbox__claim` | 各 CLI 0；票据 HTTP 200；MCP completed | worker 与 main host digest 不同；worker epoch 1→2、`degraded`→`ready`。 |
| 21:17–21:23 | U 凭据任命 main，M 凭据 `task.create`；worker MCP `task__claim`、`task__start`、`cognition__report`、`task__submit` | 前三项 HTTP/MCP 成功；报告六次 `invalid_claim`；报告轮次人工停止，CLI 1；另起提交轮次 CLI 0 / MCP completed | claim→start→submit 有真实返回；报告中的 `claims` 被 Codex 传为字符串数组，后端要求对象数组。没有将报告失败写为通过。 |
| 21:23–21:29 | main MCP `contract__propose`、`message__send`；worker MCP `contract__accept`、`inbox__claim`、`inbox__fetch`、`inbox__presented`、`inbox__ack`、`message__send`、`message__respond` | 两轮 CLI 0；所列 MCP 均 completed | 指定 worker 身份接受同一 proposal digest；recipient 拉取、呈现、ACK 后，回应义务状态为 `responded`。模型连接曾多次超时重连，但工具最终完成。 |
| 21:30–21:33 | 对 worker 的 `session.reconnect` 用错误 nonce、正确 nonce、旧凭据重试；随后新票据 rebind，并用真实 Codex worker 再次调用 `inbox__claim` | 403 `stale_reconnect_nonce`；200 epoch 2→3；401 `authentication_failed`；CLI 0 / MCP completed | 新票据 rebind 后 worker epoch 4 且工具可用。此轮没有模拟“命令已到服务端而客户端断线”的在途请求。 |
| 21:33–21:36 | main 在一轮真实 Codex MCP 中两次以完全相同参数调用 `message__send` | CLI 0；两次 MCP completed | 两次返回同一个 message ID；同输入去重正例成立。 |
| 21:33–21:41 | 隔离 HTTP 负例：同一 `command_id`、同一输入重复；再以同一 `command_id` 改输入 | 200 / 200 / 200 | 前两次为同一 message ID；改输入仍创建新消息，未报冲突。此负例是直接 HTTP，不冒充 Codex 模型工具调用。 |
| 21:36–21:41 | 隔离 HTTP 负例：发出带 response schema 的义务，再以不存在的 `response_message_id` 调用 `message.respond` | 200 | 服务端仍将义务标为 `responded`；该负例是直接 HTTP。 |

复现用的命令骨架是 `codex exec resume --json --ignore-user-config --skip-git-repo-check -c mcp_servers.tsunagou.command='node' -c mcp_servers.tsunagou.args=['<bridge-server/dist/server.js>'] -c mcp_servers.tsunagou.default_tools_approval_mode='approve' -c mcp_servers.tsunagou.env.TSUNAGOU_HTTP_URL='<isolated-loopback-url>' ... <observed-thread-id> <prompt>`。每次票据由运行中的同一 HTTP 服务通过 `agent.ticket.create.user` 签发，并仅交给 bridge 私有文件；不能用 CLI `agent enroll` 的退出码代替兑换。原始命令中的路径、端口和身份值是一次性的，不应照抄。

## 十项判定

“观察到”是本轮真实 Codex 宿主与隔离服务的结果；“正式状态”保持保守，依 [首轮验收规则](first-live-acceptance.md) 未补齐的负例和故障步骤仍为 `unknown`。`ready` 仅是四项准入门槛的运行时判定，不是十一项正式基线通过。

| 能力 | 本轮真实观察 | 正式状态 / 后续最小补证 |
|---|---|---|
| `identity.continuity_evidence` | main、worker 均在真实 resume/rebind 后保持同一 digest，epoch 1→2；新 thread digest 互异 | `unknown`：再核对有内容会话的 compact 与 fork/new 生命周期，不能只用票据 rebind 代替全部连续性场景。 |
| `context.project_read` | bridge 列出项目根目录并记录 digest | `unknown`：当前工具目录没有项目 ID、任务与 worker scope 查询工具；目录 digest 不等于读取项目语义。 |
| `command.typed_tools` | 真实 Codex 列出并调用 typed MCP 工具；但 `cognition__report.claims` 的 schema 仅是 `type: array` | `unknown`：补全元素 schema、额外字段及 actor 的拒绝验证；本轮报告调用的六次 `invalid_claim` 是反例。 |
| `task.lifecycle` | worker 经 MCP 完成 claim、start、submit；main 经 HTTP 创建任务 | `unknown`：仍缺真实 Codex 的 preflight/progress 步骤及对应工具/证据。 |
| `cognition.report` | 六次真实 MCP 报告均因字符串 claim 被后端拒绝 | `unknown`（当前阻断）：使工具 schema 与后端对象字段一致后复测显式理解、假设、不确定性和证据。 |
| `contract.participation` | main 提案、worker 以自身身份接受精确 proposal digest，均为真实 MCP 完成 | `supported`（本轮指定双方正例）；保留 proposal digest 与 actor 绑定的脱敏结果。 |
| `inbox.pull_fetch_ack` | 真实 recipient 经 claim→fetch→presented→ack，隔离状态为 `acked` | `supported`（拉取链路正例）；断 push 后补拉与非 recipient 拒绝可作为后续加强。 |
| `response.structured` | 真实 MCP 义务回复完成；HTTP 负例中不存在的回复消息 ID 仍被接受，合同 schema 也未校验 | `unknown`（语义不满足）：先校验回应消息存在、发送者、关联义务和 response schema，再复测。 |
| `recovery.idempotent_reconnect` | 真实会话的 D 凭据 nonce CAS 与 epoch 轮换成立，旧凭据失效；Codex 再入会后 MCP 可用 | `unknown`：补“服务端已接收命令而客户端断线”故障注入及旧连接在途提交拒绝。 |
| `delivery.deduplicate` | 真实 MCP 同输入两次返回同一消息；HTTP 负例同 `command_id` 改输入却生成第二条 | `unknown`（语义不满足）：按原始 `command_id` 绑定输入 digest，改输入应冲突且不产生第二次动作。 |

## 定位与交接

- `cognition__report` 的 `claims` 缺少对象元素定义（`packages/bridge-server/src/server.ts`），而后端 `_claim` 要求 dict（`src/tsunagou/application/handlers.py`）；真实 Codex 六次生成字符串元素，均报 `invalid_claim`。交给实现负责人修复，本轮未改代码。
- `message.respond` 的服务端路径只按 obligation ID 标记完成，未核对 `response_message_id` 是否存在以及 schema（`src/tsunagou/modules/messaging.py`）；隔离负例返回 200。
- dispatcher 的 `command_hash` 不含原始 `command_id`（`src/tsunagou/interfaces/runtime.py`），`MessageStore` 以此 hash 作为去重键。隔离负例证明同 command ID 改输入不会冲突，而会成为新消息。
- `context.project_read` 的当前准入证据只来自 `readProjectDigest` 对根目录名称的读取；它无法替代项目 ID、任务和 scope 查询。`task.lifecycle` 的桥接工具也缺 preflight/progress。

下一轮建议先修复上述语义缺口并为它们补真实宿主负例，再覆盖 compact、断 push 补拉与在途断线。Codex 专项结果不改变 OpenCode、DeepSeek Harness 的状态，也不提升发布门禁。
