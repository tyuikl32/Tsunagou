# 首批 Agent 适配与会话身份研究

> 研究日期：2026-09-17。仅查阅公开文档与源码；没有安装、启动或修改任何 Agent。
> 产品范围以用户最新要求为准：Codex、OpenCode、ZCode、DeepSeek Harness；Claude Code 暂不纳入。

## ZCode

来源：[官方首页](https://zcode.z.ai/)、[Agent 说明](https://zcode.z.ai/cn/docs/agents)、[Hooks](https://zcode.z.ai/cn/docs/hooks)、[MCP](https://zcode.z.ai/cn/docs/mcp-services)。

已核实的文档事实：

- 官方自研 ZCode Agent 是独立宿主；不能直接视为 Codex 适配器的别名。
- 支持 MCP stdio、HTTP、SSE 配置；配置来源与优先级需要按官方规则处理。
- Hook 通过本地子进程 stdin/stdout JSON 工作；输入有 session_id、事件类型、工作目录和工具信息。
- SessionStart 可区分 startup、clear、compact。PreToolUse 能拒绝或替换工具输入；PostToolUse 能追加模型可见上下文。
- Hook 配置在 session 启动时形成快照；插件启用后已有会话不保证热更新。
- 官方文档明确当前不执行项目级 Hook 配置，建议插件或用户级配置；同页末尾又提及 workspace 配置入口，存在不一致，应以警示为保守边界并做版本实测。
- Hook 的 transcript_path 指向临时文件，调用完成会清理；不能将其路径作为长期会话身份证据。
- 分叉产生新任务并保留原会话；fork 不回滚共享工作目录，也不复制在途任务和队列。

对本项目的推论：MCP + 原生 Hook 是可行方向；session_id 与 source 能协助身份绑定。恢复事件、清空后 ID 是否变化、MCP 调用与 Hook 的会话关联、闲置时主动注入的稳定接口尚需核实。

## DeepSeek Harness

来源：[官方仓库 README](https://github.com/deepseek-ai/deepseek-harness)、[架构](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.md)、[Agent 生命周期](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/core.md)、[Session](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/session.md)。

已核实的文档事实：

- DeepSeek 官方开源 Harness，基于 Cordis 插件体系；README 标明 developer preview，会发生破坏性变更。
- 有 web、headless、sdk、acp 等 profile；Python SDK 也通过 dsh SDK profile 启动。
- Session 是追加式事件记录，模型历史由日志推导；新建与恢复具有不同生命周期路径。
- AgentRegistry 提供 create/resume；Agent 与 Session 共享会话身份；生命周期 source 包含 startup、resume、clear、compact。
- 公开的 Agent 接口包含 inbox 投递、steer/inject 等能力；注入上下文并不总是立即唤醒，必须按边界和唤醒语义适配。
- tools/pre-execute、tools/post-execute 和 agent 生命周期事件可用于插件观察/拦截。
- fork 可以复制上下文历史；新身份与来源关系应独立处理，不能因继承历史而共享 Tsunagou 执行身份。

对本项目的推论：原生插件能提供较强的会话连续性证据与模型可见回执，但需要固定宿主版本或 commit，并有适配契约测试。当前未将主干文档当作稳定版本承诺。

## 身份与支持深度建议（待决）

- 厂商产品类型、宿主安装实例、宿主对话、项目成员身份、连接实例分别标识。
- 恢复身份不能只依靠模型自述、工作目录、显示名称或配置中的旧 token。
- 已确认：同一对话恢复或压缩只有在宿主证据可验证时延续身份；新建、clear、fork 创建新身份，fork 只记录来源关系；无法验证时重新接入。
- 缺少可靠生命周期证据的宿主，应明确暴露能力不足并采用确认/重新接入流程。
- 接入演示仅验证基本调用；正式支持必须验收身份隔离、任务/认知/契约闭环、持久消息、断线恢复和去重。
- 主动唤醒、工具门禁、进程启动等增强能力可因宿主不同而不同，但不得降低已确认的身份要求。
- 适配器执行继任时必须支持任务级凭据/租约切换；批量整体继任是同一原子交接机制的批量形式。宿主侧无法停止的旧进程必须作为残余风险上报。
- 适配器不得把加入票据持久化为长期凭据；兑换后使用可撤销、可轮换的访问令牌，并将项目成员 `agent_id` 与宿主会话及连接实例分别保存。

## 已确认的支持目标：共同基线与分级增强

用户已确认四种适配器均须达到正式共同基线；主动唤醒和工具门禁允许按宿主能力增强。此处是产品验收要求，不表示四种宿主已经通过实测。

| 能力 | 四种适配器的统一要求 | 验证重点 |
|---|---|---|
| 注册与身份绑定 | 必须支持 | 同厂商并行对话不能混用身份；新空对话不得沿用旧授权 |
| 上下文获取 | 必须支持 | 接入项目、任务与契约版本可核查 |
| 任务生命周期 | 必须支持 | 领取、状态更新、结果提交服从统一领域规则 |
| 认知报告与协商 | 必须支持 | 提交报告、提议、异议与契约接受，遵守统一版本约束 |
| 独立持久收件箱 | 必须支持 | 定向消息、逐条确认、失败重投和去重 |
| 恢复与重新接入 | 必须支持 | 验证宿主恢复/压缩证据后延续身份；新建、clear、fork 或证据不足时重新接入 |
| 主动唤醒 | 能力增强 | 不具备时明确回退至检查点拉取，不能伪报即时送达 |
| 工具门禁 | 能力增强 | 声明实际可拦截工具范围；缺失时不宣称运行时强制 |

后续拟做统一适配契约测试，再以真实宿主测试确认能力。宿主拒绝调用、会话结束、插件停用和协议不兼容都应显式可见，不能以“已安装 MCP”替代验收。

## 权限门禁补充研究

用户确认宿主可为保证完整工作能力而以 Full Access 运行；调度中心的逻辑范围与宿主的机械范围必须分开建模。2026-09-17 查证结果：

| 宿主 | 已核实的机制 | 当前结论 |
|---|---|---|
| Codex | 本机 CLI 提供启动参数 `--sandbox`、`--cd`、`--add-dir` 和 approval policy；`hooks` 在当前 CLI 功能表中为 stable | 可在启动时选择沙箱与可写根目录；尚未找到可依赖的会话内动态改写范围接口，不能先行承诺动态强制 |
| OpenCode | [权限文档](https://opencode.ai/docs/permissions/)支持 allow/ask/deny、按工具与路径匹配、`external_directory` 和 per-agent 覆盖；显式 deny 在 auto mode 下仍生效 | 能提供宿主规则门禁，但配置热更新、外部调度中心逐次裁决以及 shell 内嵌路径的完整覆盖仍需真实版本测试 |
| ZCode | [Hooks](https://zcode.z.ai/cn/docs/hooks)的 PreToolUse 可 allow/ask/deny 并替换工具输入，PermissionRequest 可更新权限；Hook 配置按 session 快照 | 对被 Hook 覆盖的工具可在执行前向调度中心查询实时策略；安装/启停 Hook 后通常需新建 session，且不能推断覆盖宿主外部写入 |
| DeepSeek Harness | 官方架构提供 `tools/pre-execute` waterfall、`fs/*` 扩展点、sandbox backend 和 per-agent scope | 原生插件具备实现实时策略门禁的结构条件；项目仍为 developer preview，需固定版本并以契约测试确认阻断语义 |

建议将执行强度记录在每个能力/资源类型上，而不是给整个 Agent 一个笼统安全等级。至少分别报告文件读写、命令执行、网络访问、调度中心 API、IDE 原生工具和宿主外部进程；同一适配器可能对这些类别具有不同强度。

用户已确认上述方向，并采用四级协议：`advisory`、`observed`、`gated`、`isolated`。任务可以声明最低执行强度；适配器低于要求时不能自动接受任务，只有项目策略允许时主 Agent 才能留下理由显式降级。

## 已确认的适配器实现边界

第二轮实现协商进一步确认：

- 四款采用宿主原生薄桥接，直接调用统一 REST/SSE；Python 核心不加载厂商 SDK。
- Codex 使用独立 MCP bridge；OpenCode、ZCode、DeepSeek Harness 使用各自原生插件或 Hook，并共享 OpenAPI、JSON Schema、测试向量和 conformance runner。
- 静态能力清单只声明适配器上限；每次连接还要运行探测，保存 effective capabilities 与证据。只对 min-supported/max-tested 窗口内版本承诺正式支持。
- 四款均须支持附着已有会话；managed launch 属增强能力。协调器只终止自己启动的进程。
- 模型只获得 context、task、report、contract、inbox、lease 等类型化工具；bridge 代持 token，凭据不能进入 prompt、schema、Git 或模型可读环境变量。
- SSE 只提供变化/唤醒信号，权威消息与资源经鉴权 REST 拉取。取消、交接、hard discrepancy、契约请求、租约风险和明确高优先级请求可主动唤醒，其他通知等待下个边界。
- 门禁故障按声明强度处理：gated/isolated 要求的操作 fail-closed，advisory/observed 可留痕 fail-open。
- 安装器只维护带 owner/version 标记的配置区块，升级前备份，发现用户修改时停止自动覆盖。
- 真实 Coding Agent e2e 首版采用逐版本手工验收；只有 Windows 测试阻止发布，其他平台必须在兼容说明中标记为非阻塞验证。

完整决定见 [第二轮实现决策账本](./implementation_decisions_round2.md)。
