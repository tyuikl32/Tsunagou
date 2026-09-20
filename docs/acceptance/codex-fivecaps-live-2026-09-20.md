# Codex 剩余五项的真实单宿主复验（2026-09-20）

本轮沿用 [前轮独立复验](codex-live-2026-09-20.md)的正式证据口径，只对五项 `unknown` 做真实 Codex bridge 调用。脱敏结构化结果见 [本轮 evidence](../research/evidence/codex-2026-09-20T1628-fivecaps-live.json)。没有改产品代码、Git 分支、Codex 配置、`auth.json`、cc-switch；没有 commit、push 或 release。原有未提交产品修复保持原样。

## 版本、隔离和实际命令

- 分支 `elysia`，HEAD `081116d9b6354ab986a4e71a89f9dc1bfe235e08`，产品工作树已有未提交修改。Codex CLI `0.155.0-alpha.9.2`；Node `v24.20.0`；bridge/Tsunagou `0.1.0`；协议 `1.0`；schema bundle `sha256:f2c3d8e0dc89f8b454288048d6326a4446f51659003045ac6194d6da39545fc6`。当前 bridge `dist/server.js` SHA-256 为 `3314f08472f83ad7e95209e77c93087cc018d09b2bbc663c0a2ed41328c23871`；修改过的源码哈希见 JSON evidence。
- 模型后端记为 `gpt-5.6-sol`，来源是用户在本轮的明确确认；`codex exec --json` 未独立暴露 model/backend 字段。按约束未读取用户 Codex 配置或 `auth.json`，也没有沿用模板里未经证实的 `deepseek`。
- 使用两条新建专用 Codex thread、一个空的独立 Git 项目、独立 loopback 后端和私有 run 状态。main/worker 的 conversation digest 分别为 `1ce45cef4d2234bc6c0604725f3f4add819f03623aaad023e13d8341ba07d08f` 与 `377ad006b269076c37281ed4f9b20bd93a5a7ec5effd958102c74d7d9517ddd4`，均为 SHA-256(`conversation_id:` + 原始 ID)。原始 ID、票据、token、nonce 和转录只进入私有 run，清理后不保留。
- 交付的 `issue_tickets.py` 必须接收两条 conversation ID，因此实际顺序为 `prep.py` → `start_server.py` → 两条无工具 seed → `issue_tickets.py` → 首次 bridge 兑换 → 再签票 → 同 thread rebind。首次兑换两个会话均为 `degraded`/epoch 1；第二次票据被 bridge 消耗后均为 `ready`/epoch 2，agent ID 保持不变。隔离 U 控制端指定 main 返回 HTTP 200。seed、首次入会、两次签票及以下五个业务 turn 的退出码均为 0。

实际 CLI 命令的脱敏骨架如下；业务 turn 分别使用交付提示词及本轮增加的坏 schema 负例。原始 CLI JSONL 被重定向到私有 run；终端只输出工具状态与退出码。使用只读 CLI sandbox，没有采用模板中的 `--dangerously-bypass-approvals-and-sandbox`。

```powershell
codex exec --json --ignore-user-config --skip-git-repo-check -s read-only -C <empty-project> '<seed-prompt>'

codex exec resume --json --ignore-user-config --skip-git-repo-check `
  -c "mcp_servers.tsunagou.command='node'" `
  -c "mcp_servers.tsunagou.args=['<current-bridge-dist-server-js>']" `
  -c "mcp_servers.tsunagou.default_tools_approval_mode='approve'" `
  -c "sandbox_mode='read-only'" `
  -c "approval_policy='never'" `
  -c "mcp_servers.tsunagou.env.TSUNAGOU_HTTP_URL='http://127.0.0.1:<isolated-port>'" `
  -c "mcp_servers.tsunagou.env.TSUNAGOU_TICKET_FILE='<private-role-ticket-file>'" `
  -c "mcp_servers.tsunagou.env.TSUNAGOU_SESSION_FILE='<private-role-session-file>'" `
  -c "mcp_servers.tsunagou.env.TSUNAGOU_PROJECT_ROOT='<empty-project>'" `
  -c "mcp_servers.tsunagou.env.TSUNAGOU_STATE_DIR='<private-role-bridge-state>'" `
  <private-thread-id> '<bounded-prompt>'
```

| 真实业务 turn | 私有日志创建至末次写入，UTC | CLI 退出码 | 实际 MCP 结果 |
|---|---|---:|---|
| main 项目查询兼 rebind | 08:41:36–08:44:13 | 0 | `context__project_read` completed |
| worker 同 thread resume | 08:44:57–08:47:33 | 0 | `context__project_read` completed |
| main 请求与去重 | 08:50:26–08:52:38 | 0 | 三次 `message__send` completed，一次 `command_id_conflict` failed |
| worker 结构化回应 | 08:54:17–08:57:25 | 0 | inbox claim/fetch、两个预期回应错误、有效回应 completed |
| main 故障脚本后查询 | 08:59:45–09:01:47 | 0 | `context__project_read` completed |

每轮有 4 个网关 `error` 重试事件，但最终均 `turn.completed`。表中时间是私有日志文件时间，不冒充模型事件时间。CLI 退出 0 本身不作为能力证据，以下判定来自对应的 MCP 参数、返回和隔离状态。

## 五项判定

| 能力 | 本轮真实观察及必要负例 | 正式状态 |
|---|---|---|
| `context.project_read` | main、worker 的真实 `context__project_read` 均返回与隔离项目配置一致的 `project_id`，以及绑定 agent、role、main_agent_id、scope.capabilities、tasks 字段。当前空项目的 tasks 数为 0；[前轮 evidence](../research/evidence/codex-2026-09-20T0002-live.json)另有真实 worker 已认领任务出现在任务列表的正例。 | `supported` |
| `response.structured` | main 真实发送 `required=true`、schema 要求字符串 `verdict` 的请求。worker 从**公开** `inbox__fetch` 取得 open obligation ID 和 schema；不存在的回应 ID 返回 `response_message_not_found`。worker 发关联请求但数值型 verdict 的真实消息，`message__respond` 返回 `response_schema_violation`；随后字符串型 verdict 的关联真实消息使同一义务 `responded`。后一次成功也证明两个负例没有先关闭义务。 | `supported` |
| `delivery.deduplicate` | main 在同一真实 Codex turn 中三次通过 typed MCP `message__send` 传入同一**显式原始** `command_id`。前两次同输入返回相同消息 ID；第三次改 summary 返回 `command_id_conflict`。在 worker 回复前，隔离消息存储总数为 2：一条结构化请求和一条去重测试消息，冲突未建第二条测试消息。 | `supported` |
| `recovery.idempotent_reconnect` | 交付的 `recovery_fault_inject.py` 退出 0，隔离 HTTP 的一次性会话验证在途发送一次、重连后同 ID 幂等、旧凭据失效；真实 Codex main 随后也能调用 `context__project_read`。但脚本断开及重连的是**另建的 disposable 会话**，真实 Codex main 的 epoch 仍为 2，未经历在途断线或重连。 | `unknown`：缺同一真实 Codex 会话上的故障注入与恢复证据 |
| `identity.continuity_evidence` | 真实 main/worker 在同 thread rebind 后 agent ID 和 host digest 保持不变，worker 又完成一次真实 resume 查询。交付的 `continuity_trigger.py` 退出 0，但它以三个新造的字符串 ID 调用 HTTP，分别标记为 compact/fork/new；它没有对有内容的真实 Codex thread 触发 compact、fork、new。 | `unknown`：只证实普通 resume，真实生命周期三场景缺证据 |

结合原先六项，本轮正式基线为 **9/11 supported、2/11 unknown**。运行时 `ready` 仅是四项会话准入的当前判定，不等于十一项全部完成；OpenCode、DeepSeek Harness 和发布门禁没有变化。本轮未重跑协同方的单测、类型检查与隔离 HTTP 回归；这些已有结果记录在 [缺口修复材料](codex-live-2026-09-20-followup.md)，不得说成本轮亲测。

## 剩余最小交接

1. 协同方需把 recovery 故障注入接到**同一条真实 Codex bridge 会话**，确认服务端已接收命令时客户端断线、同会话重连后幂等恢复、旧 epoch 拒绝。现有脚本只验证一次性 HTTP 会话。
2. 协同方需准备真实 Codex 有内容会话的 compact、fork、new 触发与 digest/身份记录。现有脚本对合成 conversation ID 的 HTTP 行为不能充当宿主生命周期证据。
3. 模型后端 `gpt-5.6-sol` 由用户确认，CLI JSONL 未独立提供；后续证据应继续分别记录报告来源与宿主实际返回。

不得把两项 `unknown` 写成 supported，也不得把脚本的合成标签当成真实宿主行为。下一轮只补这两项，避免重跑已完成的三项。
