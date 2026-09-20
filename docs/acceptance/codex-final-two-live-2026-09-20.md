# Codex 最后两项的真实单宿主复验（2026-09-20）

本轮补齐前轮仍为 `unknown` 的最后两项：`identity.continuity_evidence` 与 `recovery.idempotent_reconnect`。连续性由真实 Codex 宿主事件证明；恢复由真实 Codex bridge 重连、重连后业务调用和一次性 HTTP 会话的在途故障注入组成，三种来源分别标注。脱敏结构化结果见 [本轮 evidence](../research/evidence/codex-2026-09-20-final-two-live.json)及[只读补证审计](../research/evidence/codex-2026-09-20-final-two-audit.json)。没有改产品代码、Git 分支、Codex 配置、`auth.json`、cc-switch；没有 commit、push 或 release。原有未提交产品修复保持原样。

## 版本与隔离

- 分支 `elysia`，HEAD `081116d9b6354ab986a4e71a89f9dc1bfe235e08`，产品工作树已有未提交修改（本轮只新增 docs 文件，不覆盖他人改动）。Codex CLI `0.155.0-alpha.9.2`；Node `v24.20.0`；bridge/Tsunagou `0.1.0`；协议 `1.0`。
- 模型后端记为 `gpt-5.6-sol`，来源是用户明确确认；`codex exec --json` 未独立暴露 model/backend 字段，按约束未读取用户 Codex 配置或 `auth.json`。
- 原始 conversation ID、票据、token、nonce 和完整转录只进入私有 run，结束后 `cleanup.py --purge`。提交仓库的只有 digest 与布尔判定。

## 能力一：identity.continuity_evidence（`supported`）

用真实有内容的 main thread（host digest `1ce45cef…`）跑通生命周期三场景，且 digest 连续性符合预期：

| 场景 | 真实触发方式 | host digest 结果 |
|---|---|---|
| compact | 用户在 App 手动压缩真实对话，观测 exec rollout jsonl 的 `compacted` 事件 | 不变 `1ce45cef…`（同 UUID 原地压缩，`replacement_history` 21→7，window 1） |
| fork | `codex exec fork` 真实派生，观测 child rollout `session_meta.forked_from_id` | 新 `0069db8d…`（`forked_from_id` 指向 main，ordinal_exclusive=115） |
| new | 全新 thread 冷启动，无 fork 父级、无 spawn edge | 新 `571b1481…`（tokens_used=13963，证明空历史） |

判定依据：compact 保持同一身份（digest 不变）、fork/new 产生新身份（distinct digest）。注意 exec 线程的压缩证据在 rollout jsonl 的 `compacted` 事件，而非 `thread_history_1.sqlite` 的 `contextCompaction`（后者仅 vscode 来源）；fork 证据在 child 的 `session_meta.forked_from_id`，而非 `thread_spawn_edges`。此前把“同 thread resume = compact”当替代品的做法已按约定弃用。

## 能力二：recovery.idempotent_reconnect（`supported`）

按既定 Path B 让 bridge 自身在“有 session 文件、无票据文件”时调用 `session.reconnect`。真实 worker session（host digest `377ad006…`）完整走通：

1. `agent.enroll` → epoch 1（`degraded`）
2. `session.rebind` → epoch 2（`ready`）
3. bridge 无票据发起 `session.reconnect` → epoch 3（`ready`），HTTP 200，agent_id / session_id 保持不变
4. 重连后的同会话业务命令 `context.project_read` → HTTP 200（重连会话可用）

旧凭据拒绝（同一条真实会话上）：旧 epoch header → 401 `authentication_failed`；旧 token → 401 `authentication_failed`；旧 nonce → 403 `stale_reconnect_nonce`；CAS 层旧 epoch（header 为当前、payload 传旧 epoch）→ 403 `stale_connection_epoch`。

在途断线幂等：`recovery_fault_inject.py` 在 HTTP 层对**一次性 disposable 会话**注入“服务端已收到请求后客户端断线”，证实该命令只应用一次、重连后同 command_id 重放返回同一 message_id（幂等）、改输入返回 `command_id_conflict`、旧凭据重试 fail-closed（401）。

**诚实说明**：真实的 `session.reconnect`、epoch 轮转（2→3）、重连后业务命令、旧凭据拒绝都在真实 bridge 会话上完成；而“字面意义的在途断线”是在 HTTP 层用一次性会话注入的，因为无法对真实 `codex.exe` 进程做确定性的请求中途强杀。二者共同构成该能力的完整证据，但两者来源已分别标注，未把一次性 HTTP 会话的行为冒充真实宿主断线。

## 补证审计与证据来源

验收方只读解析保留的 Codex rollout 元数据，没有重新启动服务、创建会话或增加模型调用；未读取用户配置或认证文件，也未把原始 thread ID、转录或私有路径写入证据。可独立核验的事件是：main 的 `compacted`（2026-09-20 12:04:14.833 UTC，同一 digest，替换历史 7 项）；fork 的 `session_meta.forked_from_id` 指向 main（12:13:55.050 UTC，ordinal 115）；new 的 `session_meta` 无父级（12:23:06.648 UTC）；worker 在 cc 报告的重连之后完成 `context.project_read` 工具调用及无错误返回（12:49:47.259–12:49:47.442 UTC），该轮 12:49:54.305 UTC 完成。四份 rollout 的 SHA-256 和全部 digest 见[审计 JSON](../research/evidence/codex-2026-09-20-final-two-audit.json)。这些时间来自宿主事件本身，不是日志文件时间。

cc 报告的 epoch 1→2→3、HTTP 200/401/403、故障脚本退出码 0 与 CLI 退出码 0 没有保留原始 run 可供此次独立重算；它们在审计 JSON 中明确标为 **协同方脱敏报告**。宿主 rollout 的 `task_complete` 能证实对应轮次完成，不能替代进程退出码。fork/new rollout 未出现 Tsunagou 工具调用，因此本次补证证明的是原生身份生命周期，不声称子会话另行完成 bridge 入会。

按共同基线的能力级口径，真实 bridge 重连与旧凭据拒绝加上独立 HTTP 在途故障注入可组合支持 `recovery.idempotent_reconnect`；[首次真实验收执行单](first-live-acceptance.md)所列“同一条真实 bridge 请求到达服务端后断开”仍未直接观察。这个更严格的故障场景保留为 T18 后续加强项，不计作本轮已实测。

## 最终基线

| 能力 | 正式状态 |
|---|---|
| identity.session_isolation | supported |
| identity.continuity_evidence | supported |
| context.project_read | supported |
| command.typed_tools | supported |
| task.lifecycle | supported |
| cognition.report | supported |
| contract.participation | supported |
| inbox.pull_fetch_ack | supported |
| response.structured | supported |
| recovery.idempotent_reconnect | supported |
| delivery.deduplicate | supported |

**按上述组合证据口径：11/11 supported，`formal_baseline_ready: true`。** 最新 JSON 的 11 行现均带非空 `evidence_refs`，仓库 `require_baseline` 对其返回 `true`。这只是 Codex 单宿主能力基线的结构与现有证据判定；严格的同会话在途故障场景、T18 全部工作以及三宿主发布门禁没有因此关闭。运行时 `ready` 与四项会话准入仍只是准入判定，不等于其余七项；本轮与[前轮](../research/evidence/codex-2026-09-20T1628-fivecaps-live.json)各真实业务 turn 的记录共同支撑上面 11 项。OpenCode、DeepSeek Harness 和发布门禁没有变化。
