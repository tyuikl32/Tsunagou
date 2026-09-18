# Agent 协同方法探索：深度研究与项目适配结论

> 研究日期：2026-09-17  
> 研究对象：[原题《Agent 协同方法探索》](https://join.geek-tech.club/problems2/agent-to-agent)及其附录资料  
> 文档性质：外部研究、架构判断和验证方案。事实、建议与待验证假设在文中分别标明。

## 1. 结论先行

这个项目与原题高度契合，但需要准确表述它要证明的命题：

> 项目不应试图证明“共享代码区天然优于 Worktree”，而应证明“统一协调平面能够让多个 Agent 在共享目录、Worktree 或其他隔离方式下，更早发现理解与契约分歧，并减少重复劳动和晚期集成失败”。

建设本身的可行性高，尤其是本地 Python 服务、中心持久化、MCP 接入、显式认知报告、契约协商、任务依赖、租约和事件回放。真正的不确定性是“它是否比成熟的 branch-and-merge 隔离方案更高效”。2026 年的 CAID 研究显示，Worktree 隔离相较共享工作区的软约束更稳定，但也带来额外成本，而且端到端耗时未必明显下降。因此，性能优势只能通过严谨对照实验得出，不能先写进产品承诺。

建议首阶段采用“Python 模块化单体 + 内部领域协议 + 多适配器”形态，而不是微服务。内部状态模型必须独立于 MCP 和 A2A：MCP 是 Coding Agent 最现实的本地接入面；A2A 适合未来的跨厂商、跨进程或跨机器互操作；二者都不能替代项目状态、权限、租约、冲突和契约模型。

## 2. 对原题的完整解读

### 2.1 原题真正反对的是什么

原题指出，多 Agent 直接操作同一代码库会产生三类典型失败：文本覆盖、接口不一致、环境互相污染。简单地将 Agent 放进独立 Worktree 或容器可以避免即时干扰，却会让 Agent 看不见彼此正在做什么，导致重复实现、设计分叉和最终串行合并。

因此，题目并不要求取消隔离，而是要求补上隔离缺少的协调信息，并在真实任务上证明收益。

### 2.2 必做能力

原题的 Lv1 要求共享状态至少包含：

- Agent 当前任务；
- 计划或正在修改的范围；
- 已完成的变更；
- 用户已经作出的决定；
- 在工作开始前查询状态，在重要变化后更新状态；
- 在合并前发现文件、函数或 API 重叠。

Lv2 要求进一步回答：

- 协调粒度是文件、目录、符号、模块所有权、接口契约，还是多层组合；
- Agent 崩溃后的资源恢复和死锁处理；
- 决策、参数、格式和已知失败怎样定向传播，避免上下文噪声；
- 与单 Agent、独立 Worktree 多 Agent、采用协调机制的多 Agent 做同任务比较；
- 衡量耗时、Token、冲突、人工合并、测试通过率，并诚实记录退化。

Lv3 可选方向包括跨厂商/跨机器、人类介入和动态任务拆分。Bonus 是可回放的全局事件时间线，以及依赖和等待可视化。

### 2.3 与现有共识的匹配程度

| 原题要求 | 当前项目共识 | 契合度 | 需要补强 |
|---|---|---:|---|
| 多 Agent 共享状态 | 中心项目状态与持久化 | 高 | 定义稳定的内部领域模型 |
| 提前发现范围/API 冲突 | 意图、租约、契约、认知协商 | 高 | 区分声明式发现、事后检测和真正强制 |
| 决策传播且控制噪声 | 按影响范围组织协商 | 高 | 订阅、受影响方计算、上下文预算 |
| 崩溃恢复和死锁 | 已将租约纳入范围 | 中 | fencing token、原子领取、恢复语义 |
| 同任务定量对照 | 尚未固化实验设计 | 中 | 建立可复现实验工具链和评分规则 |
| 至少 3 个 Agent 的冲突任务 | 产品 MVP 首先证明 2 个 Agent 的认知闭环 | 中 | 分开“产品 MVP”和“原题验收”：原题演示必须用 3 个 Agent |
| 跨厂商 Agent | 首批兼容 2–3 种 Coding Agent | 高 | 用适配器能力矩阵验证，而不是假定协议完全一致 |
| 人类介入 | 当前不是核心产品范围 | 低但不冲突 | 保留 `input_required`/审批状态，不建设完整 UI |
| 动态任务拆分 | 当前不是首要价值 | 低但不冲突 | 作为后续 Planning 能力 |
| 时间线回放 | 中心持久化已有方向 | 高 | 领域事件日志必须从第一版开始设计 |

### 2.4 对原题开放问题的当前回答

| 原题问题 | 当前判断 |
|---|---|
| 中心化还是点对点 | 首阶段采用本机中心协调服务作为权威状态源；Agent 可以直接交换工作消息，但正式任务、契约、租约和决定必须回写中心状态。跨机器后再评估联邦或点对点复制。 |
| Agent 自愿协作还是运行时强制 | 两者并存并明确分级。认知报告主要依赖 Agent 配合；状态机和经由受控工具的操作可强制；Full Access 下不能承诺拦截所有行为。 |
| Worktree 何时更合适 | 高风险、长轨迹、边界较清楚、尚未完成契约协商或失败成本高时优先。低风险且频繁共享中间结果的工作可用共享目录。最终策略应由任务风险和实验数据决定。 |
| 自然语言还是结构化协议 | 使用“结构化外层 + 自然语言理由”。身份、任务、版本、影响范围和接受状态结构化；推理、假设、不确定性和替代方案保留自然语言。 |
| 协调 Agent 与执行 Agent 的关系 | Planning 是可转移角色，不是常驻超级用户。运行时负责确定性规则，Planning Agent 负责依赖和语义判断，执行 Agent 保有提出异议和修订契约的能力。 |
| 怎样分层观测 | 不可变领域事件用于审计和回放；物化视图用于当前状态；OTel traces/metrics/logs 用于性能与跨组件关联；面向用户的时间线只呈现经过整理的领域事件。 |

## 3. 外部研究的关键发现

### 3.1 A2A 与 MCP 分处不同层次

[A2A v1.0](https://a2a-protocol.org/latest/specification/)面向彼此独立、内部实现不透明的 Agent 系统。它提供 Agent Card、能力发现、Message/Part/Artifact、长任务生命周期、流式更新、推送和 JSON-RPC/gRPC/HTTP+JSON 绑定。A2A 的任务状态和上下文标识很适合跨系统委派与跟踪。

[A2A 官方对 A2A 与 MCP 的解释](https://a2a-protocol.org/latest/topics/a2a-and-mcp/)也明确区分：MCP 连接模型或 Agent 与工具、资源；A2A 连接相互独立的 Agent。

对本项目的判断：

- A2A 可作为未来的外部 Agent 网关或 Lv3 互操作接口；
- A2A Task 不应直接成为内部项目任务的唯一真相源，两者的所有权、生命周期和细粒度不同；
- A2A 没有定义文件意图、代码范围、租约、契约接受者、冲突证据或事件溯源；
- 首阶段为本机 Coding Agent 建完整 A2A 栈，收益低于先做 MCP 与原生钩子适配。

### 3.2 MCP 是首阶段最现实的通用接入面，但不能承担核心状态

截至研究日期，[MCP 当前协议版本为 2026-07-28](https://modelcontextprotocol.io/specification/versioning)。这一版本变为无会话协议，采用每请求能力信息和 `server/discover`；异步 Tasks 被移到可选扩展；Roots、Sampling 和 Logging 被标记弃用。官方对 Roots 的解释很关键：它采用率低、语义只是“信息性指导”，服务器并不必然遵守，并且可由工具参数、资源 URI、服务配置或环境变量替代。参见 [SEP-2577](https://modelcontextprotocol.io/seps/2577-deprecate-roots-sampling-and-logging)与[版本变更](https://modelcontextprotocol.io/specification/2026-07-28/changelog)。

这意味着：

- 项目范围必须存放在本系统的 `Workspace/Scope/Authority` 模型里，不能依赖 MCP Roots；
- 首版 MCP 能力应基于最低共同能力：工具发现/调用与资源读取；
- 长任务不能假设每个宿主都支持 [MCP Tasks 扩展](https://modelcontextprotocol.io/extensions/tasks/overview)，内部任务仍由本系统持久化；
- 不同 Agent 可能只支持较旧的 MCP 版本，适配器必须做版本与能力协商；
- 目录范围通过受版本控制的项目清单、显式工具参数或资源 URI 表达；它是协调范围，是否构成强制边界取决于 Agent 的沙箱和钩子能力。

### 3.3 三类候选 Coding Agent 的接入可行性

| Agent | 已核实的接入面 | 可达到的治理强度 | 结论 |
|---|---|---|---|
| Claude Code | [MCP](https://docs.anthropic.com/en/docs/claude-code/mcp)、[PreToolUse/PostToolUse 等 Hooks](https://docs.anthropic.com/en/docs/claude-code/hooks)、任务与队友事件 | 可在工具调用前后检查、拒绝或补充上下文；仍取决于 Hook 覆盖面和用户权限 | 最适合做首个深适配器 |
| OpenCode | [本地/远程 MCP](https://opencode.ai/docs/mcp-servers/)、[插件事件和 `tool.execute.before/after`](https://opencode.ai/docs/plugins/) | 可观察会话、文件、权限和工具事件，并在工具层约束 | 适合验证第二种深适配器 |
| Codex CLI | 本机 `codex-cli 0.154.0-alpha.6.2` 已核实 `codex mcp`、`exec`、`--cd`、`--add-dir`、sandbox、worktree 等启动能力 | MCP 可做通用交互；实际强制程度需按当前版本和启动模式实测 | 适合验证通用 MCP + 进程启动适配 |

OpenAI Docs 页面在本次研究环境中被站点返回 403，因此 Codex 一行只记录了本机 CLI 帮助实际可见的能力，不将其外推为所有版本的稳定承诺。实施时应把版本探测结果写入 `AgentSession.capabilities`。

### 3.4 厂商原生多 Agent 已验证需求，但没有消除项目空间

[Claude Code Agent Teams](https://docs.anthropic.com/en/docs/claude-code/agent-teams)已经提供中心 lead、独立上下文、共享任务列表和 Agent 间消息，说明“共享任务 + 定向消息”是实际需要。其文档同时表明该能力仍属实验性，并列出会话恢复、任务协调、关闭、固定 lead、单会话单 team 等限制；文档的最佳实践仍要求主动避免文件冲突。

这说明本项目不能只做另一个厂商内置 team：差异化应落在跨厂商、跨项目目录、可版本化认知契约、隔离策略无关、明确的执行强度和可回放评估上。

### 3.5 新研究支持“协调 + 隔离”，不支持“共享目录必胜”

2026 年论文 [Effective Strategies for Asynchronous Software Engineering Agents](https://arxiv.org/abs/2603.21489)提出 CAID：中心化依赖感知委派、异步执行、Worktree 隔离、commit/merge 集成和测试门禁。论文报告相对单 Agent 在 PaperBench 上提升 25.6 个百分点，在 Commit0 上提升 14.7 个百分点。

更关键的是其消融结果：

- PaperBench：单 Agent 57.2，软隔离共享区 55.5，Worktree 隔离 63.3；
- Commit0-Lite：单 Agent 53.1，软隔离共享区 56.1，Worktree 隔离 59.1；
- Agent 数量从 2 增加到 4 在部分任务上改善，从 4 增至 8 则因任务过细、冲突和集成成本下降；
- 多 Agent 成本始终更高，端到端 wall-clock 并未因并行而显著降低，原因之一是集成和测试仍然串行。

因此项目的研究机会不是否定 Worktree，而是验证显式认知契约和更早的依赖同步，能否减少 CAID 仍存在的集成等待、错误委派和重复验证。

### 3.6 黑板系统适合解释共享状态，但实现必须强类型化

Nii 的经典[黑板系统论文](https://doi.org/10.1609/aimag.v7i2.537)描述了多个独立知识源围绕共享黑板贡献部分解、由控制组件选择机会性推进的架构。本项目中的项目状态、Agent 报告和可变 Planning 角色与此高度相似。

建议借鉴“共享事实面 + 独立贡献者 + 控制策略”，但不采用一个所有 Agent 任意覆写的大文档。黑板应实现为：

- 有类型、可版本化的记录；
- 追加式事件和可重建视图；
- 乐观并发版本；
- 清晰的作者、证据、适用范围和失效关系；
- 只有确定性校验由运行时完成，语义结论仍由 Agent 协商。

### 3.7 租约能处理崩溃恢复，但不能自动提供文件系统强制

Gray 与 Cheriton 的[租约论文](https://doi.org/10.1145/74850.74870)提出以有期限的授权降低故障恢复难度。它适合任务领取、端口、测试环境、数据库实例和编辑范围预留。

首版租约至少需要 `resource_id`、`holder`、`mode`、`issued_at`、`expires_at`、`fencing_token` 和状态。TTL 只会让旧租约过期；如果旧进程仍能直接写文件，它仍可能产生过期写入。只有当所有写操作经过可校验 fencing token 的工具代理，或 Agent 处于 OS/容器强制边界内，租约才具有严格强制力。否则它是协作协议和检测依据。

避免死锁的首版策略应简单：多资源请求按稳定顺序一次性原子领取，失败则不保留部分资源；等待设上限并记录等待图。不要一开始实现复杂分布式锁管理器。

### 3.8 CRDT、Difftastic、Git Worktree 和 OpenTelemetry 各自只解决一部分问题

- [CRDT](https://crdt.tech/)适合多副本离线编辑和自动收敛。首阶段是本机中心化协调器，CRDT 会增加复杂度，而且“状态收敛”无法判断哪个 API 契约在语义上正确。它可在未来用于评论、标注等可合并数据，不适合作为任务、权限、租约和正式决策的核心模型。
- [Git Worktree](https://git-scm.com/docs/git-worktree)是成熟的隔离执行器。它能为一个仓库提供多个工作树，但不能传播意图、认知或契约；跨仓库项目还需要每仓库分别管理。`git worktree lock` 是 Worktree 生命周期保护，不是代码编辑租约。
- [Difftastic](https://difftastic.wilfred.me.uk/)用 tree-sitter 生成结构化语法 diff，适合压缩变更上下文和提供冲突证据。它不是合并引擎，也不能判断业务契约是否兼容。
- [OpenTelemetry 的 Agent 可观测性建议](https://opentelemetry.io/blog/2025/ai-agent-observability/)支持统一 traces、metrics、logs 和语义约定。OTel 适合导出和跨组件关联，但不能替代不可丢失、可回放的领域事件日志。

### 3.9 SQLite 适合本地中心存储，但需要单写入者模型

[SQLite WAL](https://www.sqlite.org/wal.html)允许读写并发，但所有进程必须在同一主机，且不适合网络文件系统；SQLite 每个数据库仍只有一个并发写入者。它与“本机协调服务统一写、多个 Agent 经 API/MCP 访问”的形态正好匹配。

建议将中心状态保存在用户选择的本地中心目录，以 SQLite 保存事实和物化视图，并将大体积附件、快照和 diff 放在内容寻址的文件存储中。多个 Agent 不应直接写数据库文件。跨机器阶段再评估客户端/服务器数据库。

## 4. 推荐的一级模块划分

建议划分为 8 个一级业务模块。它们是同一个 Python 模块化单体中的边界，不是 8 个独立服务。

### 4.1 项目空间与权限域

负责项目、多个目录/仓库、资源 URI、用户授权范围、Agent 实际能力范围和中心保存位置。它回答“这个项目包含什么、这个 Agent 被配置为能做什么、该范围是否被真正强制”。

### 4.2 Agent 接入与运行时管理

负责 Agent 身份、会话、能力探测、启动/附着、心跳、MCP 接口、厂商 Hooks/Plugin 适配和进程退出。每个适配器要上报支持的通信、观察和强制等级。

### 4.3 任务图与调度

负责任务、依赖、领取、交接、阻塞、取消和完成条件。Planning 是可由任意 Agent 承担的角色；运行时只维护合法状态与依赖关系。

### 4.4 认知报告、协商与契约

负责 Agent 主动提交的理解、假设、不确定性、问题、提议、接受/反对和版本化契约。只对结构化声明做确定性比对，不在首版主动推断未声明的隐含分歧。

### 4.5 资源协调与冲突检测

负责意图声明、范围重叠、任务/文件/目录/符号/环境资源租约、心跳续租、等待图和冲突案例。文件和目录是首版可靠粒度；符号级引用和语义冲突作为证据与提示，不能假装是严格锁。

### 4.6 工作空间与隔离驱动

负责共享目录、Git Worktree 和后续容器等策略的统一接口，以及基线版本、变更收集和集成状态。策略由用户或主 Agent 按风险选择，协调内核不绑定单一隔离模式。

### 4.7 持久化与事件回放

负责追加式领域事件、事务性状态更新、快照、迁移、恢复、内容存储和重建物化视图。所有正式决定必须能追溯到事件和参与者。

### 4.8 可观测性与实验评估

负责时间线、等待原因、冲突解决、Token/费用、Agent 活跃时间、测试结果和 OTel 导出。它同时支撑原题的定量对照和未来 Web 工作台，但首版不需要建设 Web UI。

## 5. 核心领域记录

以下记录应属于内部协议，不能由 A2A 或 MCP 对象直接代替：

| 记录 | 核心含义 |
|---|---|
| `Project` | 用户定义的一项工作及其中心存储位置 |
| `WorkspaceRoot` | 项目包含的一个目录；可关联零个或一个 Git 仓库 |
| `AuthorityEnvelope` | 用户授予的范围、Agent 自身沙箱范围和实际强制等级 |
| `AgentSession` | Agent、版本、适配器、能力、心跳和当前角色 |
| `Task` / `Dependency` | 工作项、前置条件、状态、交付物和负责人 |
| `IntentClaim` | 将要读取/写入/变更的资源范围和基线版本 |
| `Lease` | 有期限的资源占用及 fencing token |
| `EpistemicReport` | 理解、假设、不确定性、问题和证据 |
| `Contract` | 版本化接口、参与者、适用任务、接受状态和替代关系 |
| `ConflictCase` | 冲突类型、证据、影响方、状态和解决结论 |
| `Decision` | 用户或 Agent 已确认的正式选择及影响范围 |
| `Artifact` | 代码提交、patch、测试结果、文档或其他输出引用 |
| `DomainEvent` | 所有重要状态变化的不可变审计记录 |

结构化字段用于机器比较和订阅，自然语言用于理由、语义和不确定性。二者必须同时保留，但要为自然语言设上下文预算和定向接收者，避免把全量聊天广播给所有 Agent。

## 6. 认知分歧闭环

首版最关键的产品闭环应当是：

1. Agent 加入项目并读取与任务相关的快照。
2. Agent 提交 `EpistemicReport` 和 `IntentClaim`，显式声明理解、假设、不确定性、计划范围和公共契约影响。
3. 运行时比对结构化字段，发现同一契约版本、任务前置条件或写范围不兼容。
4. 系统创建 `ConflictCase`，只通知受影响的 Agent 和当前 Planning 角色。
5. Agent 提交提议、反对或反提议；运行时记录每一步，不替 Agent 判断业务正确性。
6. 所需参与者接受后生成新 `Contract` 或 `Decision` 版本。
7. 被该分歧阻塞的任务恢复，其他任务继续。
8. 实施结果引用契约版本并提交验证证据；违反契约则重新打开冲突。

首版成功标准不是“系统猜出 Agent 没说出口的误解”，而是“Agent 明确提交后，系统不丢失、不漏通知、不让相互矛盾的正式契约同时生效”。

## 7. 运行时强制等级

必须避免把“已记录范围”宣传成“已强制范围”。建议每个 Agent 会话显示以下能力等级：

| 等级 | 能力 | 能保证什么 |
|---|---|---|
| E0 通知型 | Agent 自愿调用 MCP/CLI 更新状态 | 只能协调，无法阻止绕过 |
| E1 观察型 | 文件监视、Git 状态、工具后置钩子 | 能发现部分未声明变化，通常是事后 |
| E2 工具门禁型 | 工具前置钩子、受控命令代理、租约校验 | 能拦截经过覆盖工具面的操作 |
| E3 隔离型 | Agent 沙箱、Worktree、容器或 OS 权限边界 | 能在配置范围内形成更强执行边界 |

Full Access 模式下仍可进行 E0/E1 协调，但系统必须明确声明它没有完整拦截能力。Windows 首发还需专门验证大小写归一化、盘符、UNC、junction/reparse point 和符号链接造成的范围逃逸或重复资源标识。

## 8. 可行性和主要风险

| 项目 | 可行性 | 主要风险 | 建议 |
|---|---:|---|---|
| 中心项目状态与事件日志 | 高 | 模型过早泛化、事件与视图不一致 | 先围绕验收闭环建最小领域模型 |
| MCP 通用适配 | 高 | 客户端协议版本和可选能力差异 | 能力协商、最低共同能力、契约测试 |
| Claude/OpenCode 深钩子 | 高 | Hook/Plugin 版本变化或覆盖不全 | 插件版本化并报告 enforcement grade |
| Codex 接入 | 中高 | 官方页面本次不可访问，当前本机版本为 alpha | 以运行时探测为准，不固化版本假设 |
| 文件/目录范围冲突 | 高 | 重命名、生成文件、跨根路径 | 稳定资源 ID + 版本基线 + watcher 补偿扫描 |
| 符号级冲突 | 中 | 多语言解析、动态语言、代码生成 | 先做提示证据，不作为强制锁 |
| 认知契约协商 | 中高 | Agent 不按模板提交、上下文膨胀 | 短结构化报告、按影响订阅、字段校验 |
| 强制权限 | 依适配器而异 | Full Access 或直接 Shell 可绕过 | 明示 E0–E3，不作虚假强制保证 |
| 跨仓库原子变更 | 中低 | Git 无原生跨仓库事务 | 用协调事务与补偿状态，不声称 Git 原子性 |
| 相对 Worktree 基线的效率优势 | 未知 | 集成仍串行、协调 Token 和等待增加 | 必须通过多轮基准和消融验证 |

## 9. 原题验收的实验设计

### 9.1 分开两个验收目标

- 产品 MVP：2 个 Agent 发现显式理解分歧，形成契约，并继续完成任务。
- 原题/研究验收：至少 3 个 Agent，在会发生真实代码与契约冲突的中型仓库完成同一复杂任务。

### 9.2 建议任务

选择一个中型 Python 项目，实施“可取消的长任务 + 状态订阅 + 持久化恢复”。拆成领域状态机、持久化迁移、协议/CLI 适配、测试与文档等子任务。它会自然产生：

- 多个 Agent 同时修改任务状态枚举和公共类型；
- API 参数与返回格式契约；
- 数据库迁移与恢复语义；
- 共享测试夹具和配置文件；
- 任务取消、崩溃恢复和并发更新的设计分歧。

不要人为制造只靠编辑同一行即可触发的冲突；目标是让局部合理、整体不兼容的方案自然出现。

### 9.3 对照条件

| 条件 | 描述 |
|---|---|
| A | 单 Agent 串行完成全部任务 |
| B | 3 个 Agent 使用独立 Worktree，只在最后或固定检查点合并 |
| C | 3 个 Agent 使用本协调系统，隔离策略按任务选择 |
| D（消融） | 与 C 相同，但关闭认知报告/契约协商，只保留任务和文件范围协调 |

D 能回答核心增量价值究竟来自一般调度，还是认知协作本身。

### 9.4 控制变量

- 固定仓库快照、任务文本、测试环境、依赖缓存和总预算；
- 同一 Agent/模型组合在各条件间保持一致；
- 随机化条件执行顺序，避免缓存和操作者学习偏差；
- 每个条件先做 2–3 次试运行，再至少做 5 次正式运行；
- 所有失败都计入，不因“Agent 状态不好”剔除；
- 跨模型 Token 不直接混算，分别记录输入、输出、费用和工具调用量。

### 9.5 指标

结果质量：隐藏测试通过率、功能完成率、契约一致性、回归数。

效率：wall-clock、所有 Agent 累计活跃时间、集成等待时间、验证时间、费用和 Token。

协调：重复实现量、意图重叠次数、冲突发现时点、晚期合并冲突、契约重开次数、人工介入分钟数。

认知闭环：注入或自然产生的分歧是否在代码冲突前被发现、从发现到达成契约的时间、受影响任务是否正确阻塞、无关任务是否继续、最终实现是否引用并遵守同一契约版本。

### 9.6 预先声明的假设

以下只能作为待验证假设：

- C 的测试通过率不低于 B；
- C 相比 B 更早发现 API/设计分歧，并减少人工合并时间；
- C 的协调额外 Token 有上限，且不会抵消质量收益；
- D 的表现低于 C，从而证明认知报告/契约不仅是附加记录。

不建议在第一次实验前设定一个营销式固定提升百分比。先用试运行获得方差，再确定有统计意义的 go/no-go 门槛。

## 10. 推荐推进顺序

### 阶段 0：实验与协议骨架

定义内部领域对象、事件格式、能力等级和基准任务；先做可手动驱动的命令/API，不绑定 Web 框架。

### 阶段 1：认知协作最小闭环

实现项目/多根目录、Agent 会话、任务、认知报告、契约、冲突案例、定向通知和事件回放。用两个 Agent 完成产品 MVP。

### 阶段 2：三 Agent Lv1/Lv2 验证

加入意图范围、文件/目录租约、心跳恢复、依赖等待、Git 变更采集和三 Agent 对照实验。共享目录和 Worktree 至少各跑一种配置。

### 阶段 3：适配器通用性

完成 2–3 个 Agent 的能力矩阵与契约测试：至少一个仅依靠 MCP，一个使用深钩子，一个由系统启动并配置工作目录/隔离方式。

### 阶段 4：可选扩展

根据实验结果选择 A2A 网关、跨机器、人类审批 UI、动态任务拆分和 OTel 后端。A2A 不应成为阶段 1 的阻塞项。

## 11. 已形成的研究判断

以下可以进入后续正式设计：

1. 采用中心协调平面，执行空间允许共享目录、Worktree 和其他隔离方式并存。
2. 内部领域协议是权威状态；MCP 和 A2A 都是边界适配协议。
3. 首版优先 MCP 基础工具/资源，不依赖已弃用 Roots 或支持不一的 Tasks 扩展。
4. 项目范围用多 `WorkspaceRoot` 表达，中心存储位置与代码目录解耦。
5. 认知协调只处理 Agent 显式提交的理解、假设、不确定性和契约。
6. 事件日志是产品核心，不是仅用于调试的附属日志；OTel 是导出层。
7. 租约按 E0–E3 能力等级解释，不能在 Full Access 下声称绝对强制。
8. 文件/目录是首版主要协调粒度，符号级信息先作为建议和冲突证据。
9. 首阶段使用 Python 模块化单体和本机单写入者持久化最合理。
10. 产品 MVP 用 2 个 Agent，原题验收使用至少 3 个 Agent，并包含 Worktree 对照和认知协作消融。

## 12. 尚未决策的问题

- 第一批 2–3 个正式支持的 Agent 及其最低版本；
- MCP 的兼容版本矩阵与是否提供 stdio、Streamable HTTP 两种传输；
- Python Web/API 框架与进程模型；
- 中心目录的默认位置、项目清单格式和附件保留策略；
- 首版是否实现工具门禁 E2，还是先交付 E0/E1；
- Worktree 集成由系统创建还是只登记已有 Worktree；
- 认知报告与契约的最小字段集；
- 基准仓库、预算和人工评分规则。

## 13. 资料索引

### 原题与附录

- [Agent 协同方法探索](https://join.geek-tech.club/problems2/agent-to-agent)
- [A2A Protocol](https://a2a-protocol.org/latest/)
- [Model Context Protocol](https://modelcontextprotocol.io/specification/versioning)
- [Git Worktree](https://git-scm.com/docs/git-worktree)
- [Blackboard Systems, Part One](https://doi.org/10.1609/aimag.v7i2.537)
- [Leases: an efficient fault-tolerant mechanism](https://doi.org/10.1145/74850.74870)
- [CRDT](https://crdt.tech/)
- [Difftastic](https://difftastic.wilfred.me.uk/)
- [OpenTelemetry: AI Agent Observability](https://opentelemetry.io/blog/2025/ai-agent-observability/)

### 补充研究

- [MCP 2026-07-28 Key Changes](https://modelcontextprotocol.io/specification/2026-07-28/changelog)
- [MCP SEP-2577](https://modelcontextprotocol.io/seps/2577-deprecate-roots-sampling-and-logging)
- [MCP Tasks Extension](https://modelcontextprotocol.io/extensions/tasks/overview)
- [A2A and MCP](https://a2a-protocol.org/latest/topics/a2a-and-mcp/)
- [A2A Life of a Task](https://a2a-protocol.org/latest/topics/life-of-a-task/)
- [Claude Code Agent Teams](https://docs.anthropic.com/en/docs/claude-code/agent-teams)
- [Claude Code Hooks](https://docs.anthropic.com/en/docs/claude-code/hooks)
- [OpenCode Plugins](https://opencode.ai/docs/plugins/)
- [Effective Strategies for Asynchronous Software Engineering Agents](https://arxiv.org/abs/2603.21489)
- [SQLite Write-Ahead Logging](https://www.sqlite.org/wal.html)
