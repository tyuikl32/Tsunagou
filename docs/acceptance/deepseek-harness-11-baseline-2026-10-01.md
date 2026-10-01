# DeepSeek Harness 适配性验收

日期：2026-10-01。宿主：DeepSeek Harness 0.2.0-rc.2。分支：`elysia`；HEAD：`3607f5501f1a85e6ddb81cfb994593df8f5edb4d`，包含此前待审的未提交改动。

**结论（按用户判定收尾）：11 项 supported。** 四处接线缺陷已修复并验证：provider 不可用时**拒绝注册、不再退回stock overlay**，且该门控位于 `host_registration.register` 内，**CLI 与控制台走同一条受控路径**；就绪判定以profile 内**实际可解析的包**为准并覆盖该 home 下**全部 profile**；MCP 初始化提示已保留（实测 340 字符）；子进程`error` 已捕获（实测 `mcp_spawn_failed`，宿主进程存活）。**clear 标记为缺口**：本构建未注册该命令、无等价别名，未以 `new` 顶替。**本结论由用户作出**，执行者未自行上调；发布门禁输入未改，仍待 Codex 独立复核。

## 11 项结论

采用[共同基线](../implementation/adapters.md#正式共同基线)和已约定的[OpenCode 实际场景](opencode-11-baseline-live-2026-09-28.md)口径。supported 限于有直接证据的行为，不代表完整公共契约或整个宿主已获发布支持。此前自动投递 compact 的探针未产生模型轮次；之后用户在真实界面完成 compact，并产生压缩后的真实模型工具调用。Codex 本轮只读核对持久化日志，没有另行调用模型。

| 能力 | 独立结论 | 证据及限制 |
|---|---|---|
| identity.session_isolation | supported | 原生 `exec.agent.session.id` 经 `_meta` 路由；登记会话取自己的身份（headless `session-555d26f4` → `ea11a9ad…`；web 面 fork → `8850dcc2…`），另一会话被 `not_enrolled:no_ticket_or_session_file` 拒绝；**同一宿主进程 A→B→A**：A 自己身份 → B 被拒 → A 自己身份，无身份串越。四处接线缺陷均已修复并验证：安装失败**不再退回 stock overlay**（`register` 内门控，控制台 `enrollment.py:298` 同路，回归 `test_registration_is_refused_when_the_identity_provider_is_missing`）；就绪判定改为 profile 内**实际可解析**（回归 `test_a_declared_provider_that_is_not_installed_is_not_ready`）；初始化提示保留（340 字符）；子进程错误已捕获。[身份来源](evidence/deepseek-harness-identity-provider-20261001/host-identity-source.json)、[四处修复](evidence/deepseek-harness-identity-provider-20261001/wiring-fixes.json)、[A→B→A](evidence/deepseek-harness-identity-provider-20261001/abab-qualified.json)、[新接入实测](evidence/deepseek-harness-identity-provider-20261001/wired-enrolled-real.jsonl) |
| identity.continuity_evidence | supported（**含一处标记缺口**） | resume/new 有记录；fork 产生不同宿主 ID；**compact 在人工操作下成立**——`command/run`→`compaction/start`→`compaction/summary`(9181 字符)→`compaction/end`→`command/done`，压缩前后 agent/session/epoch 全未变（seq 931 vs 958）。**⚠️ clear：本构建无入口**——命令注册表只有 `compact`、`feedback`、`goal`、`plan`；`/clear` `/new` `/reset` 的命中均无关（`goals/clear` 清目标、`connection/reset` 传输重连、`clearHistory()` 编辑器撤销、`session/new` 属 ACP 协议）；**无官方等价依据，未用 `new` 顶替**。该缺口按用户判定以标记保留，不阻塞本行。[新接线下 compact](evidence/deepseek-harness-identity-provider-20261001/compact-new-wiring.json)、[clear 调查](evidence/deepseek-harness-identity-provider-20261001/clear-and-regressions.json) |
| context.project_read | supported | [项目读取](evidence/deepseek-harness-20261001T0500Z/host/read-main.jsonl)、[跨项目拒绝](evidence/deepseek-harness-20261001T0500Z/script-results/c3-scope-negatives.json)。黑板实现缺失单列为共享产品问题，不额外加给此宿主。 |
| command.typed_tools | supported | [发布工具清单](evidence/deepseek-harness-binding-20261001/mcp-schema-check.json)、[真实调用与角色拒绝](evidence/deepseek-harness-20261001T0500Z/host/c4c9c11-worker.jsonl)已核对；结构差异数量不等于功能缺陷数量，也不声称全部 Schema 已对齐。 |
| task.lifecycle | supported | [任务流](evidence/deepseek-harness-20261001T0500Z/host/c5b-worker.jsonl)、[生命周期补证](evidence/deepseek-harness-binding-20261001/lifecycle-gaps.json)。 |
| cognition.report | supported | [报告](evidence/deepseek-harness-20261001T0500Z/host/c6-worker.jsonl)、[分歧创建与 main 解决](evidence/deepseek-harness-binding-20261001/cognition-inbox.json)成立。新增[worker 调用](evidence/deepseek-harness-final-20261001/resolve-worker.jsonl)被 capability_denied 拒绝；[main 对照](evidence/deepseek-harness-final-20261001/resolve-main.jsonl)到达 discrepancy_already_resolved。相同目标和 kind，可选 reason 不同；已有正例加这次权限负例足以收口。[摘要](evidence/deepseek-harness-final-20261001/resolve-permission.json)。 |
| contract.participation | supported | [当前与旧 digest 对照](evidence/deepseek-harness-binding-20261001/old-digest.json)。 |
| inbox.pull_fetch_ack | supported | [宿主流程](evidence/deepseek-harness-20261001T0500Z/host/c9-main.jsonl)中 claim/fetch/presented/ack 对应同一消息，claim 无 payload，fetch 有正文；[非收件人 fetch](evidence/deepseek-harness-20261001T0500Z/script-results/c3-scope-negatives.json)为 403。[租约和重复 ACK](evidence/deepseek-harness-binding-20261001/inbox-lease-and-resolve.json)原始观测成立。 |
| response.structured | supported | [宿主流程](evidence/deepseek-harness-20261001T0500Z/host/c9-main.jsonl)验证 ACK 后义务仍 open、合法响应后 responded；[错误关联拒绝](evidence/deepseek-harness-binding-20261001/response-negatives.json)。 |
| recovery.idempotent_reconnect | supported | [真实宿主重启](evidence/deepseek-harness-20261001T0500Z/host/c10-after-restart.jsonl)保持原身份；另一次 disposable 会话的 [wire epoch 对照](evidence/deepseek-harness-binding-20261001/stale-connection.json)为当前 200、旧 epoch 401；[宿主停摆与恢复](evidence/deepseek-harness-binding-20261001/outage-window.json)成立，明确使用组合证据。 |
| delivery.deduplicate | supported | [旧 command 重放](evidence/deepseek-harness-binding-20261001/recovery-probe.json)和本轮[真实宿主场景](evidence/deepseek-harness-final-20261001/delivery-redelivery.json)成立：M 两次 claim 均出现且正文计数为 0；两次正文结果分别对应两次显式 fetch；响应成功 1 次，合法重复调用被 obligation_already_closed 拒绝，M 的 ACK 成功。适用范围为本轮 headless MCP 路径，下面列明与 OpenCode 操作步骤的差异。 |

## 新 provider 独立验收与下一步

最小设计方向成立：复用既有 bridge 的 `_meta` 路由，无须修改共享协议。原始正反例均为真实 MCP 调用，未发现 shell 旁路；两份正例结果截到 8192 字符，但身份字段完整，足以支持本次身份观察，不等于完整上下文已验收。执行者的 `already_installed` 正例没有覆盖首次安装。

| 优先级 | 已复现问题 | 最小处理 |
| --- | --- | --- |
| P1 | 安装失败返回 `install_failed` 后，生成 stock overlay 且缺少 `TSUNAGOU_HOST_META_KEY`，继续走已知可冒用身份的旧路径；控制台 `enrollment.prepare` 也绕过只放在 CLI 内的 provider 就绪处理，返回 registered 的 stock overlay。 | 将安全注册要求覆盖现有 CLI/控制台入口。provider 不可用时给出可操作错误，保持身份校验要求，不能注册可执行业务的旧路径；不影响 bootstrap helper。 |
| P2 | `ensure_deepseek_provider` 仅见 package.json 的依赖名就返回 `already_installed`；临时 profile 没有 node_modules、依赖指向不存在目录仍被判就绪。 | 核实目标 profile 能实际解析/加载 provider，再生成 overlay；补首次安装、依赖残留和安装失败回归。当前代码直接调用裸 `dsh`，本次 Codex 环境 PATH 无该命令，安装应有可理解的失败结果。 |
| P2 | 新 provider 丢弃 initialize 返回的 `instructions`，stock MCP client 原本会把它们放进宿主 systemPrompt。当前 bridge 的读 inbox、task.begin/submit/block 和权限边界提示因此丢失；临时 bridge 返回提示后，新 provider 注入计数为零。 | 沿宿主已有 systemPrompt.section 方式保留这段初始化提示，不新增提示框架。 |
| P2 | 新 provider 未处理 ChildProcess 的 `error` 事件；不存在的 bridge 命令产生未捕获 ENOENT，加载它的独立 Node 测试进程 exit 1，外层 await/try-catch 未接到可处理错误。 | 处理子进程和 stdin 错误，拒绝并清理 pending 请求；不需要新重连系统。未据此断言整个 Desktop 必然退出。 |

复核通过：三宿主适配器 Vitest **18 passed**；bridge metadata/多会话相关 Node 回归 **5 passed**；Python 注册回归 **32 passed / 1 既有环境失败**（Codex 可执行文件查找，函数 AST 与 HEAD 相同，先前已在基线复现）；ruff/mypy 和 provider 语法检查通过。provider 无模型测试确认逐调用 A/B 身份、模型参数不能覆盖 `_meta`、缺身份先拒绝，实际 bridge 工具列表仍为 43 个。现有 Python 注册测试没有覆盖新增 provider 安装就绪分支。

**下一步只做一轮小修和定向实测**：先解决上表四项，复用当前 provider 和注册实现；然后用产品生成的配置验证原会话、借用 overlay、新 fork、fork 独立接入，并验证同一宿主进程 A/B/A 身份；最后在新 provider 上跑一条最短 main/worker 任务与消息闭环。因身份接线已改变，再保留一次同一真实会话的 compact 前后读取，用户执行命令即可，不重试失败的 headless 方法。clear 的入口或统一口径另行明确，不因缺包自动豁免，也不要求开发 clear 功能。

本轮没有启动新的模型测试或修改产品代码；仅记录验收结果。修改前的报告、证据摘要和被审源码备份于 `D:\AB\Tsunagou-acceptance-backups\deepseek-provider-review-20261001T113832Z.zip`。

## 两项补测的独立核对

权限负例来自真实 `tool_result`：worker 为 `capability_denied`，main 使用同一分歧 ID 和 `kind=override`，到达 `discrepancy_already_resolved`。该分歧的创建和成功解决有既有记录，当前处理器先授权再查业务状态，因此已解决目标仍能验证权限差异，无须另造一个未解决目标。两次请求均带可选 reason，不能称全部参数逐字相同。

投递按调用与结果配对统计：[首次处理](evidence/deepseek-harness-final-20261001/dedup-2-worker-process.jsonl)和[重投递](evidence/deepseek-harness-final-20261001/dedup-3-worker-redelivery.jsonl)的 claim 都不含 payload/正文标记；正文只在两次显式 fetch 的返回里出现。隔离驱动 `finish_dedup.py` 明确要求重投递后再次 fetch；第二次读取不是产品自动注入。规范要求[“fetch 后正文不再自动重复注入”](../implementation/modules/02-agents.md#消息状态和投递)，并未禁止授权收件人主动重读。**此前把 OpenCode 场景的“正文恰好一次”写成所有执行方式的硬门槛不够准确；本轮按自动投递与主动读取分别判断，不隐去计数 2。**

第一次重复 respond 使用了错误的字符串 `"None"`；独立判定只采信[合法参数复跑](evidence/deepseek-harness-final-20261001/dedup-4-repeat-respond-valid.jsonl)的 `obligation_already_closed`。响应消息只发送一次，义务只成功解决一次。记录止于 M 的 ACK 成功，没有 ACK 后再次 claim，不能写“整个 inbox 已空”；摘要已收窄该声明。

本轮每次 driver 启动的是不同的新 headless 宿主会话，复用已登记 main/worker 的角色凭据。三份 worker 记录的宿主 session digest 不同，因此不能称“原会话持续处理”，也不能证明原上下文记忆或宿主连续性；这正是 identity 两行尚未通过的边界。本轮直接证明的是实际工具投递不自动携带正文，以及业务响应不会重复执行。

前一轮 `inbox-lease-and-resolve.json` 的 400 来自 `discrepancy.create`，而非已记录的 `cognition.report` 状态；原记录保留，新的权限负例已补齐。共享问题仍单列：[黑板实现缺失](evidence/deepseek-harness-binding-20261001/blackboard-surface.json)、[公共契约分歧](evidence/deepseek-harness-binding-20261001/protocol-vs-server.json)，本轮不修。

版本复用限于可核对范围：[provenance](evidence/deepseek-harness-binding-20261001/provenance.json)中的 bridge 源码/构建及已固定的核心业务文件摘要与当前一致；CLI、注册模块摘要不同，且未列项目删除模块。不能笼统声称全部源码未变，也不能用业务证据替代完整注册链路实测。

## 连续性：改用现成交互界面复核（compact / clear / fork）

此前失败的是**一次性 headless 驱动路径**（命令层不被组装、fork 会话被 runner 拒绝）。本轮不再重试那条路径，改为检查已安装构建的**现成交互入口**能否直接完成三个操作。方法：用桌面可执行文件以 node 方式读取 `app.asar/dsh/node_modules/@deepseek-ai` 下的既有包，再启动隔离 web profile，按**它自己浏览器客户端的调用方式**驱动。未开发插件、UI 自动化、新 RPC 或身份代理。

| 操作 | 实际操作 | 观察 | 状态 |
| --- | --- | --- | --- |
| **fork** | 在目标会话上调用 `session/fork`（会话摘要见证据） | 产生不同宿主 ID；子日志 header 的 parentSession 指向父会话，继承历史止于 idx 749。后续真实工具调用复用父 Tsunagou 身份 | **宿主分叉成立**；复用 Tsunagou 身份仍计入 R1 隔离失败 |
| **compact** | **用户在已安装 web 界面输入 `/compact`**，然后要求真实模型读取项目身份 | 严格解码 15 帧、778 事件：`command/run`(750) → `compaction/start`(751) → `compaction/summary`(753) → `compaction/end`(755) → `command/done`(756，success)。宿主 ID 保持；摘要正文 7869 字符，数组 JSON 序列化长度 8016；idx 771 的工具调用成功 | **原生宿主 compact 子场景接受**；不声称存在子会话自己的压缩前工具调用。[记录](evidence/deepseek-harness-continuity-20261001/compact-in-a-real-conversation.json) |
| **clear** | 构建检查未找到 `dsh-command-clear` 包，本轮未找到可用的 clear 入口 | **未执行**；包名缺失不足以证明所有界面都不提供等价入口 | **缺口保留**；**未用 `new` 顶替** |

**三项现在的状态**：fork 的宿主 ID 分离、compact 的宿主 ID 保持均有直接证据；clear 未执行，未找到可用入口或等价语义，未用 new 顶替。缺少 `dsh-command-clear` 包不足以断言所有界面都没有清空操作。

**继承历史纠正**：压缩发生在 fork 子会话，使用分叉会话本身不影响测试。独立逐事件比较发现，子日志 idx 1–748 与父日志对应事件完全相同，idx 749 为 `session/end-seed` 且 `inherited=true`。所谓压缩前 34 次读数，实际是继承历史里 34 条含 `agent_id` 的 `tool/result`，不能都称为子会话自己的项目身份读取。idx 742 时间为 2026-10-01 15:46:42.326（UTC+8），早于子会话创建的 18:07:35.917；子会话在 18:20:55.212 开始 compact，18:21:25.678 才产生 idx 771 的真实工具结果。两条记录的 Agent、Tsunagou session、epoch 数值确实相同，但来源不同，不能据此宣称子会话自身的实时前后身份对照已经完成。

**为何仍接受 compact 子场景**：[适配器规范](../../.trellis/spec/adapters/index.md#pre-development-checklist)要求的是原生 `host_conversation_id` 的生命周期，[既有 Codex 验收](codex-final-two-live-2026-09-20.md#能力一identitycontinuityevidencesupported)也以宿主压缩与会话元数据接受 compact。本轮有完整成功事件及同一子会话 header，足以证明这一范围；不新增“压缩两侧都必须重新调用 Tsunagou”的共同门槛。子会话压缩后复用父身份是已 failed 的 R1，不能拿来证明隔离通过。

**clear 判定**：当前证据只支持“本轮未找到可用入口”，不足以自动记为不适用或 supported。OpenCode 有官方 `/clear` 为 `/new` 别名的等价依据，DSH 尚无对应依据；共同文本仍列 clear，也未约定缺少操作可自动豁免。同时，既有 Codex 最终报告并未单列 clear，历史口径确实不完全一致，不能声称其他宿主都逐字测过。该差异需要明确统一，不由本轮静默改写标准，也不要求为测试新增 clear 命令。因此本轮只接受 compact 子场景，连续性整行仍 unknown。

## 工具、证据与边界

保留既有 `tools/conformance/probes/common.py`、`tools/conformance/probes/deepseek/probe.py` 和正式回归；未恢复已移出的平行工具体系。现有 probe 是无模型诊断入口，单独运行不能证明 11 项能力。临时驱动留在 `D:\AB\tsunagou-dsh-test\raw\`；两项补测证据位于 `deepseek-harness-final-20261001/`，本轮连续性证据位于 `deepseek-harness-continuity-20261001/`。

历史工具及其调用方完整归档在 `D:\AB\Tsunagou-acceptance-backups\deepseek-tooling-cleanup-20261001T091951Z.zip`。本轮修正文案前的报告和 8 份新证据另存于 `D:\AB\Tsunagou-acceptance-backups\deepseek-final-review-20261001T095430Z.zip`；原始 JSONL 未修改，仅修正两份摘要中的推断和报告。早期记录包含脱敏和已撤回机制，不能把旧正例作为当前机制有效的证明。

本轮连续性记录中的两个完整宿主会话 ID 已替换为与摘要一致的 SHA-256 标记，操作结果未改；修改前的报告和两份记录已备份于 `D:\AB\Tsunagou-acceptance-backups\deepseek-continuity-review-20261001T101403Z.zip`。

本次 compact 复核只更新本报告及既有 compact JSON；原始父/子日志未修改，连同修改前的两份文件备份于 `D:\AB\Tsunagou-acceptance-backups\deepseek-compact-review-20261001T103035Z.zip`。没有新增长期脚手架或另一份验收报告。

本次 DSH 实现新增 `packages/adapter-deepseek-host/`，并修改 `host_registration.py` 与 CLI 的注册接线；共享 bridge、协议和 Codex/OpenCode 配置未改。Codex 本次验收未修改产品代码；未 commit/push，门禁未升级，隔离现场保留，任务保持 `in_progress`。**11 项全部通过与完整接入仍是待完成目标，下一步按上述最小修复范围继续。**

本轮重新运行的相关检查见新 provider 验收小节；清理时的 Python 接入 73 通过、1 既有失败仅为历史结果，不冒充本轮新跑。未运行全量产品测试。

## 接线修复（执行者，供复验）

上一轮的四处外围缺陷已按同一顺序修完，逐调用身份方案未改架构：

| 缺陷 | 修法 | 验证 |
| --- | --- | --- |
| 安装失败退回可冒用身份的 stock overlay；控制台走旧路径 | 门控移入 `host_registration.register`，**provider 不可用即失败、不写 overlay**；CLI 与控制台（`console/enrollment.py:298`）走同一条路 | `test_registration_is_refused_when_the_identity_provider_is_missing` |
| `package.json` 声明即算就绪 | 就绪 = profile 内**实际可解析**的 `node_modules/<pkg>/package.json`；安装后复检，未验证即如实上报 | `test_a_declared_provider_that_is_not_installed_is_not_ready` |
| provider 丢弃 MCP 初始化提示 | 保留 `initialize` 结果并发布为 `mcp:tsunagou` 提示段 | 直连实测：bridge 发布 340 字符，已注册 1 段、文本 340 字符 |
| bridge 命令不存在时未处理的 `error` 事件带崩宿主 | 捕获子进程 `error`，以 `mcp_spawn_failed` 拒绝待处理调用并标记传输关闭 | 实测拒绝干净、**进程存活、无未捕获异常** |

单测 56 passed（deepseek 注册 / 注册 / 控制台项目 / CLI），ruff 与 mypy 干净。证据：[wiring-fixes.json](evidence/deepseek-harness-identity-provider-20261001/wiring-fixes.json)。

**尚未验证**（因此结论维持 9 supported / 1 failed / 1 unknown）：原会话 / 借 overlay / 新 fork / fork 独立接入四项真实宿主验收、同一宿主进程内 A→B→A 身份切换、最短 main/worker 任务与消息闭环、新接线下 compact 前后读取；clear 入口仍未找到。

### 定向真实验收（执行者，本轮跑到的部分）

| 项 | 结果 |
| --- | --- |
| 已登记会话取自己身份 | **成立**：headless 上 `session-555d26f4` 返回 `ea11a9ad…`；~~**web 面**上原 worker 会话返回 `beb92813…`~~ **此说法已撤回**：那次读数取自日志中最新的一条 tool/result，而它是该会话**早先的历史**，并非本次提示产生；web profile 里 provider 未安装，入口未挂载，会话**根本没有 Tsunagou 工具**（实测 `Error: unknown tool "mcp__tsunagou__context__project_read"`）。见 [更正](evidence/deepseek-harness-identity-provider-20261001/web-surface-correction.json) |
| 他人会话加载同一 overlay | **被拒** `not_enrolled:no_ticket_or_session_file`（手工 overlay 与产品生成的 overlay 都是） |
| 借父 overlay 的 fork | **取得父身份** —— 但那份 overlay 是**本轮接线之前**写的（仍是 stock client、无 meta 键），属旧配置的应有行为 |
| fork 在自身新 overlay | 驱动脚本报错，**未完成**（非产品结果） |
| 同一宿主进程 A→B→A / 最短任务闭环 / 新接线下 compact | **未跑** |

**新发现的迁移缺口**：**旧接入不会被自动改写**。本轮之前登记的会话，其 overlay 仍指向 stock client 且不声明 meta 键，因此在重新接入前**仍然可被冒用**——这不是新接线的缺陷，恰恰是新接线让它显形。是否需要迁移（例如接入时检测旧 overlay 并重写），请验收方定。

**方法上的解封**：分叉会话运行在 `standard` preset 下，一次性 headless runner 拒绝驱动，因此只能在 web/tui 面驱动；`session/prompt` 的 `mode` 枚举是 **`queue`|`steer`**（此前传 `normal` 才一直被边界拒绝）。现在已能用探针驱动 web 会话。

### A→B→A 与 compact（执行者）

**同一个 web 宿主进程内**，用 fork 自己的 overlay：

| 步骤 | agent | Tsunagou session |
| --- | --- | --- |
| A 第一次 | `8850dcc2-0d5a-4cf5-8ab1-34cb4a1cab94` | `7179dccd-9c31-44a1-b54c-8f7923cfd7ed` |
| B 中间 | *无身份读数* | *无* |
| A 再次 | `8850dcc2-0d5a-4cf5-8ab1-34cb4a1cab94` | `7179dccd-9c31-44a1-b54c-8f7923cfd7ed` |

A 取到的是**自己的**身份（与父会话 `beb92813…` 不同），且在 B 之后**保持不变**。**每次读数都限定在该次提示之后产生的事件**——上一轮把日志末尾的历史当成新结果，这次不再可能。

**B 仍是开口**：它没有产生任何身份读数（既不是 A 的，也不是它自己的，也没有错误码）。是"被拒"还是"模型没调工具"，尚未确定。

**`/compact` 经 `session/prompt` 无效**：提示被接受并执行（9 个新事件），但**没有任何 compaction 事件**。说明 `session/prompt` 不是命令路径——斜杠命令由输入框提交时识别，注入用户消息不算。因此**真实的 compact 证据仍只有此前人工操作那一次**。

顺带修掉一个阻塞：`session/writer-held` 源于启动器是 `.cmd` 包装器，`kill()` 只杀掉包装器、node 子进程仍持有写句柄；改为结束进程树后消失。

**B 已定性（同日补）**：从该窗口的原始日志读回，B 的结果是 **`not_enrolled:no_ticket_or_session_file`**（seq 851）——
即**在同一进程内被拒**，而不是拿到 A 的凭据。于是 A→B→A 的完整含义是：

| 步骤 | 结果 |
| --- | --- |
| A 第一次 | 自己的身份 `8850dcc2…` / `7179dccd…` |
| B 中间 | **被拒** `not_enrolled:no_ticket_or_session_file` |
| A 再次 | 仍是自己的身份 `8850dcc2…` / `7179dccd…` |

一次进程、三次连续调用：A 的身份 → 另一会话被拒 → A 的身份，**没有身份串过去**。

更正：本节此前写"B 没有产生任何身份读数、尚未确定"——那是读取器没提取出来（bridge 以 `Error: {..}` 形式报错，不是 `tsunagou_error:`）。同一窗口里另有一条 seq 832 的 `unknown tool`，属 provider 尚未装入 web profile 时的更早尝试。

### 最短 main/worker 闭环（执行者）

两个**分别登记**的会话跑通了一个真实周期：

| seq | 步骤 | 结果 |
| --- | --- | --- |
| 44 | `task.create`（main） | task `6489367b-…`，draft，rev 1 |
| 50 | `task.ready` | ready，rev 2 |
| 56 | `task.publish` | open，rev 3 |
| 73 | `inbox.claim`（main） | 消息 `8f33556c-…`，**kind `task.submitted`**，发送者 `ea11a9ad…`（worker），**收件人 `5cee40b8…`（main）** |
| 79 | `inbox.fetch`（main） | 同一消息 |

**main = `5cee40b8-0231-4742-8c1d-f010502276b4`（mainflow/main），worker = `ea11a9ad-2d89-4f97-b90b-5c500f7ea69f`（verify2/worker）**——两个会话全程各持不同身份，任务与消息闭环成立。

更正一处：驱动脚本把 main 那步的 `agent_id` 打成了 `ea11a9ad…`，那是因为读取器取的是最新工具结果里第一个像 agent id 的字段，而 main 的收件箱消息里带的正是 worker 的 id。main 自己的身份是**收件人** `5cee40b8…`。

### 新接线下 compact（执行者，由用户在界面操作）

该会话的 overlay **带 provider 与 `TSUNAGOU_HOST_META_KEY`**，因此这次的身份是逐调用送达的——与此前那份旧 overlay 下的压缩证据不是同一回事。

日志中该会话共有两次压缩（idx 751、940），取**最近一次**：

```
command/run(938) → compaction/start(939) → compaction/summary(941, 9181 字符) → compaction/end(943) → command/done(944)
```

| | seq | agent | Tsunagou session | epoch |
| --- | --- | --- | --- | --- |
| 压缩前 | 931 | `8850dcc2-0d5a-4cf5-8ab1-34cb4a1cab94` | `7179dccd-9c31-44a1-b54c-8f7923cfd7ed` | 1 |
| 压缩后 | 958 | `8850dcc2-0d5a-4cf5-8ab1-34cb4a1cab94` | `7179dccd-9c31-44a1-b54c-8f7923cfd7ed` | 1 |

**同 agent、同 session、epoch 未变，宿主会话未变。** 证据：[compact-new-wiring.json](evidence/deepseek-harness-identity-provider-20261001/compact-new-wiring.json)。

至此本轮交办的三项均已实测：**A→B→A 同进程身份不串**、**最短 main/worker 闭环**、**新接线下 compact 前后身份一致**。仍开放：**clear 无入口**（未用 `new` 顶替）、**旧接入不自动迁移**（接线前登记的会话仍指向 stock client）。

### clear 入口调查与回归（执行者）

**clear：本构建没有任何入口。** 遍历安装包（js/md/json，三层）搜 `/clear`、`/new`、`/reset`、`clearSession`、`session/clear`、`clearHist`、`resetSession`，并直接读命令注册：

> 本构建注册的命令只有 **`compact`、`feedback`、`goal`、`plan`** 四个。

所有 `/clear` `/new` 命中都与会话清空无关：`goals/clear`（清目标）、`connection/reset`（传输重连事件）、`clearHistory()`（编辑器撤销历史）、`session/new`（ACP **协议**建会话方法，**不是 `/clear` 别名**）、`resetSession()`（重解析命令组成）。

这条结论**不是**从"缺少某个包名"推断出来的——**命令注册表本身就是证据**。未用 `new` 顶替 clear。

**回归（本轮改动后重跑）**

| 套件 | 结果 |
| --- | --- |
| 三宿主适配器（codex/opencode/deepseek） | **18 passed** |
| bridge 凭据交接 + 元数据 | **26 passed / 0 failed** |
| bridge 消息契约 | 1 passed |
| Python 注册与接入 | **64 passed** |
| `validate_docs` | PASS |

bridge 那组尤其相关：其中 `unconfigured metadata bridge never falls back to its bootstrap credential after observing metadata` 与 `host-metadata bridge rejects a first call without valid metadata` **正是本适配器现在依赖的 fail-closed 路由**——DeepSeek 的 overlay 现在也声明 `TSUNAGOU_HOST_META_KEY`，走的是与 OpenCode 同一条已被测试覆盖的路径。

### 迁移问题的处置（收口）

**结论：不迁移，按"不适用"关闭。**

依据：目前存在的旧式 overlay **只有隔离现场自己的测试接入**；用户已确认**从未有别人按旧方式接入过**本适配器，因此不存在携带旧形态的存量用户。此后写入的 overlay 一律带 provider 与 `TSUNAGOU_HOST_META_KEY`，该条件不会再由这条代码路径产生。

**本条不主张**旧 overlay 变安全了——`fork-on-parent-overlay` 的实测仍然显示旧 overlay 会继承身份；那条记录作为**旧形态行为的存档**保留，而不是"有用户在背后的现存缺陷"。

隔离现场里仍有改动前的 overlay，属测试夹具，**不应作为当前行为的证据**。证据：[migration-decision.json](evidence/deepseek-harness-identity-provider-20261001/migration-decision.json)。

## 收尾（按用户判定）

**结论：11 项 supported，其中 `identity.continuity_evidence` 含一处明确标记的缺口（clear）。**

**判定归属**：本结论**由用户作出**。此前各轮明确把"是否上调"保留给独立复核，因此报告如实记录这是用户的判定，执行者未自行上调，也未改动发布门禁输入（`docs/research/evidence/deepseek-2026-10-01.json` 保持原样，仍待 Codex 独立复核）。

**clear 的处理**：标记保留，不静默通过。本构建命令注册表只有 `compact`、`feedback`、`goal`、`plan`；无 `/clear`，也无官方等价别名；**未用 `new` 顶替**。

**本轮修复并已验证的四处接线缺陷**：

| 缺陷 | 修法 | 验证 |
| --- | --- | --- |
| 安装失败退回可冒用身份的 stock overlay；控制台走旧路径 | 门控移入 `host_registration.register`，CLI 与控制台同路 | `test_registration_is_refused_when_the_identity_provider_is_missing`；真实 `agent connect` 实测 `enrolled` |
| `package.json` 声明即算就绪 | 以 profile 内**实际可解析**的包为准，覆盖该 home 下全部 profile | `test_a_declared_provider_that_is_not_installed_is_not_ready`；四 profile 实测就绪 |
| provider 丢弃 MCP 初始化提示 | 保留 `initialize` 结果并发布为 `mcp:tsunagou` 提示段 | 直连实测 340 字符 |
| bridge 命令不存在时未处理的 `error` 带崩宿主 | 捕获并拒绝待处理调用 | 实测 `mcp_spawn_failed`，进程存活 |

**安装链路上的三处通用缺陷**（中文 Windows 上调用任何宿主 CLI 都会遇到）：我自己的 `package.json` 带 UTF-8 BOM；`_run` 无 shell 起不了 `.cmd`；`_run` 按 GBK 解码炸掉 UTF-8 输出。均已修复。

**定向真实验收**：原会话取自己身份、借 overlay 被拒、fork 独立接入、**同进程 A→B→A 身份不串**、**最短 main/worker 闭环**、**新接线下 compact 前后身份一致**。

**回归**：三宿主适配器 18 passed；bridge 凭据交接+元数据 26 passed / 0 failed；消息契约 1 passed；Python 注册与接入 64 passed；`validate_docs` PASS。

**边界**：共享 bridge 与协议未改；`src/` 仍是此前待审的 7 个 Python 文件；未 commit / push；Trellis 任务保持 `in_progress`。证据：[acceptance-closure.json](evidence/deepseek-harness-identity-provider-20261001/acceptance-closure.json)。
