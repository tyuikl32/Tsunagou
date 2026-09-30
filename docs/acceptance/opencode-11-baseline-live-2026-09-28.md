# OpenCode 11 项共同基线真实验收（2026-09-28）

本轮在真实 OpenCode 宿主（v2.0.18）上完成 11 项共同基线实测：两个真实会话由模型轮次驱动、经 stdio MCP bridge 访问真实 daemon（临时 Git 协调项目）。结构化脱敏结果见 [evidence](../research/evidence/opencode-2026-09-28-live.json)。没有 commit、push 或 release；未放宽身份、owner、scope 或用户专属权限边界。

## 版本与隔离

- 分支 `elysia`，运行基线 `a3954ae20961583be9171be1f9f441af6177a126`；本轮 bridge 修复与文档已提交为 `adda6f5d83e0b483c07397daba78c0a7109d4779`（"opencode11test"），随后与 main 的 PT 系列工作合并为 `cca5618`。合并后的 bridge 已重建并通过凭据交接测试 18/18 与 late-ticket 冒烟（两种模式退出码 0）；本报告的 11 项结论对应运行基线加本轮修复的代码。
- OpenCode `2.0.18`（`opencode --version`）；`opencode serve` 没有旧文档中的 `--pure` 参数，实际参数为 `--hostname/--port/--cors/--serve/--stdio`。
- Node bridge `/packages/bridge-server/dist/server.js`（`tsc` 退出码 0）；daemon `127.0.0.1:8765`。
- 两个真实会话：main 会话 `session:A`（本会话）、worker 会话 `session:B`；fork 会话 `session:C`。会话标识以 SHA-256 前缀脱敏存档。
- 双 profile（`tsunagou-main` / `tsunagou-worker`）生成独立的 ticket、bridge 配置与私有 session 文件；bridge 按 `_meta["ai.opencode/sessionID"]` 为每个会话分配独立私有 session 文件。
- 第三轮（身份修复与漏测补测，工作树运行头 `6b65938`）：bridge 新增 `TSUNAGOU_HOST_META_KEY` 严格契约并由 `agent connect` 自动声明；补测同类 worker 的操作所有权、双协调项目隔离、MCP/REST 一致性、接收侧投递去重与 fork 隔离。结构化结果见 [gap-tests evidence](../research/evidence/opencode-2026-09-28-gap-tests.json)。

## 11 项结果

| # | capability | 结果 | 关键证据 |
|---|---|---:|---|
| 1 | identity.session_isolation | supported | 两个会话产生不同 Agent（`5a80e67e…` vs `7d4b0386…`）、26 vs 15 能力集、独立 session 文件；worker 调 main-only 工具 `capability_denied`；同会话二次 attach 被 `conversation_already_attached` 拒绝；第三轮：同类 worker 互相 preflight 对方 attempt 均 `attempt_owner_required`，fork 会话不继承源身份（`not_enrolled`） |
| 2 | identity.continuity_evidence | supported | resume/reconnect/compact 保持身份；compact 经真实 TUI `/compact` 实测（摘要消息 2026-09-28T13:04:49Z 落地，OpenCode 会话 id 与 Tsunagou agent/项目均不变）；新会话与 fork（`session:C`）产生新会话 id；`/clear` 经官方别名 `/new` 等价覆盖；另补充首调用身份硬校验 |
| 3 | context.project_read | supported | 两会话读取同一 `project_id` 与各自身份；调用无投影注入面，绑定由服务端决定 |
| 4 | command.typed_tools | supported | `tools/list` 53 个带 schema 的工具；调用者身份来自服务端凭据；main-only 操作对 worker `capability_denied` |
| 5 | task.lifecycle | supported | create→ready→publish→claim→workspace.select/prepare→resource.intent/acquire→preflight→start→progress→block→resume→再 acquire→preflight→start→submit；旧 revision `task_revision_conflict` |
| 6 | cognition.report | supported | worker/main 报告 + 分歧创建/解决；worker 越权 resolve 被拒 |
| 7 | contract.participation | supported | 正确 digest `accepted`；stale digest `proposal_digest_mismatch`；槽位绑定错配 `participant_slot_denied` |
| 8 | inbox.pull_fetch_ack | supported | claim/fetch/presented/ack 四步分离；非收件人 fetch `inbox_access_denied`；重复投递不产生第二份；第三轮接收侧去重：30 秒租约内二次 claim `count 0`、重复 fetch 义务恒 1、ack 后不再投递、重复 ack 幂等（不依赖 sender 端 command_id 幂等） |
| 9 | response.structured | supported | 义务生成；ACK 后仍 `open`（不冒充响应）；带 `in_reply_to` 的响应消息经 respond 结清；未链接响应被拒 |
| 10 | recovery.idempotent_reconnect | supported | 杀 bridge 进程后宿主重连：身份不变、epoch 1→2；旧 epoch 头 401 `authentication_failed`，当前 epoch 200 |
| 11 | delivery.deduplicate | supported | 同 `command_id` 重放返回同一 message id；改 payload `idempotency_conflict`；收件箱无重复 |

## 运行命令（摘要）

```powershell
# daemon + 临时协调项目
tsunagou daemon start --coordination-root <temp-git-project> --port 8765
# 为真实会话签发 ticket（会话 id 由宿主提供）
$env:TSUNAGOU_HOST_CONVERSATION_ID = "session:A"
tsunagou agent connect --adapter opencode --role main --profile tsunagou-main --no-register-host
tsunagou agent connect --adapter opencode --role worker --profile tsunagou-worker --no-register-host
# 真实宿主轮次驱动 MCP 工具（示例）
opencode run --session session:B --format json "<tool instructions>"
# 宿主重连（模拟重启后）
opencode reload
# 旧/新 epoch 对照（脱敏脚本）
python epoch-test.py <bridge-session.json> 1 2   # stale -> 401, current -> 200
```

所有 `tsunagou`/`opencode`/`node` 验收命令退出码为 0；负例命令由 daemon 返回结构化 `tsunagou_error:*` 并以工具错误呈现（预期行为）。

## 第一轮修复的产品代码（已提交为 `adda6f5`）

`packages/bridge-server/src/server.ts`：

1. 从 MCP 工具调用 `_meta["ai.opencode/sessionID"]` 提取宿主会话身份（OpenCode 不提供会话环境变量），digest 前缀与 ticket 路径统一为 `conversation_id:`，保证同一会话跨调用身份一致。
2. 多会话宿主下按会话分配私有 session 文件（`<stateDir>/sessions/bridge-session-<digest>.json`），单会话宿主仍使用 `TSUNAGOU_SESSION_FILE`。

## 合并后树复测（同日）

在 main 的 PT1–PT7 工作与本轮修复合并（`cca5618`）后，环境被完整重建（清除旧 daemon 状态、重新签发 ticket、两个会话重新 enroll），11 项在同一真实宿主上复测通过；运行头 `ffe0bbe`。关键新增观察：

- 合并后的 `workspace.prepare` 契约要求显式 `input_digest` 与 `root_binding_refs`，并自动解析任务 scope roots（worker 按新必填字段调用成功）。
- 重连后 main epoch 6 / worker epoch 5（多次重连累计），agent 不变；旧 epoch 头 401 `authentication_failed`，当前 epoch 200。
- task.lifecycle 完整闭环复测：claim→workspace.select/prepare→resource.intent/acquire→preflight→start→progress→block→resume→再 acquire→preflight→start→submit，旧 revision `task_revision_conflict`。

复测证据见 [merged-tree retest evidence](../research/evidence/opencode-2026-09-28-retest-merged-tree.json)。

## 第三轮：身份修复与漏测补测（同日）

**1) 身份缺陷修复。** 修复合并后 `conversationState` 的借用窗口：当宿主未声明 metadata 契约时，首次缺少有效 `ai.opencode/sessionID` 的调用会回落到启动恢复的 defaultState（可能借用 main 身份）。修复内容：

- `agent connect` 为 opencode 适配器在 bridge 配置中写入 `TSUNAGOU_HOST_META_KEY=ai.opencode/sessionID`（真实链路已验证生成）。
- bridge 读取该声明后进入严格模式：**每次**调用的 `_meta` 会话 id 缺失、空串或非字符串都立即拒绝（`conversation_metadata_required`），不再选择任何会话状态；声明缺失时保持其他宿主的合法接入方式（Codex 环境变量身份、显式 TSUNAGOU_SESSION_FILE）不变。
- 回归测试：`node --test scripts/test-credential-handoff.mjs` **19/19 通过**，新增用例 "host-metadata bridge rejects a first call without valid metadata" 覆盖首次调用即无效的四类输入（缺失、空、number、object），并断言未发生 enroll、未改写已恢复凭据、有效 metadata 仍能解析原凭据；late-ticket 冒烟两种模式退出码 0。
- 真实链路回归：修复后四个 bridge（main/worker/worker2/p2）均通过真实模型轮次完成 `context__project_read` 等调用（session:A–D 各自身份正确）。

**2) 补测场景与断言。**

| 场景 | 步骤 | 断言结果 |
|---|---|---|
| 同类 Agent 所有权 | worker 对 worker2 的 attempt 调 `task.preflight`；反向再来一次 | 双向均为 `tsunagou_error:attempt_owner_required`（400）；另有执行授权层 `capability_denied` |
| 双协调项目隔离 | 第二临时 Git 项目 + 第二 daemon（端口 8766）；session:D 入会项目二 | 项目一 `8a22157f-…`、项目二 `61f74f79-…`；项目二任务数 0；session:D 调项目一 worker 桥 `not_enrolled` |
| MCP/REST 语义 | REST 直发 `inbox.fetch`（越权）与 `message.send`；再用 MCP `inbox__claim` 验证 | REST 403 `inbox_access_denied` 与 MCP 错误码一致；REST 发送的消息 `8d876f86…` 被 MCP 侧读到；`workspace.*` schema 两表面同源 |
| 接收侧去重 | claim → 立即再 claim；重复 fetch；presented → ack → 重复 ack；再 claim | 二次 claim `count 0`（租约抑制）；重复 fetch 义务恒 1；重复 ack 幂等；ack 后不再投递 |
| fork 隔离 | fork 会话先调 worker 桥；再对 fork 签发独立 ticket | 未入会时 `not_enrolled`（不继承源身份）；入会后产生独立 worker agent（`73ca378f…`） |
| compact 身份保持 | 用户在真实 TUI 对 session:B 执行 `/compact`；执行前记录基线 agent/epoch=14；执行后导出会话并调用 MCP | 摘要消息 `msg_0e81e365…` 创建于 2026-09-28T13:04:49Z（操作时刻）；OpenCode 会话 id `ses_f185609c…` 不变；compact 后 `context__project_read` 返回同一 agent `6ce88823…` 与项目 `8a22157f…`（epoch 14→15 仅为期间重连轮转，身份不受影响） |

**3) 观察项（记录，未改代码）。**

- 命令目录表 `message.send` 行的 `kind:notification\|request` 未转义 `|`，导致生成的 registry/schema 只含 `kind`（表格列分隔符吞掉了后半行）。属 PT 协议表/生成器缺陷，改动会变更 schema bundle digest，第三轮仅记录；**第四轮已修复**（生成器支持 `\|` 转义 + catalog 行按真实契约修正，digest 正常更新，见下）。
- 实现中 ACK 与 presentation 是独立事实（单测 `test_ack_does_not_claim_presentation…` 明确固定该语义），与 spec 中 "ACK requires a successful presentation record" 的措辞存在差异；本轮未改动任一侧，如实记录。

## 第四轮：配置路径对齐、message.send 契约与租约重投递（同日）

**1) `agent connect` / `agent enroll` 配置路径对齐。** 两条路径现在共用同一 `_bridge_environment` 生成器：`agent enroll --adapter opencode` 同样声明 `TSUNAGOU_HOST_META_KEY=ai.opencode/sessionID`，并且 bridge 文件名清洗一致。回归：

- 单测 `test_bridge_environment_declares_per_call_host_metadata`（pytest exit 0）：opencode 声明该键、codex 不声明。
- 真实 `agent enroll`（临时 installation/conversation，exit 0）生成的配置含声明；驱动脚本用该生成配置启动 bridge：无 `_meta` → `conversation_metadata_required`、错误类型 → 同、票据绑定的有效会话 id → 接入成功（agent `05e3e509…`；driver exit 0）。
- `agent connect` 重构后复测：生成配置仍含声明。
- 旧配置刷新/重载说明已写入 [adapter-opencode.md](../implementation/adapter-opencode.md)：重跑 connect/enroll 生成配置 → 将 `env`（至少 `TSUNAGOU_HOST_META_KEY`）同步进 OpenCode 项目 `mcp.<name>.environment` → 重载/重启宿主进程使其生效。

**2) `message.send` 公开契约修复。** 根因：catalog 单元格的 Markdown 转义 `\|` 未被生成器识别，payload 单元格被拆列，registry/schema 只剩 `kind`。修复生成器的单元格解析（保护 `\|`），并按真实实现修正 catalog 行（`recipient_agent_id,summary,kind?,subject_ref?,payload?,priority?,response_contract?,in_reply_to?`；移除从未实现的 `recipient_ids`/`artifact_refs`）。同一缺陷另外截断的 9 行（agent.ticket.create、agent.ticket.create.user、artifact.upload.create、discrepancy.advance、discrepancy.resolve、project.lineage.reset、project.replica.activate、task.recover、task.scope.resolve）一并恢复完整字段。

- `message/send.schema.json` 重建为 8 字段、`required=[recipient_agent_id,summary]`、`additionalProperties=false`；bridge MCP 工具 `message__send` 的 required 同步为 `[recipient_agent_id,summary]`；registry、`protocol_data`、bridge 包三份副本一致；digest 由 `sha256:99326365…` 更新为 `sha256:51c31820…`。
- jsonschema（Draft 2020-12）8/8：全字段与最小必填通过；缺 recipient_agent_id、缺 summary、priority/payload 类型错误、未知字段、空 recipient 均被拒（exit 0）。
- 真实宿主轮次（隔离环境：新协调项目 `ee245168…` + daemon 8767 + `opencode --standalone` v2.0.18 新会话）：有效 `message__send` 成功（message `d0ca252e…`）；缺 `summary` 被 MCP 客户端参数校验拒绝（原文 `summary: Missing key`）；缺 `recipient_agent_id` 同样被拒（`recipient_agent_id: Missing key`）。
- 说明：8765/8766 的既有 daemon 与长期存活的宿主 bridge 仍运行旧 digest（本轮未重启，避免打断正在使用的宿主服务）；新 digest 的端到端验证在全新隔离实例完成。

**3) 接收侧去重：租约到期重投递与乱序（真实宿主 session:B）。**

| 步骤 | 观察 |
|---|---|
| main 发送 M（request + obligation 必填）与 N | M `cf48b08f…`、N `f2c6c903…`，同一收件人 |
| worker claim#1 | 投递顺序 `[8e5c6fc2…（遗留）, 8d876f86…（遗留）, M, N]`（按发送时间）；两条遗留消息属前置清理对象 |
| 乱序 ack | 先 ack 两条遗留消息，再 ack N（先于 M）；M 保持未 ack |
| 业务动作（1 次） | 唯一一次 `inbox__fetch` 读取 M → 发送响应 `cc92fc12…` → `message__respond`（`61b57219…` → responded）→ `inbox__presented` |
| 租约到期重投递 | 30 秒租约过期后 claim#2 仅返回 M；obligation 状态仍为 `responded`（未重开、无新义务） |
| 重复投递处理 | 不重复 fetch；重复 `message__respond` 被拒 `tsunagou_error:obligation_already_closed`；随后 ack M 成功 |
| 最终状态 | claim#3 `count 0`（空收件箱） |
| 机械化计数（会话导出） | `inbox__fetch`(M)=1；含 M 的 claim 结果=2（重投递通知）；respond 接受=1、重复被拒=1；M 标记出现于 3 个工具结果（claim×2+fetch×1）；仅存于 payload 的标记命中 0（当时 fetch 视图不含 payload；第五轮已修复并复测，见下） |

判定依据是上述 fetch/动作计数与最终状态，而不是 response obligation 数量不变。

**4) 本轮验证命令与结果。** bridge `tsc --noEmit` exit 0；`test-credential-handoff.mjs` 19/19；vitest bridge-sdk+adapter-opencode 17/17；`validate_protocol.py` exit 0（111 命令 / 126 schema）；`pytest tests/protocol tests/unit` 仅剩两个既有失败（`test_audit_contract` 生成物陈旧、`test_checkpoints` master/main 环境依赖，均与本轮改动无关且未修改相关文件）；`validate_docs.py` PASS。

**5) 观察项更新。** 第三轮记录的 catalog 转义缺陷已由本轮修复（见 2），不再保留“仅记录”的结论；ACK/presentation 独立性的措辞差异保持不变。

## 第五轮：inbox.fetch payload 与 9 条命令 Schema 同步（同日）

**1) `inbox.fetch` 返回 payload（仅限授权收件人）。**

- 修复：`inbox.fetch` 在收件人授权检查通过后返回完整 `payload`；`inbox.claim` 继续使用仅元数据的 `_message_view`，批量列举不会携带正文；非收件人 fetch 仍在读取 payload 之前被拒（`inbox_access_denied`）。MCP 工具描述同步为 "including its payload"。
- 回归：新增单测 `test_inbox_fetch_returns_payload_only_to_the_recipient`（claim 无 payload 键；fetch 返回 `{marker: TG-BODY-UNIT}`；非收件人 403 `inbox_access_denied`）；`tests/unit` 通过。
- 真实宿主复测（session:B，standalone OpenCode v2.0.18；daemon 8765 已重启到本轮代码/digest `cc3d9b54…`；main 侧经真实 bridge 以 `4cff3b4e…` 身份发送）：
  - M `06bc19df…`（kind request、obligation `8e951114…`；标记 `TG-BODY-9c4e21a7` 仅存在于 payload）、N `50f5acb6…`。
  - claim#1 `[M, N]`，claim 视图无 payload；唯一一次 fetch M 返回完整 payload；respond 一次成功（响应 `a2159e98…`）；presented；N 先于 M 乱序 ack。
  - 30s 租约到期后 claim#2 仅 `[M]`（obligation 保持 responded、未重开）；未重复 fetch；重复 respond 被拒 `obligation_already_closed`；ack M；claim#3 `count 0`。
  - 会话导出机械计数（仅统计到达 bridge 的调用；排除 6 次宿主目录未就绪的 "Unknown tool" 重试）：fetch(M) 正文结果=1；正文标记出现的工具结果=1（重投递后不增加）；payload step 标记=1；含 M 视图的 claim 结果=2；含正文标记的 claim 结果=0；respond 接受=1、重复被拒=1。
  - 命令与退出码：main 侧 bridge 驱动（`node main-send-rerun.mjs …`）exit 0 并返回 M/N 消息 id；session:B 的每个 standalone 轮次均完成并返回上述工具结果（首调用 Unknown tool 由宿主在轮次内重试，未到达 bridge）。
  - 旧判定口径"正文标记出现 0 次"作废。

**2) 9 条受影响命令的 Schema 同步。**

- 依据实际处理器与 runtime `PAYLOAD_FIELDS` 修正 5 条 catalog 行：`agent.ticket.create.user`（installation_id,conversation_evidence 必填；kind/role/ttl_seconds 可选）、`task.recover`（task_id,expected_attempt_id,disposition 必填；reason 可选）、`task.scope.resolve`（scope_request_id,choice 必填；approved_scope/reason 可选）、`discrepancy.advance`（discrepancy_id,status 必填）、`discrepancy.resolve`（discrepancy_id,kind 必填；其余可选）。原行中不可实现的字段（如 adapter_allowlist/ceiling_template/proposal_digest/residual_risk_refs——runtime 会以 `unknown_payload_field` 拒绝）按实际实现修正。
- 其余 4 条没有 Python 处理器或 runtime 允许清单（agent.ticket.create、artifact.upload.create、project.lineage.reset、project.replica.activate），保留 catalog 已确认契约。
- 9 条旧 Schema 删除后由 `generate_protocol.py` 重新脚手架生成（不手改生成物）；registry、protocol_data、bridge 包副本一致；digest 由 `51c31820…` 更新为 `cc3d9b54…`。
- 验证：契约检查脚本 24/24（正常参数通过、缺任一必填被拒、registry 与 Schema 字段/必填一致）；`validate_protocol.py` exit 0（111 命令 / 126 schema）；`tests/integration/test_m1_runtime_flow.py` + `tests/integration/test_clone_recovery.py` 7/7 通过。

**3) 环境与观察。**

- daemon 8765 重启后持久凭据恢复（main `4cff3b4e…`、worker `6ce88823…`；epoch 正常轮转）；8766 与服务后台长期存活的 bridge 仍为旧 digest，待宿主重启。
- 观察（未改代码）：4 个陈旧 `bridge-session.json.pending.json`（旧 digest 的 `session.reconnect` 信封）会让 bridge 恢复持续报 `credential_command_failed:schema_bundle_digest_mismatch`，直到删除该日志；本轮作为环境修复清除（main/worker/worker2/p2）。standalone 每次启动的首个工具调用可能命中宿主目录未就绪（Unknown tool）后重试成功，不影响协议计数。

**4) 本轮验证命令与结果。** `tsc --noEmit` exit 0；`test-credential-handoff.mjs` 19/19；vitest bridge-sdk+adapter-opencode 17/17；`pytest tests/protocol tests/unit` 仅剩两个既有失败（`test_audit_contract` 生成物陈旧、`test_checkpoints` master/main 环境依赖）；`validate_docs.py` PASS。

## 诚实说明

- `compact`：已通过真实 TUI `/compact`（该版本唯一受支持入口，别名 `/summarize`）完成一次实测：摘要消息落地于 2026-09-28T13:04:49Z，OpenCode 会话 id 与 Tsunagou agent/项目均不变。headless 触发仍不可用（CLI 无 compact 子命令、`opencode run "/compact"` 为普通文本、REST summarize 路径 405/404、npm SDK 1.18.33 低于服务端 v2）；后续如需复核 compact，需再次用户在 TUI 执行后由 MCP 侧核验身份，操作与断言步骤见 [gap-tests evidence](../research/evidence/opencode-2026-09-28-gap-tests.json) 的 `continuity.compact`。
- `clear`：官方文档将其定义为 `/new` 的别名（新建会话）；其身份行为由 new/fork 实测等价覆盖，未以字面 `/clear` 命令另行执行。
- 跨项目对照已在第三轮完成（第二协调项目 + 第二 daemon；双向 `not_enrolled` 拒绝，见 gap-tests evidence）。
- schema bundle digest 已随两轮契约修复更新（当前 `cc3d9b54…`）。第五轮已把 daemon 8765 重启到新代码/digest 并完成真实宿主复测；8766 与服务后台长期存活的宿主 bridge 仍为更早的 digest，需要重启宿主/服务后才能采用。
- 自动唤醒（`wake.push`）是增强项，本轮 bridge 报告 `unsupported`（stdio 无宿主反向唤醒通道），不计入 11 项。
- 原始会话标识、token、ticket 与私有 session body 只进入私有运行目录；仓库仅保留 digest 前缀与脱敏引用。
