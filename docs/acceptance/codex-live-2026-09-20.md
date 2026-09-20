# Codex 单宿主真实 bridge 复验（2026-09-20）

本轮只验证 Codex 的十项待补能力，不改变三宿主首发门禁。主张以真实 Codex 模型发起的 MCP 工具调用为准；协同方的 [五项工具 HTTP 证据](../research/evidence/codex-gap-tools-2026-09-19T2317-http.json)和 [三缺陷 HTTP 证据](../research/evidence/codex-fixes-2026-09-19T2229-http.json)仅作前置交叉检查。脱敏机器证据见 [本轮 JSON](../research/evidence/codex-2026-09-20T0002-live.json)。未改产品源码，未 commit、push 或 release。

## 宿主、隔离与实际命令

- 分支 `elysia`，HEAD `081116d`；Codex CLI `0.155.0-alpha.9.2`；Node `v24.20.0`；bridge/Tsunagou `0.1.0`；协议 `1.0`，schema bundle `sha256:f2c3d8e0dc89f8b454288048d6326a4446f51659003045ac6194d6da39545fc6`；本轮 bridge 构建 SHA-256 `f00aeab932fdf11d8e78aba26754c3e83f12c6199aba36734bd3bbdc2860e833`。
- 两条专用 Codex 会话来自独立空项目，conversation digest 分别为 `b4a24ebfcb39e6b4f487a10fa11dffd9a9dc3387fcb92bcb6a936177497212dd`（main）与 `5d08f1afa878e5ceda474ce0257a90b9e38007f33a5e1d7dc10b585b4bea7b0a`（worker）。digest 算法为 SHA-256(`conversation_id:` + 原始 ID)；原始 ID 不入库。独立 loopback 服务和状态目录使用一次性私有凭据；票据由运行中的 U HTTP 命令签发并由 bridge 兑换。两会话最终均为运行时 `ready`、epoch 2。
- 本轮从持久化的隔离身份状态重启当前服务/bridge 后继续这两条仅完成入会的会话。worker 首次 rebind 的 Codex CLI 退出码为 1：MCP `inbox__claim` 已完成且会话已 `ready`，随后该 turn 因网关连接失败而 `turn.failed`。以下四个业务 turn 各自退出码均为 0。服务重启后的 MCP 可用不等于在途断线复验。

实际 CLI 调用的脱敏形式如下；`<...>` 均来自一次性私有文件，未写到 stdout 或仓库。四个业务 turn 均通过同一 `resume` 命令运行，分别替换 `<role>`、`<private-thread-id>` 与提示词；原始 JSONL 仅留在隔离目录，提取脱敏结果后清理。

```powershell
codex exec --json --ignore-user-config --skip-git-repo-check -s read-only -C <empty-isolated-project> '<main-or-worker-seed-prompt>'

codex exec resume --json --ignore-user-config --skip-git-repo-check `
  -c "mcp_servers.tsunagou.command='node'" `
  -c "mcp_servers.tsunagou.args=['<bridge-dist-server-js>']" `
  -c "mcp_servers.tsunagou.default_tools_approval_mode='approve'" `
  -c "sandbox_mode='read-only'" `
  -c "approval_policy='never'" `
  -c "mcp_servers.tsunagou.env.TSUNAGOU_HTTP_URL='http://127.0.0.1:<isolated-port>'" `
  -c "mcp_servers.tsunagou.env.TSUNAGOU_TICKET_FILE='<private-ticket-file>'" `
  -c "mcp_servers.tsunagou.env.TSUNAGOU_SESSION_FILE='<private-session-file>'" `
  -c "mcp_servers.tsunagou.env.TSUNAGOU_PROJECT_ROOT='<empty-isolated-project>'" `
  -c "mcp_servers.tsunagou.env.TSUNAGOU_STATE_DIR='<private-bridge-state>'" `
  <private-thread-id> '<bounded-acceptance-prompt>'
```

业务 turn 的时间来自私有日志文件创建/末次写入时间，**不是**伪称的模型事件时间。网关重试曾产生 `error` 事件，但四轮最终 `turn.completed`：

| 业务 turn | 日志窗口 UTC | CLI 退出码 | 网关 `error` 事件 |
|---|---|---:|---:|
| main：项目查询、任务、同参发送 | 00:02:40–00:05:05 | 0 | 5 |
| worker：任务生命周期、对象报告 | 00:06:57–00:09:19 | 0 | 4 |
| worker：坏 claims、收件、回应、越权 | 00:11:45–00:14:09 | 0 | 4 |
| main：未知字段和伪造 actor | 00:14:59–00:17:01 | 0 | 4 |

## 真实 MCP 观察与判定

| 能力 | 本轮正例与必要负例 | 正式判定 |
|---|---|---|
| `identity.session_isolation` | 两个专用会话 digest 不同，均完成真实 bridge 入会；另见 [前轮独立复验](codex-independent-2026-09-19.md)。 | `supported`（保留） |
| `identity.continuity_evidence` | resume/rebind 和服务重启后的调用成立；未观察有内容会话的 compact、fork、new。 | `unknown` |
| `context.project_read` | main、worker 均真实调用 `context__project_read`；worker 返回 11 项 scope 能力且包含已认领任务。返回字段只有 `agent_id`、`role`、`main_agent_id`、`scope`、`tasks`，**没有 project ID**。 | `unknown`：未满足前轮明确的项目 ID／任务／scope 查询口径 |
| `command.typed_tools` | 多个合法 typed 调用完成；额外 `unexpected_field`、伪造 `actor_id` 均被 `unknown_payload_field` 拒绝，未建消息；worker 越权 `task__create` 被 `capability_denied` 拒绝。 | `supported` |
| `task.lifecycle` | main 真实 `task__create`；worker 真实 claim→preflight→start→progress→submit，返回对应 attempt/preflight/progress/result 标识；预先使用伪 preflight 的 start 被 `preflight_id_mismatch` 拒绝，随后有效 start 成功。任务 digest `c4ade96960bc7e3cba66a0df3fa53778850eb7b7aacc7b55b808f2f620abd0c1`。 | `supported` |
| `cognition.report` | worker 的真实对象 claim 含 `subject_key`、`claim_type`、`equality_key`、`value`、`evidence_refs`，另有字符串 assumptions 与空 uncertainties，返回 `report_id`；字符串 claim 负例返回 `invalid_claim`。 | `supported` |
| `contract.participation` | 本轮未重跑；前轮真实 main 提案、worker 按 digest 接受的证据仍有效。 | `supported`（保留） |
| `inbox.pull_fetch_ack` | 本轮 worker 再次真实 claim→fetch→presented→ack；前轮也有完整正例。 | `supported`（保留） |
| `response.structured` | main 发送 `response_contract={"required":true}` 的消息；worker 以不存在的回应 ID 调用 `message__respond` 得 `response_message_not_found`，后续真实关联回应成功且最终义务为 `responded`。但 `inbox__fetch` 不暴露 obligation ID，本轮由隔离测试状态私下提供；服务端也未校验回应内容的 response schema。 | `unknown`：仅修复了回应存在／发送者／关联校验，完整结构契约尚未成立 |
| `recovery.idempotent_reconnect` | 服务重启后旧会话可经 bridge 调用；未做“服务端已接收命令、客户端在途断线”的故障注入。 | `unknown` |
| `delivery.deduplicate` | main 在同一真实 turn 中以完全相同参数连续两次 `message__send`，返回同一消息 ID（digest `40e327b22497bed75553a0be7520ee083e8e856522fb9d20897b0a70e1d281b1`）。当前 bridge 从整个 payload 派生 `command_id`，typed MCP 调用者不能以**同一原始 command ID、不同输入**触发冲突；该负例只有协同方隔离 HTTP 证据。 | `unknown`：缺严格口径要求的真实 MCP 冲突负例 |

本轮为 **6/11 supported、5/11 unknown**。运行时 `ready` 只表示四项会话准入的当前判定；正式十一项还要求每项完整真实证据，不能把 `ready` 当成十一项通过。未修改 OpenCode、DeepSeek Harness 或发布门禁状态。

## 给协同方的交接清单

1. `context.project_read`：在后端、bridge/schema、测试与隔离 HTTP 证据中补可验证的 project ID，并确认它与当前项目绑定；现有真实输出只含 agent/role/main/scope/tasks。完成后我只需一次真实 `context__project_read`。
2. `response.structured`：让收件方经公开 typed 工具取得自己的 obligation ID；补 response schema 的校验、正负例及脱敏脚手架。当前真实存在性负例已通过，但完整能力仍是 `unknown`。完成后我只需一次带 schema 的真实回应正负例。
3. `delivery.deduplicate`：确认同一原始 `command_id` 的比较覆盖 `priority`、`response_contract`、`in_reply_to` 等全部有副作用的输入；目前代码比较未包含这些字段。准备能通过真实 Codex MCP 安全演示“同 ID 改输入冲突”的测试接口或故障注入方式，并跑单测、隔离 HTTP 正负例。现有 typed bridge 对不同输入总会生成不同 ID，我不会把 HTTP 结果冒充真实 MCP 结果。
4. `recovery.idempotent_reconnect`：交付在途断线注入脚本、独立状态与安全清理步骤，覆盖服务端接收后断线、重连、旧 epoch 拒绝和幂等结果。我只执行最终真实 Codex 调用。
5. `identity.continuity_evidence`：交付有内容会话的 compact/fork/new 触发脚本与脱敏记录模板；只在脚本可运行后使用真实宿主额度。
6. 协同方继续负责协议/schema、后端/bridge 修复、单测、隔离 HTTP、打包与显式 descope、host matrix 更新。本轮只产生脱敏 evidence；不提交、不推送、不发布。
