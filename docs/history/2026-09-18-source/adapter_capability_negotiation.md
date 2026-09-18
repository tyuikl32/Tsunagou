# Adapter 能力探测与快照

> 核对日期：2026-09-17。
> 状态：第 192 题已确认选项 A；作为 D116 的能力探测基线。

## 依据与边界

[MCP 生命周期规范](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle)要求初始化阶段先协商协议版本、交换 capabilities 和 implementation information，再开始正常操作。[A2A 规范](https://a2a-protocol.org/latest/specification/)也把 Agent Card、AgentCapabilities、AgentSkill 与 AgentInterface 作为发现和互操作对象。

Tsunagou 的 adapter capability 不是 Agent 自报的业务权限。它只描述宿主/bridge 实际能否提供某类功能和证据，例如：

- session identity/continuity evidence；
- MCP/tool 调用、SSE/pull inbox、主动 wake；
- pre-tool gate、post-tool observation、session lifecycle hook；
- managed launch/stop；
- 文件、命令、网络等 enforcement strength；
- presented/stop/process continuity evidence。

Grant 决定“允许做什么”，capability snapshot 决定“当前宿主能可靠做到什么”。两者必须同时满足。

## 第 192 题：能力何时探测和更新

### A（已确认）：attach/resume 时探测一次，变化显式生成新快照

- 代码内的 `AdapterDescriptor` 声明 adapter kind/version 支持的最大能力和正式测试窗口；它不是运行事实。
- 每次 attach 或恢复新 Connection epoch 时，bridge 执行固定 probe suite，提交版本、配置/插件摘要和逐能力 evidence。服务端取 descriptor 上限、版本窗和 probe 结果的保守交集，创建不可变 `CapabilitySnapshot`。
- probe 完成前 HostSession 为 `probing`，只允许初始化/诊断命令；无法证明的能力记 `unknown`，不能按 supported 处理。
- 宿主 lifecycle/config/plugin 变化时，adapter 显式调用 `ReprobeCapabilities` 创建新 snapshot revision。首发不在每条业务命令前调用宿主 probe。
- 能力下降立即影响 eligibility，相关 claimed/running attempts 产生 blocker 或 migration/re-preflight；能力上升只扩大可选候选集合，不自动扩大 Grant、task scope 或恢复被阻塞任务。
- 每个 task claim/preflight、RiskAssessmentRequest 和消息 RoutingSnapshot 记录所使用的 capability snapshot ID/digest，便于重放。

优点：运行事实可审计且开销有界；连接/配置变化会刷新，普通命令不依赖慢或不稳定的宿主探测。代价：adapter 必须实现可重复 probe suite 和变化通知。

### B（已否决）：只使用 Adapter 静态清单

- 根据 adapter/host version 直接加载代码中的 capability manifest，不运行动态 probe。

优点：实现最少。代价：插件未安装、配置失效、权限关闭或 Hook 加载失败时仍会宣称支持，无法满足正式共同基线。

### C（已否决）：每条命令执行前实时探测

- command handler 调用 bridge/宿主确认所需能力，再授权执行业务命令。

优点：状态最新。代价：延迟、失败面和宿主耦合显著增加；事务前探测与实际执行仍存在竞态，也无法替代 snapshot/事件记录。

## 选择 A 时的快照结构

```text
CapabilitySnapshot
  snapshot_id, host_session_id, connection_epoch
  adapter_kind, adapter_version, host_kind, host_version
  protocol_version, schema_bundle_digest
  descriptor_version, probe_suite_version
  capabilities[] {id, status=supported|unsupported|unknown,
                  strength?, evidence_kind, evidence_digest}
  config_digest, plugin_set_digest
  created_at, supersedes_snapshot_id nullable
  snapshot_digest
```

不保存完整宿主配置、transcript、命令输出或 secret。evidence payload 只保留验证所需的有限结构与 digest，敏感内容留在本机 adapter 诊断区并按保留策略清理。

## Probe 失败语义

- 必选身份隔离、项目上下文、任务操作、认知/契约、inbox、恢复/去重任一共同基线能力为 unsupported/unknown 时，该 adapter session 不进入 `ready`，只提供诊断/修复。
- enhancement 缺失不阻止 attach，但必须准确降级：无 wake 使用 pull，无 gate 标为 advisory/observed，无 managed launch 只允许 attached。
- probe transport failure 不复用上一次 snapshot 冒充当前结果；resume 留在 probing/degraded，已运行任务按其 minimum capability 和既有 blocker 规则处理。
- snapshot supersession 不改写历史 TaskAttempt、RoutingSnapshot 或 IsolationDecision 引用。

## 后续待细化

- 通用 capability ID 注册表和四 adapter probe mapping；
- 每项 evidence kind 的验证器与 conformance fixture；
- snapshot 下降对 task/workspace/message 的影响矩阵；
- capability/config 变化的宿主事件来源和手工 `reprobe` CLI。

## 第 193 题：共同基线 Probe 失败时如何接入（已确认 A）

### A（已确认）：保留 diagnostic-only HostSession，修复后原地 reprobe

- 身份/票据校验成功后可以物化 HostSession，但若任何 mandatory baseline capability 为 unsupported/unknown，状态为 `degraded`，不签发正常 `agent_base`，也不进入 task eligibility 或 main-agent candidate 集。
- degraded session 仅能调用静态 allowlist 的 bootstrap/diagnostic endpoints：读取自身 session/probe 结果、提交新 probe、结束 attach；不能读取项目协调状态、inbox、claim/execute task、参与 contract 或获得管理 grant。
- user/control 可查看结构化缺失项和修复建议。修复配置/插件后，同一 HostSession 调用 `ReprobeCapabilities(expected_revision)`；全部 mandatory 通过时单事务转为 `ready` 并签发 agent_base。
- 已 ready 的 session 在 resume/reprobe 后丢失 mandatory capability 时转 degraded，冻结其业务 grants；running attempt 进入 blocker/orphan/migration 的具体结果按缺失能力类别决定，不能继续“尽力而为”。
- diagnostic session 默认不设时间 TTL；用户可 detach，项目删除/归档同样清理。它不算正式接入成功，适配器发布验收也不能据此宣称支持。

优点：失败可诊断和原地修复，不创建半可用 Agent；共同基线仍是硬门槛。代价：需要很小的 bootstrap authorization allowlist 和 degraded 状态。

### B（已否决）：Probe 失败就回滚整个 attach

- 不保存 HostSession，只返回错误；修复后重新消费新 enrollment ticket。

优点：领域状态最干净。代价：诊断信息和失败历史难保留，每次修复都需新票据，用户体验较差。

### C（已否决）：按实际能力进入 ready，缺什么就禁什么

- 只要身份验证成功就签发 agent_base；缺失的任务/认知/inbox 能力按 action 禁用。

优点：最大限度使用残缺适配器。代价：四种适配器的“正式共同基线”失去含义，可能出现能 claim 却无法收件、协商或恢复的半工作 Agent。

## 第 194 题：共同基线如何在协议中表示（已确认 A）

### A（已确认）：服务端版本化 Profile，展开为原子能力与证据要求

- 服务端代码/协议注册 `collaboration_baseline_v1`，固定 required atomic capability IDs、允许的 evidence kinds 和最低 strength；adapter 不能自报 profile 已通过。
- CapabilitySnapshot 逐项保存原子能力状态/evidence；readiness evaluator 根据注册的 profile version 计算 `satisfied|unsatisfied` 和缺失项。
- 首版 baseline 至少包含：
  - `identity.session_isolation`、`identity.continuity_evidence`；
  - `context.project_read`、`command.typed_tools`；
  - `task.lifecycle`、`cognition.report`、`contract.participation`；
  - `inbox.pull_fetch_ack`、`response.structured`；
  - `recovery.idempotent_reconnect`、`delivery.deduplicate`。
- `wake.push`、`tool_gate.*`、`managed_launch`、`model_presented_evidence` 等保持 enhancement，不影响 baseline ready，但可成为具体 Task 的额外 minimum capability。
- profile 新版本只追加/调整时显式发布；现有 HostSession 继续绑定 attach 时协商的 profile version，升级通过 reprobe/migration，不静默改变 readiness。

优点：四种 adapter 用同一、可测试的合格定义，同时保留各能力的诊断和任务选择；profile 版本能进入 release matrix。代价：需要维护一份 profile registry 和 atomic evidence 规则。

### B（已否决）：Adapter 只报告一个 `common_baseline_supported` 布尔值

- bridge 根据自己的逻辑决定是否支持共同基线，核心只存 true/false。

优点：核心协议最小。代价：无法知道缺哪项、无法统一验证，也不能防止四个 adapter 对“支持”作不同解释。

### C（已否决）：不设 Profile，只在每个 Task 上逐项要求能力

- HostSession 只要身份通过就 ready；任务根据自己的 required capabilities 筛选。

优点：最灵活。代价：Agent可能进入项目后才发现无法收件、协商或恢复，重复第 193 题已否决的半可用问题。

## 第 195 题：四种宿主的会话证据如何统一（已确认 B）

[Codex CLI 官方功能页](https://developers.openai.com/codex/cli/features/)与[命令参考](https://developers.openai.com/codex/cli/reference/)明确区分恢复已有会话的 `resume` 和产生分支的 `fork`，但不能据此假定它与其他宿主共享字段格式。ZCode Hook 文档暴露 `session_id` 与 SessionStart source；DeepSeek Harness 使用追加式 Session 事件；OpenCode SDK 提供独立 Sessions API。统一层应约束语义和 verifier 结果，而不是字段名称。

### A（已否决）：每 Adapter 版本化 Evidence Schema，归一为共同 Verdict

- `protocol/schemas/agents/evidence/<adapter>/<version>.json` 定义各宿主原生字段、事件来源和允许的 lifecycle transitions；core 只接受已登记 adapter/version/evidence schema。
- adapter-specific verifier 输出统一 `ConversationContinuityVerdict`：`same|new|forked|cleared|ended|unverifiable`，并带 evidence digest、confidence class（不是模型概率）、parent digest 和 reason code。
- core 根据 verdict 执行固定规则：只有 `same` 可 resume；`new|forked|cleared` 必须新 Agent；`ended` 收敛旧 session；`unverifiable` 保持 degraded/要求重新 enrollment。
- verifier 可以位于 TypeScript adapter/bridge，但必须提交规范 payload，Python core 用 schema、descriptor version、既有 digest/transition 和 conformance fixture 再验证；首发不要求硬件签名或厂商远程证明。
- 只保存稳定 ID 的 keyed digest、lifecycle metadata 和有限 evidence；不保存 transcript path、正文、宿主 token 或完整配置。

优点：尊重宿主差异，又让 core 的身份规则一致且可测试；新增宿主只增加 evidence adapter。代价：每个正式支持版本都要维护 schema/verifier/fixture，Codex 等缺乏足够公开证据时必须通过实测或保持 degraded。

### B（已确认）：强制所有 Adapter 提供统一 `host_conversation_id`

- 所有 adapter 在 attach/resume 协议中提供非空 `host_conversation_id`。唯一性作用域为 `(adapter_installation_id, host_kind)`，避免不同安装/厂商碰撞。
- resume/compact 必须保持 ID；new/clear/fork 必须产生新 ID。fork 可同时提供 `parent_host_conversation_id` 作为 provenance，但不能继承 Agent/task owner 身份。
- core 对规范化 ID 做精确相等比较，不解释宿主字段或统一 verdict。数据库仅保存 keyed digest；原始 ID 不写日志、prompt、共享 Git 或领域事件。
- adapter 可使用宿主原生 ID，或使用可靠写回/绑定到该宿主对话生命周期的 opaque ID；禁止使用 bridge PID、工作目录、显示名称、旧 session token 或模型自述作为 ID。
- 正式 conformance 必须实测：原会话 resume/compact ID 不变，并行会话/new/clear/fork ID 不同。无法满足的宿主版本将 `identity.continuity_evidence=unknown|unsupported`，不能进入 ready。

优点：core 协议与表结构最小，四个 adapter 共享相同匹配算法。代价：差异和验证负担转移到 adapter/conformance；一个字符串本身不携带 transition 证据，因此必须严格测试生命周期行为。

### C（已否决）：不采信宿主证据，每次 resume 都由用户手工确认

- bridge 重启或宿主恢复时暂停，由用户选择是否仍是原 Agent。

优点：不依赖厂商字段。代价：频繁打断本机协作，无法自动完成断线恢复共同基线，也不适合后台 inbox/lease 恢复。

## 第 196 题：宿主无法提供稳定 Conversation ID 时怎么办（已确认 A）

### A（已确认）：该宿主版本不得进入正式 ready

- probe 将 `identity.continuity_evidence` 标为 unsupported/unknown，HostSession 按 D117 保持 diagnostic-only degraded。
- adapter 可以通过后续版本增加原生集成、Hook/plugin 字段或可靠的 per-conversation durable binding；通过 conformance 后再加入正式版本窗。
- 不允许用户点击“仍然信任”把该版本升级为 ready；用户仍可查看诊断并使用其他已支持版本/宿主。

优点：保持 D16 和“四种正式共同基线”的含义，不会让新对话借旧身份接管任务。代价：某些当前宿主版本可能暂时无法正式支持，必须先完成 adapter spike。

### B（已否决）：允许用户手工确认并继续使用旧 Agent

- 无稳定 ID 时，每次 attach/resume 由用户选择原 Agent，系统记录 manual evidence。

优点：能覆盖缺少 API 的宿主。代价：人工误选会直接接管旧身份；断线自动恢复不成立，还需审批 UI/CLI 流程。

### C（已否决）：Bridge 每次启动生成 ID，尽量复用本地文件

- 在工作目录或 adapter 私有目录保存随机 ID；只要文件存在就视为同一 conversation。

优点：实现容易。代价：多个对话共享目录会碰撞，复制/清理文件会误继承或丢失身份；这只是 bridge 安装身份，不是宿主对话身份。

## 第 197 题：Adapter Installation ID 如何产生和持久化（已确认 A）

### A（已确认）：安装/注册时生成随机 UUID，升级保持，卸载重装重建

- 每个宿主用户 profile 下的 Tsunagou adapter 安装/注册动作生成一个 UUIDv7 `adapter_installation_id`，写入 adapter 私有数据目录和 daemon 的本机安装登记表；它不是 secret，也不进入 prompt/Git。
- 正常 adapter 升级、配置更新、bridge 进程重启和可验证的数据目录迁移保持 ID；用户执行 uninstall/reset identity 或丢失私有数据后重新安装则生成新 ID。
- 同一宿主存在多个独立 profile/data directory 时各有自己的 ID；同一 ID 不得被两个 active host instances 并发声明，冲突进入诊断而非自动合并。
- 首次登记用 user/control 安装命令或一次性 enrollment ticket 关联 daemon；之后 attach 仍用 HostSession token 鉴权，installation ID 本身不授予权限。
- installation ID 改变后，旧 conversation ID 即使字符串相同也不自动匹配旧 Agent；用户需要新 enrollment，并可由主 Agent按既有继任流程处理旧任务。

优点：作用域稳定、与路径/版本解耦，支持多个宿主 profile；实现只是本机 UUID 与登记表。代价：私有数据丢失会导致需要重新接入，不能从工作目录猜回旧 installation。

### B（已否决）：从 Adapter 可执行文件路径和宿主版本派生

- 对规范化 executable/plugin path、host version 和用户 profile 做 hash。

优点：无需保存随机 ID。代价：升级、移动目录或切换版本会改变 ID；复制安装可能碰撞，路径还可能泄露本机信息。

### C（已否决）：不设 Installation ID，Conversation ID 在同一宿主类型下全局唯一

- 身份键只使用 `(host_kind, host_conversation_id)`。

优点：少一个字段。代价：不同用户 profile、并行安装或厂商 ID 重置可能碰撞，无法区分同一 ID 来自哪个本机宿主实例。
