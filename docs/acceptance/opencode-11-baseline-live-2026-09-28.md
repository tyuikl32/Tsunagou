# OpenCode 11 项共同基线真实验收（2026-09-28）

本轮在真实 OpenCode 宿主（v2.0.18）上完成 11 项共同基线实测：两个真实会话由模型轮次驱动、经 stdio MCP bridge 访问真实 daemon（临时 Git 协调项目）。结构化脱敏结果见 [evidence](../research/evidence/opencode-2026-09-28-live.json)。没有 commit、push 或 release；未放宽身份、owner、scope 或用户专属权限边界。

## 版本与隔离

- 分支 `elysia`，运行基线 `a3954ae20961583be9171be1f9f441af6177a126`；本轮 bridge 修复与文档已提交为 `adda6f5d83e0b483c07397daba78c0a7109d4779`（"opencode11test"），随后与 main 的 PT 系列工作合并为 `cca5618`。合并后的 bridge 已重建并通过凭据交接测试 18/18 与 late-ticket 冒烟（两种模式退出码 0）；本报告的 11 项结论对应运行基线加本轮修复的代码。
- OpenCode `2.0.18`（`opencode --version`）；`opencode serve` 没有旧文档中的 `--pure` 参数，实际参数为 `--hostname/--port/--cors/--serve/--stdio`。
- Node bridge `/packages/bridge-server/dist/server.js`（`tsc` 退出码 0）；daemon `127.0.0.1:8765`。
- 两个真实会话：main 会话 `ses_f18d3da8dffehIF2UxzvikhoNs`（本会话）、worker 会话 `ses_f185609c0ffeXXN5M0q3ibrakC`；fork 会话 `ses_f18498661ffer8rK47LVSIua7X`。会话标识以 SHA-256 前缀脱敏存档。
- 双 profile（`tsunagou-main` / `tsunagou-worker`）生成独立的 ticket、bridge 配置与私有 session 文件；bridge 按 `_meta["ai.opencode/sessionID"]` 为每个会话分配独立私有 session 文件。

## 11 项结果

| # | capability | 结果 | 关键证据 |
|---|---|---:|---|
| 1 | identity.session_isolation | supported | 两个会话产生不同 Agent（`5a80e67e…` vs `7d4b0386…`）、26 vs 15 能力集、独立 session 文件；worker 调 main-only 工具 `capability_denied`；同会话二次 attach 被 `conversation_already_attached` 拒绝 |
| 2 | identity.continuity_evidence | supported | resume/reconnect 保持身份；新会话与 fork（`ses_f18498661ffe…`）产生新会话 id；本版本无手动 compact/clear 入口（注记） |
| 3 | context.project_read | supported | 两会话读取同一 `project_id` 与各自身份；调用无投影注入面，绑定由服务端决定 |
| 4 | command.typed_tools | supported | `tools/list` 53 个带 schema 的工具；调用者身份来自服务端凭据；main-only 操作对 worker `capability_denied` |
| 5 | task.lifecycle | supported | create→ready→publish→claim→workspace.select/prepare→resource.intent/acquire→preflight→start→progress→block→resume→再 acquire→preflight→start→submit；旧 revision `task_revision_conflict` |
| 6 | cognition.report | supported | worker/main 报告 + 分歧创建/解决；worker 越权 resolve 被拒 |
| 7 | contract.participation | supported | 正确 digest `accepted`；stale digest `proposal_digest_mismatch`；槽位绑定错配 `participant_slot_denied` |
| 8 | inbox.pull_fetch_ack | supported | claim/fetch/presented/ack 四步分离；非收件人 fetch `inbox_access_denied`；重复投递不产生第二份 |
| 9 | response.structured | supported | 义务生成；ACK 后仍 `open`（不冒充响应）；带 `in_reply_to` 的响应消息经 respond 结清；未链接响应被拒 |
| 10 | recovery.idempotent_reconnect | supported | 杀 bridge 进程后宿主重连：身份不变、epoch 1→2；旧 epoch 头 401 `authentication_failed`，当前 epoch 200 |
| 11 | delivery.deduplicate | supported | 同 `command_id` 重放返回同一 message id；改 payload `idempotency_conflict`；收件箱无重复 |

## 运行命令（摘要）

```powershell
# daemon + 临时协调项目
tsunagou daemon start --coordination-root <temp-git-project> --port 8765
# 为真实会话签发 ticket（会话 id 由宿主提供）
$env:TSUNAGOU_HOST_CONVERSATION_ID = "ses_f18d3da8dffehIF2UxzvikhoNs"
tsunagou agent connect --adapter opencode --role main --profile tsunagou-main --no-register-host
tsunagou agent connect --adapter opencode --role worker --profile tsunagou-worker --no-register-host
# 真实宿主轮次驱动 MCP 工具（示例）
opencode run --session ses_f185609c0ffeXXN5M0q3ibrakC --format json "<tool instructions>"
# 宿主重连（模拟重启后）
opencode reload
# 旧/新 epoch 对照（脱敏脚本）
python epoch-test.py <bridge-session.json> 1 2   # stale -> 401, current -> 200
```

所有 `tsunagou`/`opencode`/`node` 验收命令退出码为 0；负例命令由 daemon 返回结构化 `tsunagou_error:*` 并以工具错误呈现（预期行为）。

## 本轮修复的产品代码（未提交）

`packages/bridge-server/src/server.ts`：

1. 从 MCP 工具调用 `_meta["ai.opencode/sessionID"]` 提取宿主会话身份（OpenCode 不提供会话环境变量），digest 前缀与 ticket 路径统一为 `conversation_id:`，保证同一会话跨调用身份一致。
2. 多会话宿主下按会话分配私有 session 文件（`<stateDir>/sessions/bridge-session-<digest>.json`），单会话宿主仍使用 `TSUNAGOU_SESSION_FILE`。

## 诚实说明

- `compact`/`clear` 在 OpenCode 2.0.18 中没有可手动触发的入口，本轮以 resume/reconnect/new/fork 覆盖连续性语义，未声称 compact/clear 已实测。
- 跨项目对照（第二个协调项目）未跑；`context.project_read` 的「不串项目」由服务端凭据绑定与两会话身份隔离共同支撑，调用本身无项目选择参数。
- 自动唤醒（`wake.push`）是增强项，本轮 bridge 报告 `unsupported`（stdio 无宿主反向唤醒通道），不计入 11 项。
- 原始会话标识、token、ticket 与私有 session body 只进入私有运行目录；仓库仅保留 digest 前缀与脱敏引用。
