# 实现规划决策账本：第二轮

> 日期：2026-09-17。
> 范围：承接 [implementation_decisions.md](./implementation_decisions.md)，持续记录第 28 题之后的用户确认结果。
> 状态：本文件中的“已确认”是后续详细实现计划的约束；若与早期建议冲突，以本文件标明的最新选择为准。
> 依赖与工具链的注册表核对见 [technology_stack_research.md](./technology_stack_research.md)。

## 决策索引

| 编号 | 决定 | 核心约束 |
|---|---|---|
| D33 | 扁平任务状态机与开放领取 | 单一 owner；不使用 offer；所有合格 Agent 可原子 claim open 任务。 |
| D34 | 不可变 TaskAttempt 与完整 preflight | claim 创建 attempt；工作区、报告、契约、权限与租约齐备后才 running。 |
| D35 | 策略化验收、返工与终态 | submitted 后按任务策略验收；返工创建新 attempt；completed 不重开。 |
| D36 | 两阶段取消、阻塞与失联恢复 | cancel_requested、blocked、orphaned 均有独立恢复/收敛语义。 |
| D37 | 关键边界认知报告 | 报告为不可变结构外层加自然语言；更新以 supersedes 连接。 |
| D38 | 确定性分歧检测与影响传播 | 首版不使用 LLM 推断隐含分歧；hard 分歧沿影响/依赖图阻塞。 |
| D39 | 多提案、逐一接受的不可变契约 | 必要参与者对同一哈希逐一接受；用户 override 不伪装成共识。 |
| D40 | ResourceIntent 与 Lease 分离 | 多资源全取或全不取；等待按优先级与年龄；不自动抢占。 |
| D41 | lease_id 校验与后台心跳 | 不采用 fencing token；30 秒续租、120 秒 TTL；外部写入只告警。 |
| D42 | shared/worktree/external 三驱动 | Worktree 仅正式支持单仓库；external 只附着既有环境。 |
| D43 | 主 Agent LLM 风险评估 + 内核硬约束 | 自动选择隔离驱动，输出结构化理由；权限和能力硬约束不可绕过。 |
| D44 | Git 工作区基线、结果与清理 | Worktree 基于干净 commit；结果附变更证据；checkpoint 后显式清理。 |
| D45 | 每项目 SQLite 与单写者 | `.tsunagou/local/state.sqlite3`；OS 锁、每项目单写队列、并发读。 |
| D46 | WAL + FULL、迁移备份与分层保留 | 自动前向迁移前备份；失败只读；领域历史永久，运行明细默认 30 天。 |
| D47 | SQLite 持久作业与同事务 outbox | 进程内 worker；正确性不依赖内存队列或外部 broker。 |
| D48 | 宿主薄桥接 + 核心 REST/SSE | 核心不加载厂商 SDK；SSE 只发变化信号，权威内容经 REST 拉取。 |
| D49 | 能力探测、版本窗口与故障降级 | 静态上限加运行探测；只正式支持已测试版本窗；Hook 故障按强度处理。 |
| D50 | 类型化工具与桥接代持凭据 | 模型不接触 bearer token；安装只维护可回滚的托管配置区块。 |
| D51 | 附着为共同基线、托管启动为增强 | 只终止系统自己启动的进程；attached 进程只撤销协调权限。 |
| D52 | 模块内分层、每命令 UoW、轻量 CQRS | 八模块通过应用端口/已提交事件协作；事务内不做外部副作用。 |
| D53 | 源码运行 monorepo | 显式登记 checkout；生成协议产物提交 Git 并检查漂移。 |
| D54 | 短期凭据原方案（被 D93 收缩） | 保留随机 loopback、一次性票据和可撤销原则；首发取消 access/refresh token 轮换与系统凭据库集成。 |
| D55 | 本机 control token（被 D93 收缩） | 保留独立 control principal；首发无 Web 工作台并关闭 CORS，浏览器认证延后设计。 |
| D56 | 结构化日志、OTel 与受限内容采集 | 默认只记元数据；未知模型不估 token；真实 Agent 首版手工验收。 |
| D57 | 微基准与真实仓库四组实验 | 固定主实验后跨宿主复验；采用正确性优先的预注册门槛。 |
| D58 | 协调 Git 仓库与受保护元数据 | 一个协调仓库承载 `.tsunagou`；任务 Worktree 不得修改协调数据。 |
| D59 | 项目归档、删除与本机备份 | checkpoint 后只读归档；删除默认只注销；永不删除项目源码。 |
| D60 | 兼容范围、精确锁与 Schema-first | Python/Node 声明兼容范围并精确锁定；JSON Schema 2020-12 是协议源；Python 3.13 的 UUIDv7 由封装后的 `uuid6` 提供。 |
| D61 | Node 24、pnpm 12 与 TypeScript 7 | 首版固定 Node 24 兼容窗、用户态 Corepack/pnpm 和 strict ESM；codegen 工具各自拥有明确输出边界。 |
| D62 | SSE 高水位信号 | SSE 只发送可合并的变化提示；可靠内容经 REST 拉取并显式 ACK，不建立独立 SSE 重放表。 |
| D63 | Operation、Job 与副作用恢复 | 异步副作用由持久 Operation/Job 承载；幂等键绑定请求哈希；不可验证结果进入 outcome_unknown。 |
| D64 | Job 调度与恢复默认值 | 4 worker、60 秒 lease/15 秒 heartbeat、最多 5 次尝试及 full-jitter；lease 过期先 reconcile。 |
| D65 | 主 Agent 风险建议与内核隔离裁决 | 风险请求绑定不可变输入摘要；模型提交建议，内核验证时效与硬约束后生成最终 IsolationDecision。 |
| D66 | 风险评估超时与确定性 fallback | 在线等待 120 秒并有限提醒；离线立即保守裁决；无法唯一安全选择时保持 claimed/preflight。 |
| D67 | Monorepo 与八模块物理边界 | 单一 Python src distribution + pnpm adapters；模块自有表/仓储，只经 public ports 或已提交事件协作。 |
| D68 | Typer + Rich CLI | 类型化命令树服务人类操作；JSON stdout、stderr、退出码和异步等待语义保持脚本稳定。 |
| D69 | 按作用域分层配置 | shared/local/user TOML 与 SQLite 状态分离；配置按字段合并，本机层只能绑定或收紧，秘密不进入配置。 |
| D70 | REST/MCP 传输原生命令投影 | REST 使用 ETag/If-Match，MCP 使用 expected_revision；两者映射到同一内部 envelope/hash。 |
| D71 | 统一跨语言 JSON profile | 全协议 snake_case；安全整数、UTC 毫秒、UUID/hash/null 均使用唯一规范表示。 |
| D72 | 签名 Keyset Cursor 分页 | 通用列表用短期 HMAC opaque cursor 和稳定排序；事件时间线直接使用 after_seq，不承诺跨页历史快照。 |
| D73 | 逐接收者响应 Obligation | request 为 required/optional recipient 建义务；合法 response/domain evidence 满足义务，领域模块决定业务完成。 |
| D74 | 保守 at-least-once 消息投递 | fetched 前可重投，fetched 后不重复注入正文；使用有界 lease/batch/backpressure，永久错误才 dead-letter。 |
| D75 | 有界版本协商与独立格式迁移 | 产品统一发版；实时协议支持 current/N-1；schema bundle 精确绑定；共享格式与 SQLite 独立前向迁移。 |
| D76 | 单一原子 Codegen 流水线 | Python 编排器调用锁定工具，在 staging 中完成 lint/generate/fixtures/manifest/check；公开 DTO 限制为已验证 schema 子集。 |
| D77 | Python 窄兼容窗口与精确锁 | 首版正式支持 CPython 3.13；核心 0.x 依赖锁 minor、稳定库锁 major；`uv.lock` 是唯一已验证组合。 |
| D78 | 单活动项目副本 | clone 继承项目/谱系身份但获得新 replica；本机同一谱系只允许一个可写 replica，切换需 checkpoint，异常接管开启新 runtime epoch。 |
| D79 | 逻辑项目与历史代次分离 | project_id 跨普通恢复保持稳定；回滚/重置创建新 lineage；独立 fork 同时创建新 project 与 lineage，并记录来源。 |
| D80 | 初始化后立即活动、Git 锚点延后 | init 物化成功即允许本机协作；Git durability 独立标为 unanchored，后续提交中的有效 checkpoint 才建立可恢复锚点。 |
| D81 | 本地覆盖与远端发布分离 | 本地 commit anchor 与远端 ref publication 是两个带证据时间的状态轴；本地锚定不宣称跨机器可恢复。 |
| D82 | 混合本地 Anchor 发现 | 后台发现与显式 verify 共用只读验证器；高影响操作强制刷新，只有本地 branch/tag 可达且完整校验的 checkpoint 可提升覆盖度。 |
| D83 | 主 Agent 控制 Git 执行面 | daemon 不修改 Git 或访问 remote；当前主 Agent 在 Full Access 宿主中执行本地/远端 Git，并向调度中心提交结构化结果。 |
| D84 | 主 Agent Git 分级自治 | 常规 additive/fast-forward Git 可自主执行；丢弃工作、重写已发布历史或删除远端 ref 必须由用户批准精确 intent。 |
| D85 | 多仓库状态向量与 Saga | TaskAttempt 绑定不可变 repository vector；多仓库 Git 由 parent/child Operation 顺序执行，部分成功进入 reconcile 而非伪回滚。 |
| D86 | 显式混合 Root/Repository Registry | 共享层声明逻辑身份，本机层绑定路径；发现只提议不自动登记；受限 non-Git root 可参与权限、租约与文件证据。 |
| D87 | Root 策略交集与物理资源身份 | 重叠仅限显式 parent/child；最具体 root 为 canonical URI，权限沿祖先链收紧，链接别名按物理键统一 lease。 |
| D88 | 用户上限内的 Root 委托管理 | 用户设置本机访问 ceiling；主 Agent在交集内管理普通 roots/绑定和任务子授权；扩大上限与高敏身份变更由用户决定。 |
| D89 | 主 Agent 交接冻结与逐项接管 | epoch 切换立即撤销旧管理/闲置授权；running grants 最多冻结 120 秒，新主 Agent按摘要等权或收窄 adopt。 |
| D90 | 正交 Project 状态与作用域 Blockers | lifecycle/authority/replica 分开；外部事实用 versioned conditions，命令可用性由带资源/动作 scope 的 blockers 决定。 |
| D91 | 显式首任主 Agent | init 产生 active + authority unassigned；用户任命已接入 Agent，或用专用一次性票据原子完成 attach+appoint，普通 join 永不自动升级。 |
| D92 | 主 Agent 单阶段任命 | 候选无需接受；任命/交接事务校验后立即切换 epoch 与管理权，通知仅作投递和审计，失败不回滚。 |
| D93 | 本机可信的最小认证 | loopback-only；control token 与逐 Agent session token 仅标识主体，服务端实时授权；无 OAuth/JWT/TLS/refresh，防误用与身份混淆而不抵御同用户 Full Access 恶意进程。 |
| D94 | 父子任务式委派 | 主 Agent保留父任务/attempt；可验收工作必须创建独立子任务，子 Agent只拥有子 attempt，其结果作为父任务输入，不能接管或直接完成父任务。 |
| D95 | 父任务显式等待子任务 | 创建子任务不自动改变父状态；父 owner 可继续 running 或显式 blocked 并释放租约，子任务变化只发通知，是否 resume 由父 owner 决定。 |
| D96 | 子任务不构成父任务门禁 | `parent_task_id` 只表达委派/追踪；系统不设 required/optional 或 bind-result 门禁，父 owner 自行判断充分性并在提交中引用采用的子结果。 |
| D97 | 父任务终态不级联子任务 | 父任务 completed/failed/cancelled 不取消、不暂停既有 descendants；它们独立继续，晚到结果不重开或改写父任务。 |
| D98 | 主 Agent集中创建子任务 | 仅 user/current main 可创建和发布 child task；普通 owner 通过消息提交 DelegationRequest，不能获得可转授的 task.create-child capability。 |
| D99 | 原子创建并开放子任务 | 常用 DelegateChildTask 在单一 UoW 完成校验、创建、open、事件和消息响应；失败无半成品，成功后由合格 Agent按 D33 竞争 claim。 |
| D100 | 主 Agent可重构委派请求 | DelegationRequest 可落实为零到多个新/既有 task refs 或拒绝；无需 requester 再接受，新任务与 resolution 在同一 UoW 原子提交。 |
| D101 | 单表当前状态授权 | authorization_grants 保存当前 active/frozen/revoked/expired 状态，变更写审计事件；scope/capability 不就地扩大，不建设不可变撤销实体与权限投影。 |
| D102 | Grant 随领域生命周期收敛 | 普通 grant 无默认 TTL/续期；Session、authority epoch、Attempt 状态变化同步撤销，授权实时复核关联状态，启动 reconcile 修正遗留行。 |
| D103 | 固定领域动作 Capability | 代码注册稳定 action IDs，scope/selectors 分离；无 wildcard、自定义策略或 endpoint/tool 权限，role template 只在签发时展开。 |
| D104 | 项目协调状态共享读取 | active project Agent 默认 project.read；任务/认知/契约/资源等非秘密状态项目内可读，inbox 正文仅收件人，秘密和本机敏感字段隔离。 |
| D105 | 按生命周期分层 Grant | agent_base、main_authority、task_attempt、task_review 分别承载成员、管理、执行和审查能力；动作要求指定 kind，不能跨 grant 拼接扩权。 |
| D106 | 静态 CommandPolicy 矩阵 | 每个 command 注册 principal、单一 capability、grant kind、固定 predicates 和 blocker action；所有传输共用，缺失注册时启动/CI 失败。 |
| D107 | 按 Grant kind 的类型化 Scope | 五类 grant 使用各自版本化 JSON Schema 与 JCS digest；关键关系另有外键列，不实现通用 selector 表达式或多资源 ACL 表。 |
| D108 | 正向 Root 路径前缀 | path rule 使用 root_id、read/write 与规范 segment prefix；空 prefix 为整 root，write 含 read，无 glob/deny/绝对路径，实际访问仍做物理校验。 |
| D109 | Task scope 到 Attempt scope 的交集派生 | Task 发布时固定 execution_scope；claim/preflight 与用户 ceiling、项目/root policy、主 Agent可委派范围和宿主能力取交集生成 EffectiveAttemptScope，ResourceIntent 不能扩权。 |
| D110 | 分层 ScopeExpansion 批准 | current main 可在自身可委派交集内批准 scope 扩大；超出主 Agent范围、user ceiling、高敏 root、coordination root 或信任边界时 user-only。批准生成新 revision、撤销旧 grant 并要求重新 preflight。 |
| D111 | Scope 批准单阶段生效 | main/user 批准事务提交即生成新 scope revision 并撤销旧 grant；通知 ACK 不构成门禁，owner 必须显式 resume/preflight 后继续。 |
| D112 | HostSession 恢复 | Agent/HostSession/Connection 三层分离；token、安装实例、统一 conversation ID 和 runtime 身份全匹配才恢复原 HostSession，仅递增 connection epoch；ID 细则由 D119 覆盖。 |
| D113 | 单一 Connection Epoch Fencing | 同一 HostSession 仅一个 current connection；新连接 CAS 递增 epoch 并 supersede 旧连接，旧命令/续租/ACK 在提交前返回 stale_connection。 |
| D114 | 无独立 Presence 心跳 | 首发不发 ConnectionHeartbeat、不用静默超时判离线；在线性仅来自传输/请求/lifecycle evidence，无证据为 unknown，授权和 Lease 生命周期独立。 |
| D115 | 明确宿主终止立即收敛 | verifier 确认 end/clear/detach/uninstall 后终止 HostSession并撤销凭据/grants，running attempts 立即 orphaned；主 Agent仅标 unavailable，不自动换届。 |
| D116 | Attach/Resume 能力快照 | 静态 descriptor 上限与每次连接 probe 取保守交集，生成不可变 CapabilitySnapshot；变化显式 reprobe，下降阻塞，上升不自动扩权。 |
| D117 | Probe 失败保留诊断会话 | mandatory baseline 缺失时 HostSession=degraded，仅允许 bootstrap/diagnostic/reprobe，无 agent_base、项目读取、inbox、task eligibility 或 main candidacy。 |
| D118 | 服务端版本化共同基线 | collaboration_baseline_v1 由服务端展开为原子 capability/evidence/strength 要求并计算 readiness；adapter boolean 不可信，profile 升级显式 reprobe/migrate。 |
| D119 | 统一宿主 Conversation ID | 四 adapter 必须提供稳定 host_conversation_id；同 installation 下 resume/compact 保持 ID，new/clear/fork 必须新 ID，core 存 keyed digest 并按精确相等判断连续性。 |
| D120 | 无稳定 Conversation ID 不得 Ready | identity continuity capability 为 unknown/unsupported 时只能 diagnostic degraded；禁止用户 override 或 bridge 文件 ID 冒充宿主对话身份。 |
| D121 | 随机持久 Adapter Installation ID | 每宿主用户 profile 安装/注册生成 UUIDv7，升级/重启保持，卸载/reset 重建；ID 非 secret，不授予权限，conversation identity 以其为作用域。 |
| D122 | 原子 Ticket 兑换与 Provisioning | RedeemEnrollmentTicket 单 UoW 消费票据并创建 provisioning Agent/HostSession/credential/snapshot；baseline 通过才 active+agent_base，失败保留 diagnostic degraded。 |
| D123 | Agent 单非终态 HostSession | 每 Agent 最多一个 probing/degraded/ready/disconnected session；正常 reconnect 复用，凭据丢失用 session_rebind_ticket 原子替换，同 conversation 再 enrollment 冲突。 |
| D124 | 显式 Agent 继任与新 Attempt | 继任只迁移选定未完成任务：旧 Attempt 收敛或失效，successor 新建 Attempt并重做 preflight；Lease、workspace、grant 和历史身份不转移，未决请求显式重路由。 |
| D125 | Handoff 是 Attempt 关闭原因 | `handed_off` 不新增 Task 状态；有停止证据时旧 Attempt 以该 close reason 终结，Task 指向新 Attempt；无停止证据仍为 orphaned 并阻塞冲突执行。 |
| D126 | 精确残余风险阻塞 | predecessor 未停止或副作用未知时生成 ResidualRiskSet；只阻塞相交动作，按既有 delegable/user-only 边界批准精确风险接受，输入变化即失效。 |
| D127 | 全量自动继承 Pending Obligations | Agent succession 自动为 successor 替换 predecessor 的全部 pending obligations；旧项 superseded，新项保留原规则与 deadline，身份和已发生响应不改写。 |
| D128 | 继任触发契约参与者重签 | predecessor 被 successor 替换时创建新 Proposal revision，参与者集合进入新 hash，全部 required participants 重签；生效 Contract 通过 superseding proposal 迁移。 |
| D129 | 原子替换并退休 Agent | `ReplaceAndRetireAgent` 单 UoW 完成必要 authority handoff、全量 succession、obligation/contract 迁移、撤权和退休；策略允许时 current main 可在边界内自我替换。 |
| D130 | 可恢复的 Retired Agent 身份 | retired Agent 可在原 installation/conversation 连续性通过验证后恢复同一 agent_id；退休期间凭据和授权仍失效，恢复权限与责任另行约束。 |
| D131 | 显式恢复且只恢复成员身份 | user 或具备 agent.reactivate 的 current main 可批准原 conversation 恢复；创建全新 Session/base grant，不恢复旧 authority、tasks、leases、obligations、contracts 或 approvals。 |
| D132 | 按责任范围解析 Succession DAG | 部分继任无全局唯一 successor；Task/obligation/contract 各按不可变 replacement 链解析，只有全量替换维护可重建 current_replacement_head。 |
| D133 | 时序 Succession 允许身份重复 | A->B 后可再 B->A；current responsibility 由 CAS 推进的 transition/head revision 决定，Agent ID 可重复，具体实体 replacement 链保持无环且历史不压缩。 |
| D134 | 批量 Succession 内部原子提交 | selector 先展开为 plan digest，全部 task/attempt/obligation/contract revision 一次复核并全有或全无提交；外部停止与 reconcile 在提交后逐项收敛。 |
| D135 | 继任逻辑提交与外部收敛分层 | 逻辑责任事务提交后立即可见；停止、Lease、workspace 和副作用核对由 Operation/Job 异步收敛，按有无外部工作返回 200/202。 |
| D136 | Outcome-unknown 精确阻塞 | 未知副作用只阻塞与 ResidualRiskSet 相交的动作；不相交和只读工作继续，解除 blocker 需要新的核对证据或风险接受。 |
| D137 | Outcome-unknown 可持续接受 | 主 Agent可在任务继续期间持续延长已登记风险接受，不把用户逐次确认作为默认门槛；每次延长保留摘要、理由和审计。 |
| D138 | 项目范围内无额外时限上限 | 风险接受可覆盖项目范围并持续到任务完成；硬性用户/project ceiling、禁止动作和重大方向变更仍不可突破。 |
| D139 | 主 Agent 默认自治混合模式 | 用户设定总体边界后，普通调度和技术决策由主 Agent自主执行；重大方向、最终完成、关键不可协调冲突和 ceiling 外请求形成用户确认点。 |
| D140 | 最小重大决策集合 | 默认只把项目设计/方向、重大目标或验收变更、任务最终完成、关键不可协调冲突、超出 ceiling 和用户明确保留事项列为用户门槛。 |
| D141 | 结构化重大决策包 | 主 Agent先提交背景、候选、推荐、影响、风险、可逆性和待确认项；确认前仅暂停依赖该决定的动作，无关工作继续。 |
| D142 | 持久依赖式决策阻塞 | 未确认不是计时器或超时；黑板持久记录依赖，受影响 Agent可提交阶段结果并挂起，无关 Agent继续。 |
| D143 | Attempt 可挂起可事件恢复 | Agent提交阶段结果、blocked_on 和恢复条件后，Attempt进入 blocked/suspended；对话可结束，依赖满足时产生恢复资格事件。 |
| D144 | Resume-eligible 由事件表达 | 依赖满足产生 `resume_eligible`；主 Agent/调度器可观察和排序，但不把资格直接当作安全执行许可。 |
| D145 | 原 Attempt 自主选择恢复 | 原 Attempt Agent自行决定何时提交恢复，不因空闲、无上下文或未响应被判定失败；系统不替它强制唤醒。 |
| D146 | ResumeAttempt 必须重新预检 | 主动恢复执行权限、scope、契约、风险、workspace 和资源 preflight；通过后继续原 Attempt，失败则保留 blocker。 |
| D147 | 恢复发现变化保留 Attempt | 资源、契约、权限或工作区变化只生成新的 typed blocker，原 Attempt保持不关闭，待材料更新后再次 resume。 |
| D148 | Blocked 仍允许协调写入 | blocked 只禁止受阻执行动作；原 Agent可提交认知报告、澄清、契约提案/接受、资源意图修订和 ResumeAttempt。 |
| D149 | 主 Agent可推进 Blocked 相关变化 | 项目策略与权限允许时，主 Agent可直接推进相关资源/执行条件和协调变化；所有 revision、理由和审计仍保留。 |
| D150 | 契约代行受项目策略控制 | 策略允许时主 Agent可代行适用契约决策；否则创建 Proposal并按 required participants 接受，不能用管理权伪造他人接受。 |
| D151 | 代理接受保留真实主体 | 代理接受记录真实主 Agent actor、策略 revision、授权范围、理由和受影响参与者，明确标记 proxy_acceptance，不伪装成直接接受。 |
| D152 | 普通任务由协作角色完成 | 普通 Task由 owner/reviewer/current main按验收策略完成；用户只确认项目整体完成或明确保留的关键里程碑。 |
| D153 | 项目完成由 Agent提议、用户确认 | owner 或 current main提交 ProjectCompletionProposal与证据包；只有 user/control确认后项目才进入 completed。 |
| D154 | Completed 是可恢复项目状态 | completed停止普通任务创建和自动调度，保留查询、审计和显式 follow-up；它不同于 archived，并可显式重新激活。 |
| D155 | 用户或策略授权的主 Agent可重激活 | user始终可 ReactivateProject；current main在项目策略允许且不扩大 user ceiling时也可执行；创建新 runtime_epoch，不复活旧运行态。 |
| D156 | 重激活后任务选择性恢复 | 项目重激活不自动重开历史任务；user/current main显式选择可恢复任务，未选任务保持原状态，completed只能建 follow-up。 |
| D157 | 支持原子批量任务恢复选择 | current main可提交 selector，服务端展开精确 task IDs与 plan digest，并以单一UoW处理；失败不留下部分恢复。 |
| D158 | 批量恢复直接将选中任务置 Open | 合法选中任务在批量UoW内直接进入 open；不预建 Attempt/Lease/workspace/grant，后续仍按开放claim和完整preflight执行。 |
| D159 | 任务恢复采用主 Agent业务判断 | 内核仅校验项目/lineage、revision、非 completed、未被替换、无当前 owner/Attempt等结构不变量；旧依赖是否仍适用由主 Agent判断并记录理由。 |
| D160 | 项目完成前由主 Agent收敛执行面 | main/user先决定全部未完成任务处置并关闭非终态current Attempts、释放Lease/执行grant；确认命令只验证执行静止，不自动替任务作业务决定。 |

## 任务图与调度

### 状态与所有权

- 一个任务同一时刻最多一个执行 owner；多人协作必须拆分子任务，其他 Agent 只能作为观察者或顾问。
- 用户和当前主 Agent可创建根任务与子任务。普通 task owner 不能直接创建/发布 child task，只能通过 D73 的类型化 `DelegationRequest` 请求当前主 Agent拆分。
- 委派可验收工作必须创建带 `parent_task_id` 的独立子任务。父 TaskAttempt 的 owner 保持不变，子 Agent只能领取和执行子 TaskAttempt；子结果通过结构化引用成为父任务输入，不能直接提交、完成或接管父任务。
- 极小的问答/咨询可使用 request/response Message；一旦需要独立写工作区、取得 lease 或产生验收结果，就必须升级为子任务。
- 创建子任务不自动改变父任务状态。父 owner 仍有自身工作时可保持 `running`；只等待子任务时显式进入 `blocked(reason=waiting_on_children)` 并释放 leases。被观察的子任务状态变化只发通知；是否已经足够继续由父 owner 判断，并通过显式 resume 重新 preflight。
- 父任务与子任务并行时分别持有各自声明的资源租约；父任务不得继续占用已经委派给子任务的 exclusive write scope。
- `parent_task_id` 不产生 required/optional 完成门禁。父 owner 可在子任务未完成、失败或取消时提交父任务；提交结果应引用实际采用的子任务结果/证据，并可说明忽略或尚未完成的子工作，验收方据此判断充分性。
- 父任务进入 `completed|failed|cancelled` 不传播状态给既有子孙任务，也不撤销它们自己的 grants/leases。子任务继续独立收敛；晚到结果保留原 parent 关系并进入时间线，但不能重开、补写或改写已终态父任务，只能由 follow-up 任务显式引用。
- 父任务终态后不能再创建新的直接子任务。父任务终态事件通知仍活跃的 descendant owners 和当前主 Agent；是否取消由合法主体另行提交显式命令。
- `DelegationRequest` 是 Message request，不新增领域审批实体；它固定 parent task/revision、请求目标、建议 scope/资源、理由和预期产物。当前主 Agent以创建后的 child task ref 或结构化拒绝满足响应义务，用户也可直接创建。
- 任务树允许多层，但每一层均由当前主 Agent或用户创建。child scope 默认必须在 parent task 的有效 scope 内；需要扩大时先修改父任务并重新进行相关授权/preflight，不能借子任务扩权。
- 普通 Agent不持有可转授的 `task.create-child` capability。主 Agent离线且用户未介入时，DelegationRequest 保持 pending，普通 Agent可继续原任务或显式 blocked，但不能自行物化子任务。
- `DelegateChildTask` 是 user/current-main 专用组合命令：校验 parent 非终态、authority/project/parent revisions、child scope、policy、验收配置和幂等键后，在同一 UoW 创建 `status=open` 且无 owner 的 child，并写 TaskCreated/TaskOpened、inbox/outbox 及可选 DelegationRequest 响应。
- 组合命令失败不留下 draft/ready/task ID；成功后不产生定向 offer，仍由所有合格 Agent按 D33 原子 claim。workspace、attempt、task grant 和 lease 在 claim/preflight 阶段创建，而非 delegate 阶段。
- 需要逐步编辑时仍可使用通用 `CreateTaskDraft` 与显式 publish。create-and-open 不伪造 draft/ready 中间事件；TaskCreated 直接记录经过完整验证的 initial status `open`。
- 主 Agent可将一个 `DelegationRequest` 收窄、拆分为多个 child、关联已有任务或拒绝，但不得扩大 parent scope。`DelegationResolution` 使用 `created|linked_existing|rejected`，携带 task refs、请求片段 mapping、理由和未采纳说明。
- resolution 不要求 requester acceptance。若创建多个 child，全部 task、events、inbox/outbox 和 Message obligation satisfaction 在同一 UoW 成功或失败；相同 request/command hash 幂等返回同一 task refs，不得重复创建。
- 最终采用单一扁平状态机：`draft`、`ready`、`open`、`claimed`、`running`、`blocked`、`submitted`、`changes_requested`、`cancel_requested`、`orphaned`、`completed`、`failed`、`cancelled`。
- 最新决定取消 `offer` 对象和 `offered` 状态，覆盖早期“主 Agent 发定向 offer”的建议。用户或主 Agent 将 `ready` 发布为 `open`，所有满足硬约束的 Agent 都可见，首个合法原子 claim 获得任务。
- 调度内核只做确定性候选筛选：依赖、权限、适配器能力、最低执行强度、资源条件和工作区可用性。首版不自动选择 owner。
- `blocks` 必须保持 DAG；契约、资源和外部条件使用类型化 prerequisite。`related_to`、`duplicates` 等非阻塞边可成环。

### Attempt 与状态转移

- claim 从 `open` 进入 `claimed`，创建不可变 `TaskAttempt` 并递增 `execution_epoch`。
- `claimed` 阶段异步准备工作区；只有启动认知报告、契约绑定、权限、风险评估、执行强度和全部资源租约通过后，显式 start 才进入 `running`。
- 每次重试、返工或强制交接都关闭旧 attempt 并创建新 attempt；历史结果、耗时和证据不可改写。
- `blocked` 保留 owner，但离开 running 时释放资源。blocker 消失只标记可恢复；owner 或主 Agent 必须显式 resume 到 `claimed` 并重新执行 preflight。
- `waiting_on_children` 是 `blocked` 的类型化原因，不新增任务状态。子任务变化可提醒 owner，但不自动判断等待条件已满足，也不自动把父任务推进到 claimed/running。
- 执行租约过期进入 `orphaned`，不假设外部进程已经停止。允许三种显式恢复：有宿主连续性证据时恢复原 attempt；主 Agent 关闭旧 attempt 后交接；放弃旧 attempt 并回到 `ready`。
- 运行中取消使用两阶段语义：先进入 `cancel_requested` 并通知 owner，取得停止证据后进入 `cancelled`。主 Agent 可强制收敛，但必须记录残余进程/写入风险并使旧执行代次失效。
- `failed` 和 `cancelled` 可由有权限命令重开到 `ready`，保留全部旧 attempts；`completed` 不可重开，只能创建关联 follow-up 任务。

### 提交与验收

- running owner 提交结构化结果与证据后进入 `submitted`，不能自行把普通任务直接标记为 completed。
- 验收策略在任务进入 open 前固定，只支持三种原语：`automated`、指定 `reviewer`、项目策略允许的低风险 `self`；可使用 `all_of` 组合，不引入通用表达式语言。
- reviewer 要求修改时提交结构化 findings，任务进入 `changes_requested`；原 owner 接受返工时关闭旧 attempt，创建新 attempt 并进入 `claimed`。
- 任务离开 `running` 即释放执行资源租约，包括进入 blocked、submitted、cancel_requested、orphaned 或终态。

## 认知报告、分歧与契约

### EpistemicReport

- 在 claim 后启动前、关键假设/计划/影响范围变化、进入契约敏感操作前和 submitted 前强制提交；其他时刻允许主动更新。
- 每份报告不可变，更新通过 `supersedes_report_id` 关联。
- 结构化外层至少覆盖：目标理解、假设、置信度、证据、错误影响、不确定性、计划动作、资源意图、契约引用和预期产物；各项可包含自然语言理由。
- 置信度只使用 `unknown/low/medium/high`，并要求理由或证据与 `impact_if_wrong`，不使用不可校准的小数概率。

### DiscrepancyCase

- 首版检测由版本化确定性规则和 Agent 主动上报构成，不调用 LLM 裁定隐藏分歧。
- 规则比较结构化字段、契约版本/哈希、任务前置条件和资源意图。
- severity 为 `info/soft/hard`；状态为 `open/clarifying/negotiating/resolved/dismissed/overridden`。
- 契约版本、接口形状、前置条件或互斥写意图等 hard 冲突自动阻塞直接受影响任务，并沿 `blocks` 依赖向下游传播；无关任务继续。
- soft/info 先发送澄清请求；dismiss 必须写理由，override 仅用户可执行。

### Proposal 与 Contract

- 一个案例允许多个不可变 proposal revision。参与者可接受、反对或请求修改；某个版本获全部必要参与者接受后转成生效契约，其余标记 superseded。
- 契约公共头包含 subject、scope、required_participants、applicable_tasks 和 supersedes；正文按 `api_interface`、`data_schema`、`behavioral`、`integration` 四类 schema 校验，并保留 rationale。
- required participants 由影响图从适用任务 owner、依赖任务、受影响资源和现有契约派生最低集合；提案者/主 Agent 可增加。移除参与者必须先缩小 scope 或解除影响关系并创建新 proposal。
- 接受绑定精确内容哈希；生效前可带理由撤回，全部接受的同一事务使版本生效。生效后不可撤回或修改，只能创建 superseding version。
- 任务精确绑定 `contract_version + content_hash`；新版本不会自动替换运行中的绑定，受影响任务必须逐一迁移并重新 preflight/验收。
- 主 Agent 可以缩小范围、拆分任务或提出新方案，但不能代替其他身份接受。
- 无法一致时只有用户可创建独立 `OverrideDecision`。它保留反对意见、范围、期限和受影响任务，不把提案标为全员 accepted；任务显式绑定 override 后才解除阻塞。
- Agent succession 自动替换 pending obligations 时，若 predecessor 是 ContractProposal 的 required participant，cognition 模块必须创建正文/scope 相同但 participant set 已替换的新不可变 proposal revision；参与者集合属于 content hash。
- 原 proposal/acceptance obligations 被 supersede，已有 acceptances 仅保留为旧 hash 的历史 evidence，不能沿用。新 revision 的全部 required participants 都收到新 acceptance obligation并对同一新 hash 重签。
- 已生效 Contract 不因 succession 就地改写。successor 需要承担其中职责时自动发起 superseding proposal；受影响 Task在绑定并接受新 Contract前保持 contract blocker。

## 资源意图与租约

### 模型与取得

- `ResourceIntent` 用于提前公开计划范围；`Lease` 是协调器授予当前 attempt 的临时占用，两者不可混为一体。
- 普通 read intent 不阻塞 exclusive write，只用于影响通知。需要稳定快照时显式申请 `consistent_read`，它与重叠 exclusive write 互斥。
- 文件/目录 exclusive write 按规范化物理路径的相同、祖先和后代关系判断重叠；命名环境资源使用 exclusive use。符号级范围只作 advisory 证据。
- 一个 attempt 启动前声明资源集合并原子全取或全不取。运行中扩大范围必须提交 amendment，并原子取得全部新增资源；缩小范围可提前释放子集。
- 等待按任务优先级与等待年龄排序；默认不抢占 running lease。高优先级任务只能请求取消、阻塞或交接当前 holder 后再取得。

### 有效性与故障

- 用户明确选择只验证当前 `lease_id`，不实现每资源单调 fencing token。受控操作仍校验 lease 是否 active、holder、task/attempt、资源与操作是否匹配。
- 适配器连接独立于模型回合，每 30 秒后台续租，默认 TTL 120 秒；连续失败先标 degraded，到期使任务进入 orphaned。
- 只有绑定当前 agent、host session 和 TaskAttempt 的桥接连接可以 renew；主 Agent不能冒充执行者心跳。
- 任务离开 running 自动释放租约；恢复、返工或重新执行必须重新全取。
- 文件监控或 Git 扫描发现未携带有效租约的外部写入时只记录告警与证据，不自动阻塞任务、不回滚文件。这一选择明确降低了外部写入治理强度。

## 工作区与隔离驱动

### 驱动边界

- 首版正式支持 `shared`、`git_worktree` 和 `external` 三个驱动。
- Git Worktree 只正式支持单仓库任务。跨仓库工作必须拆成单仓库任务，或使用 shared/external；不实现每 attempt 多仓库 Worktree 组。
- external 首版只附着用户/主 Agent 已准备的目录、容器或远端映射。协调器验证路径、基线、能力向量和健康状态，不负责创建、启动、停止或删除外部环境。
- 驱动使用能力向量描述文件写隔离、进程、网络、密钥、环境复现和清理保证，不能假定 `external` 或 Worktree 在所有维度都更强。

### 风险选择

- 最新决定由系统自动选择隔离驱动，覆盖早期“用户或主 Agent逐任务选择”的默认方向。
- 首版风险评估由当前主 Agent 响应结构化 request，使用 LLM 给出风险、理由和驱动选择；后端不直接绑定模型 provider/key。
- 内核对 LLM 结果执行确定性硬约束复核：用户/项目权限上限、最低能力与执行强度、驱动可用性、Worktree 单仓库限制、未解决 hard discrepancy 等不可被模型绕过。
- 主 Agent 离线时待评估任务等待，不能静默使用较弱驱动。
- 用户可覆盖为任意可用驱动；主 Agent 可升级隔离，也可在项目策略允许时留理由降级。所有覆盖均产生审计事件。
- 影响范围、资源意图、契约状态、仓库数、执行强度需求或驱动能力变化触发重新评估。running 任务只标记 `migration_required`，不自动搬迁现场。

### Worktree 生命周期

- provisioning 必须基于明确 commit；相关仓库存在未提交或未跟踪变更时拒绝创建，系统不自动制造 seed patch。
- submitted 结果记录 base commit、最终 head、状态清单和内容哈希；存在未提交变更时生成只读 patch artifact。协调器不强制 Agent commit。
- 任务终态、结果证据物化且 checkpoint 完成后工作区才标记可清理；仍需用户或主 Agent 显式清理。
- 脏 Worktree 禁止普通删除；强制删除只允许用户执行。

## 持久化、后台作业与项目生命周期

### 数据库与并发

- 每个项目使用 `.tsunagou/local/state.sqlite3`，用户级守护进程只保留可重建的项目路径注册表。
- OS 文件锁保证同一项目路径只有一个可写 runtime；应用内为每项目建立串行领域写队列，读取可并发。
- SQLite 使用 WAL、`synchronous=FULL`、foreign keys 和 busy timeout。
- 项目按需打开：首个请求验证共享清单、取得锁、迁移/恢复并打开连接；无 Agent、无待作业且空闲时关闭。

### 作业与事务

- materialization、消息重投、租约扫描、checkpoint 和保留清理均是 SQLite 持久作业，记录 next_run、attempt 和 worker lease。
- 守护进程使用 asyncio 进程内 worker 领取作业；崩溃重启后继续，不引入 Redis/Celery。
- 聚合状态、领域事件、inbox 路由、outbox 和必要 background job 在同一 Unit of Work 提交；提交后 dispatcher 幂等执行文件物化、SSE 和适配器通知。

### 迁移、保留与备份

- 支持范围内的数据库/共享 schema 在启动时自动前向迁移；迁移前完成预检、checkpoint 和 SQLite online backup。
- 迁移失败则项目拒绝写入并提供只读诊断；共享层处于脏或 diverged 时不自动重写。
- 任务、契约、权限、认知与审计领域事件随项目永久保留。
- 投递 attempt、心跳、工具明细和原始遥测默认保留 30 天，可配置并在 checkpoint 后压缩。
- 本机备份保存在 `.tsunagou/local/backups/`，默认最近 5 份且不超过 30 天；仅允许匹配 project_id/lineage 的诊断恢复。跨机器恢复仍以 Git 共享 checkpoint 为准。

### 协调仓库与项目终止

- 初始化必须指定一个已有 Git repository 为 coordination repo，`.tsunagou/` 位于其根；其他 ProjectRoot 通过逻辑映射引用。没有现有仓库时，由用户先建立专用元数据仓库。
- `project init` 完成共享树、本机 SQLite 和注册物化后立即进入 active，允许 Agent 接入和正常协作；不要求用户先提交 `.tsunagou`。
- 项目运行状态与 Git 持久性分离。初始化时 `git_durability=unanchored`，CLI/API 必须持续暴露其“尚不可从 clone 恢复”的含义，不能把本机成功写入表述成 Git 备份完成。
- genesis checkpoint 允许没有 Git commit；后续只把已提交树中可按 manifest/hash 完整验证的 checkpoint 记录为 anchor。工作树或 index 的当前外观不能作为 anchor 证据。
- 调度中心仍不自动执行 `git add`、commit 或 push；首个 anchor 建立前允许的高影响生命周期操作范围继续单独决策。
- Git 持久性分为 local checkpoint coverage 与 remote publication evidence；本地 commit 只证明当前 object database 中存在可达的已验证 checkpoint，不等同于远端备份。
- Git 的执行 owner 是当前 `authority_epoch` 下的主 Agent。调度中心通过类型化请求表达 checkpoint commit、集成、分歧处理、fetch/push 或远端核验目标；主 Agent 在自己的 Full Access 宿主中选择具体 Git 命令并执行。
- daemon 永不执行会修改 repository/ref/worktree 或访问 remote 的 Git 命令，不调用远端 credential helper；它只保留本地只读检查器验证 commit tree、checkpoint、ref 可达性和工作区事实。
- 主 Agent 提交结构化 `GitActionReport`，绑定 request、authority epoch、repository/root、before/after OID、ref、checkpoint、结果分类和有限证据摘要。远端结论标记为 `main_agent_reported`，不能伪装成 core 独立在线验证。
- 用户仍可在外部手动操作 Git；调度中心通过只读扫描和用户/主 Agent 报告进行 reconcile。宿主 Full Access 意味着逻辑 Git 授权可能只能审计和自然语言约束，必须如实标注执行强度。
- 主 Agent 交接或失联时，未取得完成报告的 Git 请求进入 outcome-unknown/reconcile；新主 Agent 不能假定旧进程已停止，必须先检查 repository/remote 的实际状态。
- Git 动作分为 L0 只读观察、L1 常规可追加/fast-forward 与 L2 有损或历史重写。L1 由当前主 Agent提交 intent 后按策略自动授权，L2 默认等待用户批准。
- L2 至少包括 force/non-fast-forward push、远端 ref 删除、已发布历史重写、丢弃未保存修改、强制清理脏 branch/worktree、修改 remote/credential/hook 与绕过保护。
- L2 批准绑定 action digest、repository、before OID、精确 ref/path、风险摘要和短有效期；参数、authority epoch 或 repository 状态变化后失效，禁止使用宽泛永久批准。
- 项目 policy 可以把 L1 提升为需审批，不能在首版把 L2 降为普通 Agent可执行。主 Agent可主动提出 intent，也可响应调度中心请求，但两者使用同一分类与审计。
- Full Access 宿主若不能拦截主 Agent直接运行 Git，系统必须把 enforcement 标为 advisory/observed，并在检测到无 intent 的写入时暂停依赖旧基线的操作、请求 reconcile，而不是虚报已阻止。
- 一个或多个 ProjectRoot 可归属同一 `repository_id`；TaskAttempt 只绑定其影响仓库子集的不可变 base/result repository state vector，Git OID 必须带 object-format 算法。
- 多仓库集成使用 parent Operation 与每仓库 child Git action；先原子取得全部逻辑资源租约、完成 checkpoint 和意图/审批，再按显式 repository dependency DAG 执行。
- 默认先集成被依赖 source repository，最后让 coordination repository 的 checkpoint/manifest 引用最终 commit vector；没有业务 DAG 时稳定排序只提供确定性，不冒充依赖语义。
- Git 不提供跨独立 repository/remote 的原子 commit/push。任一 child 失败、冲突或 outcome unknown 后保留已成功结果并进入 `partially_applied`/`reconcile_required`，阻塞受影响集成。
- 收敛默认采用 forward-fix、新 revert commit 或继续剩余步骤；已发布历史不以自动 force push 伪装事务回滚。compensation 是新的 intent/report 链并永久保留原记录。
- 系统不为协调目的自动把用户仓库改成 submodule/monorepo，也不宣称 coordination checkpoint 能证明其他仓库对象已发布。
- `ProjectRoot`、Git `Repository` 与 replica-scoped 本机 binding 分离；多个 roots 可归属同一 common directory，repository identity 不由路径、remote URL 或 commit OID推断。
- `.tsunagou/project.toml` 显式声明稳定 root/repository ID、role、VCS expectation、依赖与策略；`.tsunagou/local` 绑定绝对路径、filesystem identity、Git top-level/common-dir 与能力。
- 添加/bind 只探测用户明确路径和必要祖先；显式 discover 也只生成有预算的候选报告，永不递归自动登记或扩大授权。
- 已登记 nested repo/submodule 属于最具体 repository；检测到未登记 Git 边界时，涉及该路径的写任务以 `unregistered_repository_boundary` 阻塞。linked task worktree 只是 workspace binding。
- 显式 non-Git root 仍使用 `fs://`、权限、ResourceIntent/Lease、文件摘要和审计，但没有 commit/anchor/publication/worktree/fast-forward 语义，默认只支持 shared 或预置 external driver。
- clone 自动绑定 coordination repository；其他 required root 未绑定时阻止正常激活或相关任务，optional root 只阻塞引用它的任务。路径移动必须显式 rebind 并重新核验身份。
- 重叠 roots 必须声明 parent/child 且物理 binding 验证包含关系；无祖先关系的相同/重叠 writable bindings 进入冲突状态。
- 路径 canonical identity 使用最具体 active root；通过 ancestor URI 访问 child 范围返回 `canonical_root_required`。有效权限取 ancestor-to-child 全链与用户/项目/主 Agent/任务授权的交集，deny 并集。
- `fs://` wire path 只接受规范相对 segments，不允许客户端传本机绝对路径。服务端从 root handle 逐段解析，记录最终路径、filesystem identity、link chain 和实际 enforcement strength。
- 默认链接策略为 within-root：同 root 内可按策略跟随；跨到另一已登记 root 时必须改用目标 root URI重新授权和取 lease；逃出全部 roots、未知 reparse、循环或身份不可得时拒绝。
- ResourceIntent 在授予 lease 前解析为 canonical logical identity 与 `PhysicalResourceKey`；parent/child URI、大小写 alias、内部链接和可识别 hard link 指向同一对象时必须冲突。
- 尚不存在路径用最近现有 parent identity 与规范 segments 建键，创建前后重新核验；binding/parent 在 preflight 后变化返回 `path_identity_changed`，不在新位置继续。
- Full Access shell 无法保证拦截路径逃逸时必须标为 observed/advisory；受控文件工具可 gated，真正强边界依赖 isolated workspace/OS 能力。
- 用户本机 `LocalAccessCeiling` 与共享 root declarations、任务 grants 分层；ceiling 不进 Git，clone 后必须由当前机器重新建立，`full_access` 只能由显式用户动作产生。
- 当前主 Agent具备 `project.root.manage` 时，可在 coordinator/main-agent ceilings 与 shared policy 交集内 add/bind 普通 roots、同身份 rebind、收窄 policy、retire 无活动依赖的 optional root，并给 Agent/attempt 发子授权。
- 普通 Agent不能修改 roots/ceilings，只能提交结构化 RootAccessRequest；主 Agent签发的 grant 默认不可转授并绑定 agent/session/attempt、path/capability、期限、authority epoch 与 policy digest。
- 扩大 ceiling/Full Access、更换 coordination root、无法证明同身份的 rebind、越过 trust/ownership 边界、read-only 提升为 write 或 force-retire 活动 root 必须由用户批准精确 proposal。
- 用户收窄/撤销先阻止新授权，再使越界 binding、grant、token、lease 和未开始工作失效；running 外部进程按宿主能力取消并记录 residual risk，不能把 Full Access 进程宣称为已停止。
- 用户扩大 ceiling 不自动登记 root、恢复任务或发放 Agent权限；仍需显式项目与授权命令。
- authority transition 原子递增 epoch 并立即撤销旧主 Agent控制 token、未使用 ticket/session grant、未开始 Git/root intent 和非运行 execution grant。
- running attempt grant 进入最多 120 秒 `pending_adoption`，只允许读取状态、响应 handoff/cancel、报告进度/副作用、提交只读 evidence、释放 lease 和确认停止；禁止新业务阶段/资源/副作用。
- 新主 Agent或用户按 candidate/scope digest、attempt/workspace/lease revisions adopt；只能等权或收窄，重新通过 preflight 后换发新 epoch grant/token 并恢复 lease。
- 未 adopt 且有安全停止证据的 attempt 进入 `blocked(authority_transition)`/cancelled；无停止证据则 orphaned 并 quarantine 相关资源。没有 successor 时也不让旧 grants 无限存活。
- 已启动 Git/外部副作用 action 在交接时进入 outcome-unknown/reconcile，不能把旧 intent/用户批准转移给新 epoch，也不自动重试。
- transition/candidate/revocation/adoption 持久化且幂等；daemon 离线越过 deadline 后先收敛过期 candidates 再开放项目写入。
- Project aggregate 只保存少量权威维度：lifecycle (`active|archived`)、authority (`unassigned|stable|transitioning`) 与 replica role (`active_writer|standby|takeover_required`)；长流程由 Operation 表达。
- 外部/派生事实使用 `ProjectCondition`，包含 true/false/unknown、reason、scope、observed revisions/epochs、input digest、evidence、last transition 与 stale policy；过期变 unknown，不自动变 false。
- 真正门禁由 `ProjectBlocker` 表达，绑定 source、scope、affected actions/capabilities、observed revisions、remediation 与解除 predicate；多个 blockers 同时返回。
- blocker 可只冻结某 root/repository/task/action；divergence/migration/corruption 等才按规则阻止全项目写。condition 本身不自动等于 blocker。
- `operability`/`health` 仅为带 derived revision 的扫描摘要，不能替代 command preflight，也不代表调用者有权限。
- command handler 在同一 UoW 校验身份/revision/epoch、刷新或拒绝陈旧条件、收集全部适用 blockers，通过后才提交 mutation/event/outbox；REST/MCP 返回相同 machine blocker details。
- `project init` 由本机 user/control principal 调用，生成 `authority.status=unassigned`、`authority_epoch=0`；连接顺序、Agent自报 role、宿主类型或 Full Access 均不能隐式选主。
- 用户可显式任命已接入且通过 session/capability/ceiling 验证的 Agent；并发任命由 expected project revision/epoch 保证只有一个成功。
- 用户也可签发独立 ticket kind 的 `main_agent_enrollment_ticket`，固定候选/宿主条件、main-agent ceiling、expected epoch、10 分钟 expiry 和 one-time nonce，在同一 UoW 完成 attach + appoint。
- 普通 worker enrollment ticket 与 main-agent ticket 不可互换；失败不得产生半任命或可复用 access token，票据/秘密不进 Git、prompt 或普通日志。
- unassigned 可以长期存在，只阻止需要主 Agent的 Git/root/grant/risk/coordination actions；用户管理、诊断、enrollment 和其他明确允许动作继续，不自动超时选主。
- 首任失联/撤销后进入正常 authority transition，不重新应用 first-join 规则；旧 clone/runtime/lineage 的主 Agent凭据不能恢复当前 authority。
- 主 Agent任命和计划性交接不创建 candidate proposal，也不等待 accept/reject；提交前必须验证候选已经 attach、session 连续、能力满足、ceiling/grant 合法且 expected revision/epoch 匹配。
- 任命 UoW 直接设置 current main、递增 `authority_epoch`、签发新管理 grant/token，并在交接时启动 D89 旧 grants 冻结/adoption。候选从事务提交起拥有管理权。
- 任命通知与职责摘要通过持久 inbox/outbox 发送，但 ACK/可见性不构成 authority 生效条件；投递失败不能回滚或自动选择其他 Agent。
- 用户选择错误候选或候选随后失联时，使用正常 revoke/handoff 再次递增 epoch；系统不因离线自动降为 unassigned 或选主。
- 普通 Agent仍不能 self-appoint；D91 专用 main-agent enrollment ticket 代表用户预先授权 attach+appoint，不是候选 acceptance。
- 本地 anchor 采用混合发现：项目打开、checkpoint 物化、Git refs 变化提示和状态查询可触发后台 scan，同时提供可等待的显式 local verify；生命周期门禁必须同步刷新。
- 自动与显式入口调用同一 `LocalCoverageVerifier`，按 Git common directory 合并作业，并以 refs snapshot 防止扫描期间 ref 移动导致错误结论。
- 首版只有 `refs/heads/*` 和 `refs/tags/*` 可形成 local anchor；detached HEAD、reflog、dangling object、remote-tracking、stash/replace/未知 refs 只能提供诊断线索。
- 验证从 commit tree 读取 checkpoint catalog/manifest 和受管文件，不 checkout、不运行 hooks；发现 `.tsunagou/local`、秘密或临时文件进入 tree 时拒绝 anchor 并产生高优先级诊断。
- branch reset/tag delete 可使当前覆盖度降级，但不可删除历史 evidence；Git 不可用返回 unavailable，不能误报为 none。
- 普通 clone 继承共享 `project_id`/`lineage_id`，但首次注册生成本机 `replica_id`；同一 Git common directory 下的 linked worktree 归属同一 replica，任务 worktree 不得成为项目 writer。
- 用户级 daemon 对同一 project/lineage 只允许一个活动可写 replica；其他已登记 clone 为 standby，只能诊断、比较和执行激活预检。
- 正常 replica 切换必须停止新工作、排空运行态和 materialization、形成 checkpoint、撤销旧凭据，再在目标 replica 中创建新的 `runtime_epoch`。
- 旧副本不可达时允许显式 takeover；接管不会声称终止外部 Agent，而是使旧代次 session、token、lease 和 job claim 失效，并记录残余进程与不可验证副作用风险。
- 首版不提供跨机器分布式写租约；并发机器通过 checkpoint 父哈希分叉被检测后停止写入，进入显式分歧处理。
- `project_id` 标识用户眼中的逻辑协作项目；普通 clone、当前 checkpoint 恢复、归档/激活和本机修复不改变它。
- `lineage_id` 标识当前可追加的持久历史代次。从祖先 checkpoint 回滚后继续写或重置协作状态时保持 project、创建新 lineage，并永久 seal 旧 lineage。
- 从 checkpoint 另建独立项目时创建新的 project/lineage/replica/runtime 四层身份，并以只读 `forked_from` 记录源 project、lineage、checkpoint 和 hash；不继承运行态或访问权。
- lineage transition 必须绑定来源 checkpoint，撤销旧 lineage 的凭据、租约、session、job claim 和未完成 outbox；UUIDv7 时间不能替代显式父子关系。
- `.gitignore` 使用可识别托管区块，只忽略 `.tsunagou/local/`、临时文件和秘密；共享层不得被忽略。
- 任务 Worktree 保留共享快照供读取，但 `.tsunagou/` 是 protected 范围。结果扫描发现修改时拒绝 submitted 或要求清除；协调器只在 coordination checkout 物化。
- 归档要求无 running/cancel_requested/orphaned attempt，完成 checkpoint、撤销 Agent 凭据和本机租约，写入 archived 并关闭数据库。用户可显式以新 runtime epoch 重新激活。
- 普通Task由owner/reviewer/current main按acceptance policy完成，不形成用户确认点。项目整体完成使用独立`ProjectCompletionProposal`，由目标owner或current main提交证据包，只有user/control确认后Project lifecycle才进入`completed`。
- `completed`停止普通Task创建和自动调度，但保留查询、审计、checkpoint、显式follow-up与重激活；它不同于`archived`。user始终可重激活，current main仅在project policy授权且不扩大user ceiling时可重激活，动作创建新runtime epoch且不复活旧运行状态。
- 项目重激活不自动重开历史Task。user/current main可提交批量selector，服务端展开精确Task IDs和plan digest，在一个UoW内把全部合法选中Task直接置为`open`；不创建Attempt/Lease/workspace/grant，之后仍走开放claim和完整preflight。
- 批量恢复的业务理由、旧依赖适用性和取舍由current main结构化声明。内核只验证project/lineage/runtime与revisions、Task非completed/未被替换、无current owner或Attempt、actor authority和batch原子性；动态依赖/权限/契约/资源/workspace/risk在claim/preflight阶段重新计算。
- 用户确认Project completion前，current main或user/control必须先为每个未完成Task选择显式处置，关闭所有非终态current Attempts并释放执行Lease/grant；可保留残余风险和未解决事项，但必须进入completion evidence。确认handler只验证无非终态current Attempt、活动执行Lease或可用执行grant，不自动完成、取消或失败任何Task。
- 普通 delete 只移除用户级项目注册，保留仓库。清理 local 和删除 Git 共享层是两个额外用户操作；调度中心永不删除 ProjectRoot 源码或仓库。

## 适配器、运行时与安全

### 共同结构

- 四种宿主均采用“宿主薄桥接 + 核心 HTTP”的结构；核心不加载厂商 SDK，不在 Python 进程内运行厂商插件。
- Codex 使用独立 MCP bridge；OpenCode、ZCode、DeepSeek Harness 使用宿主原生插件/Hook 技术。共享 OpenAPI、JSON Schema、测试向量和 conformance runner，不强制同一种实现语言。
- 适配包声明版本化能力上限；连接时上报宿主/适配器版本并运行必要探测，核心保存 effective capabilities 和证据。能力变化触发任务风险重评。
- 维护 min-supported、max-tested 与已知不兼容列表；测试窗口外为 unsupported，只允许用户显式诊断试运行，不能计入正式共同基线。

### 安装与工具面

- CLI 修改宿主配置时只写带 owner/version 标记的最小托管区块，修改前备份。升级只改托管区块；发现用户改动则停止并要求解决；卸载精确回滚。
- 模型只看到 context、task、report、contract、inbox、lease 等类型化领域工具，每个工具有 JSON Schema。禁止暴露“任意 URL/action/payload”的通用 REST 工具。
- 宿主 bridge 从系统凭据库读取 token 并代签请求；token 不进入 prompt、工具 schema、Git 文件或模型可读环境变量。
- SSE 只发送 event_id、project_id、topic 和资源 revision 等变化信号；bridge 收到后通过鉴权 REST 拉取权威数据。使用 Last-Event-ID 恢复，游标失效时全量对账。
- 主动唤醒仅用于取消/交接、hard discrepancy、契约请求、租约即将到期和高优先级用户/主 Agent 请求，并按 Agent 限流合并；普通通知等到下个边界。
- Hook/插件联系协调器失败时，任务要求 gated/isolated 的受控操作 fail-closed；advisory/observed 可 fail-open，但记录降级和告警。

### 会话与进程

- 四种适配器都必须支持附着现有会话；managed launch 只在宿主有经过测试的稳定 CLI/API 时提供，属于增强能力。
- 系统只对自己启动的 managed 进程执行优雅停止或策略允许的终止；attached 进程只撤销协调凭据、解除关系并报告残余写入风险。
- bridge 未发现守护进程时，在 runtime 已登记且项目已初始化的前提下可调用受限 launcher 按需启动，校验 instance nonce/健康端点后连接；不得自动下载或升级。
- `Agent` 是项目内逻辑成员，`HostSession` 是某宿主安装实例/对话附着到某 project runtime 的持续关系，`Connection` 是一次短暂 REST/SSE bridge 在线连接；网络或进程断线不能混同为新 Agent。
- resume 必须同时匹配原 session token、adapter installation ID、D119 的 `host_conversation_id` digest、project/lineage/replica/runtime epoch 和协议摘要。成功只新建 Connection 并递增 connection epoch，保留 agent/session/base grant/inbox 状态。
- token 单独不是连续性证明。new/clear/fork 必须使用新 conversation ID；ID 不匹配、runtime/lineage 改变、session ended/revoked 或 adapter 无法提供稳定 ID 时拒绝 resume，要求新 enrollment/attach；fork 只记录来源关系。
- capability snapshot 下降可恢复会话但触发 blocker/re-preflight；能力上升不自动扩大既有 grant。恢复也不复活 expired Lease 或旧 authority epoch。
- 同一 HostSession 只允许一个 current Connection。resume/attach 以 expected connection epoch 和 reconnect nonce 做 CAS；成功递增 epoch并 supersede 旧连接，相同请求幂等返回原结果。
- command、Lease renew、inbox lease/fetch/ACK 和 capability report 在进入 UoW/提交前核验 current connection epoch；旧 bridge 返回 `stale_connection` 并应停止。SSE 重建可复用 current connection，但不创建第二个 command authority。
- 首发不实现 `ConnectionHeartbeat` 或固定 presence timeout。成功请求/SSE 建连更新 `last_seen_at`，明确 transport close/failure 可标记 connection disconnected；没有新证据时 HostSession presence 为 `unknown`，不得持续宣称 online 或推断 offline。
- Presence 只用于展示、主动投递选择和诊断，不撤销 Agent/HostSession/grant/authority。TaskAttempt 与资源存活仍由独立 Lease 30 秒 heartbeat/120 秒 TTL 决定；宿主明确 end/clear/detach 等 lifecycle evidence 走终止流程。
- adapter verifier 确认 `end|clear|detach|uninstall` 或 user/control detach/revoke 时，同一 UoW 终止 HostSession/Connection、撤销 credential/base grant/未开始 grants 与 inbox leases，并写事件/outbox；该终态不可恢复为旧 HostSession。
- 该 session 所属 running attempts 立即 `orphaned` 并失效 execution grant/epoch，保留外部进程 residual-risk/reconcile。若它是 current main，authority 不自动转给他人，只增加 `main_agent_unavailable` condition/blocker，等待用户 revoke/handoff/继任。
- 每次 attach/resume 新 connection epoch 运行固定 probe suite；服务端将代码内 AdapterDescriptor 上限、正式版本窗和 probe evidence 做保守交集，生成不可变 `CapabilitySnapshot`。probe 前 HostSession 只允许初始化/诊断。
- 配置、插件或宿主 lifecycle 变化通过显式 `ReprobeCapabilities` 创建 superseding snapshot。普通 command 不逐次探测；claim/preflight、RiskAssessment 和 RoutingSnapshot 记录使用的 snapshot ID/digest。
- snapshot 能力下降立即重算 eligibility 并触发相关 blocker/migration/re-preflight；能力上升只增加未来候选能力，不自动扩大 grant/task scope 或恢复任务。unknown 不按 supported 处理。
- mandatory baseline 任一能力 unsupported/unknown 时，HostSession 保留为 `degraded`，只允许读取自身 probe、提交 reprobe 和结束 attach；不签发 agent_base、不开放项目/inbox/task/contract/main-agent candidate。
- 修复后同一 HostSession 可用 expected revision 原地 reprobe；全部 mandatory 通过时单事务转 `ready` 并签发 base grant。已 ready 会话降级时冻结业务 grants，并按缺失能力影响对运行工作产生 blocker/orphan/migration。
- 服务端/协议注册版本化 `collaboration_baseline_v1`，由 identity isolation/continuity、project context、typed command、task lifecycle、cognition/contract、inbox fetch/ACK、structured response、reconnect/dedupe 等原子 capability 及 evidence/strength 规则组成。
- readiness evaluator 从 CapabilitySnapshot 逐项计算，不接受 adapter 自报的 baseline boolean。wake、tool gate、managed launch、model-presented evidence 等是 enhancement，可由具体 Task 另设 minimum。
- HostSession 绑定协商的 profile version；profile 更新不静默改变现有 readiness，须经显式 reprobe/migration，并进入 release compatibility matrix。
- 四种 adapter 必须输出统一 `host_conversation_id`。身份键为 `(adapter_installation_id, host_kind, host_conversation_id)`；resume/compact 保持，new/clear/fork 必须改变，fork 可另报 parent ID 仅作 provenance。
- core 不实现 adapter-specific continuity verdict；它对规范化 ID 做精确相等判断。原始 ID 只在 loopback attach/resume 请求中出现，数据库保存安装实例作用域内的 keyed digest，禁止进入日志/prompt/Git。
- conversation ID 不得由 bridge process ID、工作目录、显示名称、session token 或模型自述生成。宿主版本无法提供或可靠绑定稳定 ID 时，capability 为 unknown/unsupported，不能通过正式共同基线。
- 缺少稳定 conversation ID 时禁止用户手工确认为原 Agent，也禁止用工作目录/adapter 私有文件中的随机值替代宿主对话身份；修复 adapter/宿主集成并通过 new/resume/compact/clear/fork conformance 后才能进入正式版本窗。
- `adapter_installation_id` 在每个宿主用户 profile 的 adapter 安装/注册时生成 UUIDv7，保存于 adapter 私有数据目录和 daemon 本机登记表；升级、配置变化、bridge 重启和可验证迁移保持，uninstall/reset/私有数据丢失后重建。
- installation ID 不是 secret 或权限凭据，不进入 prompt/Git；同 ID 不得被两个 active host instances 并发声明。ID 改变后旧 conversation string 不匹配旧 Agent，必须重新 enrollment 并按继任流程处理历史任务。
- enrollment redemption 在一个 UoW 验证并消费一次性 ticket、检查 installation/conversation 冲突，创建 provisioning Agent、HostSession、credential hash、CapabilitySnapshot 和事件/outbox。
- mandatory baseline 通过时同事务转 active/ready 并签发 agent_base；缺失时 ticket 仍消费并保留 diagnostic-only provisioning/degraded 对象供原地 reprobe。未经 probe 的身份不存在项目访问窗口。
- main-agent ticket 只有在 attach/probe ready 后才在同一事务执行 D91 appointment；degraded 不任命。无效/过期/host mismatch/conversation conflict 不创建半对象，相同 command ID/hash 幂等返回原结果。
- 每个 active/provisioning Agent 最多一个非终态 HostSession。相同 installation/conversation 再用普通 enrollment 返回 `conversation_already_enrolled`；多 adapter 组件必须共用该 Session/Connection authority。
- token/私有数据丢失且 installation+conversation 仍精确匹配时，专用 `session_rebind_ticket` 在一个 UoW 终止旧 Session、撤销 credential/session grants 并为同一 agent_id 创建 replacement；不恢复旧 Connection/Lease/运行 grant。
- installation 或 conversation 已改变时禁止 rebind 为原 Agent，必须新建 Agent并走显式继任；历史消息、契约和 attempts 永不改作者。
- Agent succession 由 user/control 或 current main 显式批准，并固定 predecessor、successor、reason、expected revisions 及选定未完成任务；`all_unfinished` 也必须由服务端展开并固化为精确 task IDs。
- 每个选中任务都使旧 execution epoch/grant 失效，并为 successor 创建新的不可变 TaskAttempt。successor 重新执行 workspace、风险、认知、契约、scope 和资源 preflight；旧 Lease、workspace ownership、approval、未完成副作用 intent 与 execution grant 均不转移。
- 有可信停止证据时旧 Attempt 可按交接原因关闭；缺少停止证据时保持 orphaned/residual-risk，并阻止新 Attempt进入冲突执行。新 Attempt只可引用旧结果和证据，不得改写旧 owner、作者、接受者或审计 actor。
- 只有仍未满足且仍可执行的 ResponseObligation 可在同一 succession operation 中为 successor 创建新 routing/inbox entry，并把旧 obligation 标记为 `superseded_by_successor`；已 fetched、ACK、response 和普通历史消息不移动。
- 未选任务保持原状态，submitted/completed 历史不更换 owner。批量继任由 parent Operation 记录逐任务 child result；数据库状态在 project UoW 中提交，外部停止与 reconcile 由持久 Job 收敛。
- `handed_off` 是旧 TaskAttempt 的 `close_reason`，不是 Task 状态。Task 创建 successor Attempt 后进入既有 `claimed` 或 `blocked`；旧 Attempt记录关闭 actor/time、停止证据和 successor attempt reference。
- 只有可信停止证据允许旧 Attempt以 `handed_off` 关闭。外部执行仍可能存活时旧 Attempt保持 `orphaned`，successor Attempt带 overlap/reconcile blocker；统计按 close reason 区分交接、重试、返工、取消和失败。
- predecessor 未确认停止或存在 `outcome_unknown` 时，服务端按 EffectiveAttemptScope、未收敛 Lease、ResourceIntent、workspace/repository refs 和 Operations 生成不可变 `ResidualRiskSet` 与 digest。
- successor preflight 只阻塞与风险集合相交的 write、exclusive 或 external-side-effect intent；可证明不相交和只读动作继续。无法确定风险 scope 时扩大到对应 root/repository 的保守边界。
- stop/reconcile evidence 可逐项消除风险。current main 仅能在自身 delegable scope 且非 user-only/high-sensitivity 边界内接受精确风险；其他情况需 user/control。接受记录绑定 risk digest、attempt、动作、scope、理由和有效窗口，相关输入变化即失效。
- succession UoW 自动处理 predecessor 的全部 `pending` ResponseObligations，不按 request topic 设置不可继承例外：为 successor 创建新的 obligation、RoutingSnapshot 和 InboxEntry，并把旧 obligation 终结为 `superseded`。
- replacement obligation 保留原 response schema、allowed evidence 和 deadline；继任不延长期限。原 request 的聚合改为等待 replacement；这既不是 waive 也不是 satisfied。predecessor 的迟到 response只作历史 evidence，不能满足 successor obligation。
- 旧 Message、recipient、发送者、已完成 response/ACK 和审计主体均不改写。契约参与者替换造成的 proposal/hash/acceptance 后果由后续契约决策显式处理。
- `ReplaceAndRetireAgent` 在提交前展开并冻结完整责任计划；遗漏仍归属 predecessor 的可执行 task、pending obligation、contract duty、grant/session 或未收敛风险即拒绝退休。current main 只有在 policy 允许 handoff 且计划不超出其 delegable boundary 时可自我替换；user/control 始终可执行。
- 一个 project UoW 内完成 authority epoch 切换（需要时）、全量 AgentSuccession、新 Attempts、D127 obligations、D128 proposal revisions、旧 credential/grant 撤销和 predecessor retirement，并统一写 events/outbox/jobs；任一步失败则全部回滚。
- 事务提交后 predecessor 自有 Attempts 按 D125-D126 收敛，其他 workers 的 running grants 按 D89 adoption；外部停止/reconcile 由持久 Operation/Job继续，不延迟逻辑退休。部分任务继任不能同时退休；仅换主且保留旧成员继续使用 `HandoffMainAgent`。
- `retired` 按用户选择是可恢复的成员状态，不是不可逆身份终态。只有同一 adapter installation 与原 `host_conversation_id` 的连续性重新通过 verifier 时，才有资格恢复同一 `agent_id`；new/clear/fork 或 installation reset 仍必须创建新 Agent。
- retirement 发生时仍立即结束 HostSessions/Connections、撤销 credentials/grants/inbox leases，并拒绝退休期间的协调写入；可恢复性不能让旧 token、旧 Connection epoch 或旧 HostSession重新有效。恢复是否需要显式批准、以及恢复哪些责任由后续决策限定。
- retired Agent 的原 conversation 必须提交 `ReactivateAgentRequest`、连续性证据和 fresh capability probe。user/control 始终可批准；current main 只有持有 `agent.reactivate`、project policy 允许且未越过 user-only ceiling 时可批准。
- reactivation UoW 只把成员恢复为 active，并创建全新 HostSession、credential、CapabilitySnapshot 和 `agent_base` grant；旧 token/session/connection 不恢复，也不使用 session rebind。
- reactivation 不恢复 main authority、TaskAttempt ownership、Lease、workspace ownership、task/review grant、pending obligation、contract participant slot 或 approval。既有 succession、replacement Attempts、obligation replacements 与 proposal revisions保持有效；重新承担责任需要新的显式领域命令。
- `AgentSuccession` edges 永不重写并固化精确 task/obligation/contract scope；部分继任允许同一 predecessor 的不同责任流向不同 successors，因此不提供普通 Agent级全局 successor 字段。
- Task 以 `current_attempt_id` 为当前责任权威并保留 attempt/succession provenance；ResponseObligation 与 ContractProposal分别沿 replacement/supersedes refs 解析。API 返回当前对象和有界历史摘要，而不是把旧实体重定向成新实体。
- 只有 `ReplaceAndRetireAgent` 的全量替换维护可重建的 `current_replacement_head` 投影；reactivation 不改写该投影，也不自动恢复任何 current responsibility。投影损坏不能改写原始 edges，只能从持久事件重建。
- 全量责任可在后续显式 transition 中交回曾出现过且当前 active 的 Agent；A->B->A 是有序历史，不按 Agent ID 视为非法环。每个 succession 保存单调 sequence、expected replacement-head revision 和 previous full replacement ref，以 CAS 推进当前 head。
- TaskAttempt、ResponseObligation 与 ContractProposal 每次都创建新实体 ID，其 predecessor/replacement/supersedes 链必须严格无环。继任次数不设业务硬上限；常用查询读物化 head，历史使用 keyset pagination，投影按事件 sequence重建。
- 多任务 succession 先把 selector 展开为精确 task IDs，并固定相关 task/current-attempt、Agent、authority、obligation、contract 和 scope revisions 及 plan digest。提交事务重新验证全部输入，任一项陈旧或不合法则不创建任何迁移记录。
- 校验通过后，全部 AgentSuccession scope、新 Attempts、obligation replacements、proposal revisions、events/outbox/jobs 在一个 project UoW提交。事务外的 stop、workspace/Lease reconcile 与副作用核对使用逐任务 child Operations，可各自收敛为不同结果，但不回滚已提交的逻辑继任。

### 凭据与本地 HTTP

- 首发威胁模型是单用户、本机可信协作：防止普通 API/工具误用、Agent 身份混淆和陈旧会话继续行使逻辑权限；不承诺抵御同一 OS 用户下拥有 Full Access、能够主动读取其他进程/文件的恶意 Agent。
- 守护进程只绑定 `127.0.0.1` 随机端口；首发不监听 LAN、不配置 TLS、不接受 Cookie、关闭 CORS。IPv6 loopback 在完成双栈绑定与 endpoint 校验测试后再开启。
- CLI 使用安装实例专属的 256-bit 随机 opaque control token，作为 `user/control` principal。Agent bridge 不接触该 token；不得把“来自 loopback”直接当作用户权限。
- 每个 Agent host session 使用独立 256-bit 随机 opaque session token。token 只映射到服务端保存的 project、agent、host session 和状态，不携带 role、scope 或 capability claims；服务端只保存 token hash。
- session token 生命周期与 HostSession 一致，在显式 detach/revoke、Agent retire、项目 archive/delete 或会话失效时立即拒绝；首发没有 refresh token、token rotation、JWT 签名密钥、OAuth flow 或系统凭据库集成。
- bridge 在内存中代持 session token；需要跨 bridge 重启恢复时可写入本机 runtime 私有文件。control token 与 session token 都不进入项目 Git、prompt、消息正文、日志、URL 或命令行参数。
- 加入票据仍为默认 10 分钟、单次兑换的随机不透明 token。用户始终可签发；主 Agent只有具备 `agent.enroll` 且在用户上限内才可签发。票据固定 project、candidate/host 条件和权限上限。
- 所有授权在服务端按当前 authority epoch、agent identity、task/attempt owner、grant、root scope、project policy 和 blockers 重新判断。请求体中的 actor ID、role 或 capability 声明不参与认证。
- 一个 token 不得在多个 Agent 间复用。若宿主不能为子 Agent提供独立、可验证的会话/bridge，上报 `agent_identity_isolation=false`，该子 Agent不能作为独立执行 owner 接入首发正式基线。
- 首版不做 API rate limit、远程攻击防护或恶意同用户进程隔离。载荷大小、schema 校验和并发上限仍作为稳定性约束。

### 主从 Agent 与任务边界

- 主 Agent权限不编码在 token 中。管理命令必须满足 `session.agent_id == authority.current_main_agent_id`、当前 authority epoch 和对应 grant；handoff/revoke 后旧 session 即使仍可作为普通 Agent存活，也不能继续执行管理动作。
- TaskAttempt 的 owner 在 attempt 生命周期内不可变。执行命令的 actor 从 session token 导出，并必须等于 `owner_agent_id`；客户端不能通过提交另一个 `agent_id` 接管 attempt。
- 子 Agent只能领取或执行显式分配给自己的任务/attempt。主 Agent需要委派自身工作时创建有依赖关系的子任务，主任务及其 attempt 仍由主 Agent负责。
- 首发不提供“把运行中的主 Agent attempt 直接转给子 Agent”的端点。失联、取消或返工必须先关闭旧 attempt，再按既有状态机创建新 attempt。
- 子 Agent不能 self-appoint、修改 authority、签发超出自身 grant 的票据或代表主 Agent确认契约。成为主 Agent只能经过 D92 的显式 appoint/handoff 命令。

### 首发 Grant 存储

- 使用单一 `authorization_grants` 当前状态表，不实现 OAuth authorization server、JWT claims、不可变 Revocation/Supersession 实体或单独有效权限投影。
- grant 固定 project/lineage/replica、kind、subject agent/session、可选 task/attempt、issuer、authority epoch、capabilities、root/resource scope、policy/ceiling digest、status、revision 和时间字段。
- capabilities、scope、subject 和 epoch 创建后不可原地扩大或改绑。变更通过新 grant 与撤销旧 grant 完成；`active -> frozen|revoked|expired` 使用 expected revision 状态更新。
- 每次签发和状态变化同事务写不可变领域事件/audit。授权 handler 查询当前 grant，并继续与 authenticated session、current authority、TaskAttempt owner、project policy、ceilings 和 blockers 校验。
- role 只用于签发时展开默认 capability template；运行时不得因 role 字符串直接放行。普通 worker grant 不可转授。
- 普通 grant 默认无 `expires_at`，也没有 grant heartbeat。`agent_base` 随 HostSession/成员关系、`main_authority` 随 authority epoch、`task_attempt` 随 Attempt 可执行状态在领域事务中同步冻结/撤销。
- 时间限制只用于 enrollment ticket、D89 handoff transition 和用户显式临时授权。Lease 已负责运行资源的 30 秒 heartbeat/120 秒 TTL，不再复制一套 task grant 续期机制。
- daemon 启动时扫描 active grant 与 session/epoch/attempt 的不变量并幂等收敛；扫描完成前，授权 handler 仍通过实时关联校验拒绝陈旧 grant。
- Capability 使用代码注册的稳定领域动作 ID，REST/MCP 映射到同一 internal action；resource/task/root selectors 另存于 grant scope。
- 首发不支持 wildcard、前缀匹配、用户自定义 capability、策略脚本或按 endpoint/tool 名自动授权。未知 capability 在 attach/schema 验证时拒绝。
- role/template 只在签发时展开 capability 集并记录 template version/digest；运行时不因 role 名直接放行，user-only command 也不包装成可下发的 admin capability。
- 所有 active project Agent 的 base grant 默认包含 `project.read`，用于非秘密共享协调状态；不再为 tasks/agents/cognition/resources 分别维护对象级 read ACL。
- `project.read` 不覆盖 inbox/message body、token/ticket/credential、用户 ceiling、本机绝对路径或敏感配置。消息正文只允许发送时固化的 routing recipient 读取，当前主 Agent也不能任意查看他人 inbox。
- open task 可向项目成员返回足以判断 claim 的协调描述；源码/文件读取仍必须落入该 Agent/attempt 的 root scope。任何 read capability 都不隐含 claim、execute、review 或 mutation。
- `agent_base` 只承载共享读取、自己的消息和 open task claim 等共同能力；`main_authority` 绑定 current authority epoch，承载协调管理；`task_attempt` 绑定 owner/current attempt 和任务 scope；`task_review` 绑定 reviewer、被审 task/attempt 与 review round。
- 主 Agent要执行具体任务也必须先 claim 并获得独立 `task_attempt`；management grant 不能代替 task owner。reviewer grant 不能执行被审任务，task-attempt grant 也不能代替指定 reviewer。
- 每个 command policy 指定可接受的 grant kind。授权不能把一行的 capability 与另一行的 scope/subject 拼成组合权限；user/control principal 继续走明确的 user-only 分支。
- 每个内部 command kind 必须在静态 `CommandPolicy` 注册表声明 allowed principal、一个 required capability、一个 required grant kind、固定 predicates 和 blocker action；user-only command 的 capability/grant 为空。
- 首发不支持 `any_of`、嵌套策略表达式、运行时 policy 文件或 handler 绕过。需要不同权限语义时拆成不同 command kind。
- REST、MCP 和 CLI 均映射到同一 command envelope 与 authorize-and-handle path。注册表完整性检查枚举全部 handlers/commands，存在未注册、重复或未知 capability/grant kind 时启动和 CI 失败。
- 每种 grant kind 使用固定的版本化 scope schema：agent membership、main authority、task attempt、task review 和 handoff transition 不共享任意 selector 表达式。
- scope JSON 按统一 profile/JCS 规范化并保存 digest；task/attempt/session/authority epoch 等常用关系仍有类型化外键列和数据库约束，不只依赖 SQLite JSON 查询。
- Grant scope 不支持布尔表达式、否定 selector、运行时自定义资源类型或跨 grant 拼接。新增 scope type/字段必须经过 schema bundle、迁移和 current/N-1 兼容审查。
- 文件 scope 仅由 `{root_id, access: read|write, path_prefix: string[]}` 正向规则组成。空 prefix 明确表示整个 root，空 rules 表示无文件权限；`write` 包含 read。
- prefix segments 禁止空段、`.`、`..`、分隔符、盘符、UNC 和绝对路径；无 glob、regex、Git pathspec、extension filter 或 deny。多条规则取并集，多层 ceilings/scopes 取交集时保留更窄 prefix。
- 逻辑 scope 匹配不能替代 D87 的本机 binding、case、link/reparse point 和 filesystem identity 验证；受控文件访问在解析后再次确认物理资源仍落在授权 root/prefix。
- Task 在发布时固定版本化 `execution_scope`；claim/preflight 将其与 user ceiling、project/root policy、current main 可委派范围和 adapter/host 能力取交集，生成不可变 `EffectiveAttemptScope` digest，再签发 `task_attempt` grant。
- ResourceIntent 只能在 EffectiveAttemptScope 内选择实际资源和 Lease；需要额外路径/资源时向 current main 发送 `ScopeExpansionRequest`。批准后更新 task scope revision，撤销旧 task grant，显式重新 preflight/resume，禁止原地扩大 running grant。
- Attempt scope 不继承 main-authority 的全部范围；子 Agent不能借 task/resource 声明或自然语言扩大文件、仓库、workspace 或 named resource 权限。
- `ScopeExpansionRequest` 在自身可委派范围内由 current main 批准；超出范围、扩大 user ceiling、加入高敏 root、改变 coordination root 或越过 trust/ownership boundary 时只能由 user/control 批准，主 Agent只能转发结构化请求。
- scope 批准创建新 task scope revision，保存 old/new digest、actor、reason、影响任务和审计事件；受影响 running attempt 进入 `blocked(reason=scope_changed)` 或先停止，释放受影响 leases，旧 grant 撤销，显式 resume/preflight 后新 scope 才生效。
- scope 批准是单阶段 command：事务提交即成为当前 task scope revision 并撤销旧 task grant。owner/current main/user 的 inbox 通知只承载差异摘要和审计，fetched/presented/ACK 不影响生效，也不要求 owner acceptance。

### SSE 变化信号

- Agent 通过 bearer 鉴权连接项目 SSE；SSE 仅发送 `project_id`、project event sequence 高水位和有限 topics，不携带权威消息正文或领域 payload。
- SSE `id` 使用 project event sequence。服务端可合并连续提交并只发送最高水位；客户端不得假设每个 sequence 都有对应 SSE。
- 建连和重连后先发送当前 `sync` 高水位；`Last-Event-ID`/`after_seq` 只用于差距诊断和拉取优化，不承诺逐条重放。
- 持久 inbox 的 delivered/read/ack 状态独立于 SSE。客户端收到信号后经 REST 拉取权威资源并显式 ACK；不建立独立 SSE replay 表。
- 游标未知、跨 project generation 或超出查询范围时发送 `resync_required`，客户端丢弃缓存并读取当前投影。
- 当前宿主桥接使用能发送 Authorization header 的 HTTP 流客户端；未来 Web 工作台使用 Fetch 流式 SSE 客户端，不能依赖不支持自定义 bearer header 的原生浏览器 `EventSource`。
- SSE 使用 15 秒注释 ping 和 30 秒 send timeout；关闭前的 `stream.closing` 只是 best-effort 提示，重连后的 REST 状态才是权威依据。

### 消息请求与响应义务

- Message 是不可变 envelope，包含 kind/topic/schema、服务器写入 sender snapshot、subject/因果引用、priority、时间、受限 summary、结构化 payload 和 request-only response contract。
- routing service 在发送事务中展开逐 Agent `RoutingSnapshot`，固化 route basis、permission/capability snapshot 及 required/optional 标志；同 message/recipient 只生成一个 inbox entry。
- 每个 required recipient 建 `ResponseObligation(pending|satisfied|expired|waived)`。所有 required 已 satisfied/waived 时消息 request 才进入 satisfied；optional 不阻塞。
- 合法 evidence 是绑定原 request/recipient/schema 的 response message，或 owning module 在领域命令同事务产生并登记的 domain event。消息模块不跨表猜测业务事实。
- obligation satisfied 只表示消息请求已获要求证据；契约是否达成、任务是否继续仍由 cognition/tasks 等 owning module 状态机决定。
- ACK 与 response obligation 完全独立；handled ACK 不代表已响应，合法 response 也不替代 inbox ACK。
- deadline 到达使 pending obligation expired 并发 timeout event；迟到 response 可审计但不自动重开。waive 只能来自 owning module 规则或用户权限命令，通用消息 API不能绕过共识参与者。
- payload canonical JSON 最大 256 KiB、summary 最大 4 KiB；更大 diff/log/artifact 必须通过受授权 resource reference 提供。

### 消息投递与背压

- 使用 at-least-once 领取语义；delivery lease 60 秒、每 15 秒续租，单 attempt 最多连续占有 2 分钟。lease 只防并发领取，不证明 exactly-once。
- batch lease 默认 10、最大 20 条且 canonical payload 合计不超过 1 MiB；每 Agent session 最多 20 个 leased entries。
- 领取按 effective priority、available_at、enqueued sequence 和 message ID；每等待 5 分钟提升一个有效优先级，最高 high，显式 critical 始终更高。
- fetched 前 transient failure 使用 1 秒起步、60 秒封顶的 full jitter 重投；连续 5 次主动 push 失败后对该 session 抑制 push 5 分钟，但 pull/SSE 和持久 inbox 继续可用。
- 一旦 fetched，不自动向后续模型回合重复注入正文；连接/任务边界只提示未 ACK 数、最高优先级和最早 deadline。defer 到期或授权的显式 redeliver 才能再推正文。
- transient 离线/推送失败不因次数 alone 进入 dead letter。只有不可重试 schema/protocol/capability 错误或管理员确认永久不可投递时 dead-letter。
- presented/ACK/response 继续独立；expired/dead-letter 只发审计和 owning-module 信号，不自动满足 obligation 或改变 Task 终态。

### Operation、Job 与副作用恢复

- 不能在一个数据库事务内完成的命令先创建调用者可见的 `Operation`；HTTP 返回 `202`、Operation 表示和 `Location`。纯查询和纯数据库命令可同步完成。
- Operation 状态为 `pending`、`running`、`retry_wait`、`cancel_requested`、`succeeded`、`failed`、`cancelled`、`outcome_unknown`。只有取得可验证完成证据才可 `succeeded`。
- 创建 Operation 的同一 Unit of Work 写入首个持久 `Job` 及 event/outbox。每次 worker 领取创建不可变 `JobAttempt`；外部调用不在数据库事务内执行。
- 调用方对创建 Operation 的命令提供 `idempotency_key`，作用域为 project、principal 和 command kind。相同 key/hash 返回原 Operation；相同 key 不同 hash 返回 `409 idempotency_key_reused`。
- handler 必须声明为 `idempotent`、`reconcilable` 或 `unverifiable`。崩溃恢复时前两者可重试或探测接管；无法证明结果的副作用进入 `outcome_unknown` 并停止自动重试。
- cancel 是 best-effort 请求。副作用已经完成且可验证时收敛为 succeeded；已证明未发生或已撤销时才是 cancelled。
- Operation 终态不改写；误判通过 resolution event、补偿或新 Operation 表达，并保留操作者、证据和理由。

### Job 调度默认值

- 守护进程使用 4 个异步 worker；内存事件即时唤醒，1 秒 polling 只作兜底。job execution lease 为 60 秒，每 15 秒续租。
- lease 过期只使旧 worker 丧失所有权。恢复时先关闭旧 JobAttempt 并运行 handler reconcile；仅在证明未执行或可安全重复时创建下一 attempt。
- handler attempt timeout 默认 120 秒，可在 5 秒至 10 分钟范围按 operation kind 覆盖。
- 默认最多 5 次 attempt，handler 可在注册元数据中调整到最多 10 次。只有 transient 自动重试；ambiguous 先 reconcile；其他分类明确收敛。
- 第 n 次重试使用 `uniform(0, min(60s, 1s * 2^(n-1)))` full jitter。可信 `Retry-After` 可延长等待，默认单次最多 15 分钟。
- job 可指定一个 `concurrency_key`，同一 key 同时只运行一个 attempt；它只串行化外部目标，不代替领域 Resource Lease。
- 领取按基础优先级、等待 aging、available_at 和创建顺序；取消/reconcile、用户操作、清理/遥测依次降低，但 aging 防止永久饥饿。
- 非终结 job 使项目保持加载；重启扫描已登记项目数据库恢复。正常关机停止领取并等待 15 秒，未确认停止的 attempt 保留 lease，重启后 reconcile。

### 风险评估协议

- `RiskAssessmentRequest` 是不可变输入快照，绑定 assessment/project/task/attempt、execution epoch、task revision、authority epoch、policy、资源意图、仓库事实、driver 能力与 JCS SHA-256 `input_digest`。
- 当前主 Agent 通过类型化工具提交 `RiskAssessmentSubmission`，包含 risk level、可用 driver 建议、受控 risk factors/required controls、显式 assumptions、confidence 和短 reasoning summary；不采集隐藏思维链。
- 后端始终重新验证 schema、身份、current main agent、epoch、revision、digest、权限和 hard constraints。陈旧响应返回 `409 stale_assessment`，结构错误返回 `422 invalid_assessment`，均不部分采纳。
- 最终不可变 `IsolationDecision` 由内核生成并引用 request、submission、policy version 和裁决理由；模型不能直接写最终决定。
- 影响资源范围、仓库、契约/hard discrepancy、权限、强度或 driver 能力的变化使旧 digest 失效。claimed 任务重做 preflight；running 任务标记 migration_required。
- 同一 assessment 的相同提交幂等成功，不同内容冲突拒绝。用户覆盖或主 Agent策略内降级生成新的审计决定，不改写原提交。
- current main Agent 在线时，assessment deadline 为 120 秒，并在 0/30/90 秒对同一持久 request 尝试提醒；ACK 不等于完成，无效提交不延长 deadline。
- 创建请求时主 Agent离线则立即执行确定性 fallback。满足全部硬约束时，只读任务可选择 shared，单仓库写任务可选择 worktree，用户预设环境或唯一合法候选也可按策略采用。
- 多仓库写入、未知写范围、多个不可比较候选，或缺少任务要求的机械隔离能力时不猜测；Task 保持 claimed，Attempt 停在 `waiting_for_risk_assessment` preflight。
- fallback 决定明确标为 deterministic_fallback 及原因，不伪造模型 risk/confidence。决定形成后迟到提交被拒；可通过显式 re-evaluate 产生新请求。
- current main Agent 或 authority epoch 变化会使旧请求失效，并针对新主 Agent 产生新的请求与 deadline。

## 代码组织与开发运行

- Monorepo 使用单一 Python `src/tsunagou` distribution 承载八个业务模块；四个正式适配器和共享 TypeScript SDK/协议类型作为独立 pnpm workspace 包。
- 八个业务模块固定为 `projects`、`agents`、`tasks`、`cognition`、`resources`、`workspaces`、`durability`、`evaluation`；CLI/API/bootstrap/shared kernel/platform 属于组合或技术层，不新增业务模块。
- 模块按实际需要组织 domain/application/public/infrastructure/api；跨模块同步调用只能导入对方 `public`，异步协作只消费已提交领域事件。
- 各业务模块拥有自己的表、repository 和 projector；durability 只拥有事件、outbox、Operation/Job、checkpoint、迁移/备份机制，不提供绕过模块边界的通用数据访问层。
- Python domain 不得依赖 FastAPI、SQLAlchemy、Git、文件系统或其他业务模块；API 不得直达 repository。Windows 发布检查运行静态 import/table ownership 架构测试。
- JSON Schema 源位于 `protocol/schemas`；Python、TypeScript 领域类型和 OpenAPI HTTP 客户端分别输出到隔离的 generated 目录，并由统一 codegen 检查漂移。
- CLI 使用 Typer + Rich，Click 作为传递依赖；根入口 `tsunagou` 只调用 application public facade 或运行中 daemon 的 REST API，不直接访问 SQLite、Git/worktree 或宿主进程。
- CLI 人类模式可使用 Rich；`--json` 只向 stdout 输出一个稳定 JSON document，日志/提示进入 stderr，且不含 ANSI、spinner 或 markup。颜色仅在交互 TTY 默认启用并尊重 `NO_COLOR`。
- 稳定退出码区分成功、用法、权限、未找到、冲突、validation、daemon 不可用、异步 Operation 失败和内部错误。创建异步 Operation 本身成功返回 0；`--wait-timeout` 只停止客户端等待，不取消 Operation。
- CLI 不接受 bearer/control token 参数；凭据从系统凭据库或受保护降级文件读取。正式 CLI 关闭 pretty exception，traceback 仅进入 verbose/日志诊断。
- 首版命令组为 runtime、daemon、project、agent、task、contract、operation、doctor 和 completion；完整参数/JSON schema 后续逐项定义。
- 配置采用作用域分层：platformdirs 用户配置保存 daemon/CLI 非秘密默认，`.tsunagou/project.toml` 保存 Git 共享身份/逻辑 roots/策略上限，`.tsunagou/local/config.toml` 保存本机路径与宿主绑定，动态业务状态留在 SQLite。
- project TOML 外部编辑仍服从 checkpoint/fast-forward/divergence 规则；影响安全和权限的持久修改通过领域命令执行，再由 outbox 物化，不提供可绕过授权的通用 `config set`。
- 配置 schema 按字段声明 scope、merge strategy、reloadability 和 sensitive。deny 取并集，allow/capability limit 取交集，数值上限取更严格值；local/env/CLI 不得扩大 shared policy。
- 普通启动偏好按显式 CLI、allowlist `TSUNAGOU_` 环境变量、user TOML、内建默认值解析；不自动加载 `.env`，项目策略不参与这条普通覆盖链。
- 跨仓库共享配置只保存稳定 root ID 和可移植 repo identity；本机绝对路径放在 local binding。local 变更完整验证后形成 revision，并按需要触发重评或 migration_required。
- token、join ticket、refresh/service secret 和 provider credential 不得进入 TOML、环境变量、CLI 参数、JSON 输出或日志；配置只保存 opaque credential reference。
- Pydantic v2 验证字段，项目 scoped merge service 执行合并语义，tomlkit 只写项目拥有的托管 section。reload 只原子应用标记为 reloadable 的值。
- REST 与 MCP 共用不可变内部 `CommandEnvelope` 和 action payload schema，但线表示遵循各自传输：REST 用强 ETag/If-Match，MCP tool input 用 `expected_revision`。
- REST mutation body 必填 UUIDv7 `command_id`；v1 不依赖仍未成为 RFC 的 `Idempotency-Key` header。相同 command/hash 返回语义等价结果，不同 hash 复用 ID 返回 409。
- revision-protected REST mutation 缺少 If-Match 返回 428，validator 不匹配返回 412，领域状态冲突返回 409；成功资源表示返回 `ETag: "rev-N"`。
- project/principal/agent/session/transport context 由鉴权和路由层注入，客户端不能用 body 冒充；canonical request hash 不包含 trace/transport，但包含 command kind、目标、revision/epoch 和 payload。
- 错误使用 RFC 9457，稳定扩展包括 code、command_id、trace_id、current_revision、issues 和受限 retry 元数据；MCP 使用同一 machine code/details，不伪装 HTTP status。
- conformance fixtures 将同一命令分别编码为 REST 与 MCP，断言生成的内部 envelope canonical hash 一致。
- REST、MCP、SSE data、JSON/NDJSON、OpenAPI 和生成类型统一使用 ASCII `snake_case`；enum wire value 使用稳定小写 snake_case。
- JSON 使用 UTF-8 无 BOM，拒绝重复 key、非法 surrogate、NaN、Infinity 和负零；普通传输不要求排序，需要 hash 时先做 RFC 8785 JCS。
- revision、sequence、epoch、attempt、计数和 byte 值使用 `0..9007199254740991` JSON integer，并在 domain/数据库边界验证上限。
- instant 固定为 UTC RFC 3339 `YYYY-MM-DDTHH:mm:ss.sssZ`，SQLite 保存 epoch milliseconds；duration/timeout/TTL 使用非负 `_ms` integer，容量使用 `_bytes`。
- UUID 使用小写、带连字符 canonical text并验证版本；领域实体为 UUIDv7。SHA-256 使用 `sha256:<64 lowercase hex>` 并通过具体字段名区分用途。
- absent 与 null 含义由 schema 区分；mutation 使用 action-specific payload，不使用通用 JSON Merge Patch。未知/未算/不适用需要区分时使用状态字段。
- v1 reader 忽略新增 optional property，但不能把未知 enum 映射成现有状态；schema lint 和跨语言 fixtures 检查全部线格式约束。
- 通用列表使用无服务端状态的 HMAC-SHA256 opaque keyset cursor；首次请求提供 allowlist filters/sort/direction/limit，后续只传 cursor。
- 默认 page limit 50、最大 200；响应包含 items 和仅在有下一页时出现的 next_cursor，并同时返回 RFC 8288 `rel="next"` Link。
- cursor 绑定 project、principal、list kind、filter hash、稳定 sort/last values 与 limit，默认 15 分钟有效、最大 2048 bytes；每页重新鉴权，cursor 不授予权限。
- 默认 sort 使用不可变 tuple 并以唯一 ID 收尾；状态过滤是逐页当前视图，不承诺跨请求历史快照。v1 不默认计算 total_count。
- project event/audit timeline 使用 `after_seq`/`next_after_seq`，不包装通用 cursor；SSE watermark 不代表主体能读取每条 event payload。
- 每个 list endpoint 必须同时定义 filter allowlist、sort tuple、匹配 SQL index 和最大 page size，并通过 10 万行深 cursor 性能检查。
- 首版只支持从源码仓库运行，不发布 wheel/单文件可执行程序作为正式安装路径。
- 用户在选定 checkout 中运行显式 runtime register 命令；用户级 launcher manifest 记录规范化路径、代码版本与 uv 路径。路径移动或版本不匹配时拒绝自动启动并给出修复步骤。
- 使用单一 monorepo 管理 Python core/CLI、语言中立 schemas/conformance fixtures、Codex MCP bridge 和三种原生适配器。
- schema 是协议源；派生的 Python/TypeScript 模型和客户端生成产物提交 Git，检查任务重生成并验证无漂移。
- 每个领域模块拥有 domain、application、infrastructure/api 边界；跨模块只调用应用端口或消费已提交事件，禁止直接引用其他模块 ORM 表。
- shared kernel 只放稳定 ID 类型、时间/事件/命令信封和少量跨域值对象，不承载业务服务。
- 每个应用命令一个显式 Unit of Work；事务内只做数据库状态、事件、outbox 与 job 登记，不调用网络、模型或文件系统。
- 查询侧使用同一 SQLite 的专用 SQL/投影，返回 query DTO，不返回 ORM 实体，也不维护第二数据库。
- 后台守护进程由 CLI 启动为隐藏的当前用户进程，写 endpoint/PID/instance 文件；stop 走鉴权优雅关闭。首版不注册 Windows Service。

### 依赖与协议生成

- `pyproject.toml` 和 `package.json` 声明经过验证的兼容范围，`uv.lock` 与 `pnpm-lock.yaml` 精确固定开发和源码运行结果。
- 依赖升级使用独立变更，必须重跑数据库迁移、协议生成、一致性检查和 Windows 阻塞测试。
- 共享 DTO、领域事件和 Git 共享文件以 JSON Schema 2020-12 为源；生成 Pydantic v2 与 TypeScript 类型。
- FastAPI OpenAPI 引用生成的 Pydantic 模型；TypeScript HTTP 类型/客户端再从固定 OpenAPI artifact 生成并提交 Git。
- Python 3.13 使用固定版本 `uuid6` 实现 UUIDv7，但领域代码只能调用项目自有 ID factory；未来切换标准库不改变领域接口。
- TypeScript 适配器首版支持 Node `>=24.19 <25`；固定 CI 基准并验证 24.x 最新补丁，Node 26 成为 LTS 后经四适配器回归再扩展兼容范围。
- 使用 pnpm 12；仓库声明带完整性哈希的精确 `packageManager` 和 `devEngines.packageManager` 的 `>=12 <13` 范围，提交 `pnpm-lock.yaml`。引导流程安装固定的用户态 Corepack，不依赖 Node 捆绑副本。
- TypeScript 7 使用 strict、ESM 与 NodeNext，首个声明范围为 `>=7.0 <7.1`；适配器包不得混用 CommonJS。
- `datamodel-code-generator` 只输出 Python Pydantic 协议模型，`json-schema-to-typescript` 只输出 TypeScript 领域协议类型，`openapi-typescript` 与 `openapi-fetch` 只负责 HTTP 端点类型和客户端。输出目录互不覆盖。
- codegen 使用固定命令和稳定排序；CI 重生成后要求 Git 工作树无差异。
- `uv run --locked python -m tools.codegen` 是 lint/generate/check/fixtures 的唯一跨平台入口；Node 依赖预先通过 frozen pnpm lock 安装。
- 编排器按显式 bundle source 清单发现 schema，禁止 remote ref；在临时 staging tree 完成全部生成、格式化、typecheck 和 hash 验证后才原子替换目标。
- `check` 只在临时目录重生成并比较，不修改工作树；generation manifest 记录输入 schema/hash、bundle、工具/config、输出 hash 和 OpenAPI hash。
- Pydantic 模型按业务模块 aggregate schema 生成；TypeScript 领域类型从单一 deterministic aggregate bundle 生成，不依赖 experimental multi-file imports。
- OpenAPI 从 schema-only FastAPI app factory 导出，不打开 DB/凭据/Git/worker；openapi-typescript 生成 paths/components，手写 openapi-fetch wrapper 处理认证、版本、ETag、错误和 SSE。
- 公开跨语言 DTO 只允许经过 Draft202012 runtime validator、Pydantic、TS compile fixture 验证的 schema keyword 子集；生成器已知忽略/部分支持的高级关键词默认禁止。
- 生成产物统一 LF/UTF-8、无时间/用户/绝对路径；文件头记录工具版本、bundle digest 和 schema ID。生成器升级必须独立提交并做兼容审查。
- `requires-python` 首版声明为 `>=3.13,<3.14`；增加 Python minor 必须先通过数据库、异步运行时、凭据、codegen 与四适配器回归。
- `pyproject.toml` 表达进入升级评估的窄候选窗口：核心 `0.x` 与紧耦合工具锁当前 minor，稳定库锁下一个 major；`uv.lock` 精确固定正式开发、CI 与源码运行组合。
- `uv sync`/`uv run` 默认使用 `--locked`；依赖升级按 Web、数据库、协议生成和遥测分组提交，禁止无边界整体升级。
- FastAPI/Uvicorn 使用显式直接依赖，不采用大包 extras；`rfc8785` 与 `uuid6` 通过项目接口封装并精确固定。

### 版本与兼容窗口

- Python core/CLI 和四个 adapter 使用统一 monorepo SemVer release；宿主版本窗、实时协调协议和磁盘格式不能从产品版本推断。
- 实时协议使用 major.minor，REST URL major 与之对齐；daemon 正式支持当前 minor N 与 N-1，attach 时选择最高共同版本，无交集则返回双方支持集合并拒绝。
- attach 记录 adapter product/protocol/schema bundle、host kind/version 和 probed capabilities；选中版本绑定 session、token family 和 capability snapshot。宿主 MCP/A2A 版本单独记录。
- 每个 JSON Schema 使用不可变 `urn:tsunagou:schema:<module>:<name>:<semver>` `$id`；`protocol/bundle.json` 固定列出 schema hash、generator version 和 bundle digest。
- 相同协议版本但未知 bundle digest 的 adapter 不计入正式支持；生成文件头记录 schema IDs、bundle digest 与生成器版本。
- `.tsunagou` 共享文件使用独立 `shared_format_version`；同 major 保留已发布 forward migration 和 golden fixtures，遇到未来/未知格式只读诊断，major upgrade 使用显式 Operation。
- SQLite Alembic revision 独立于共享格式；已发布 migration 不删除或改写。release manifest 记录 product/protocol/bundle/shared format/Alembic/宿主矩阵映射。
- minor 只容纳可投影的兼容新增；新 enum 仅对协商新 minor发送。required 字段、删除/重命名或状态语义变化升 major，不进行有损 down-conversion。
- 每次 release 对 current/N-1 跑双传输 conformance、四 adapter 模拟和共享格式 golden migration；移除 N-1 前至少一个已发布 minor 提供 deprecation 信号。

## 可观测性、测试与评估

### 遥测与隐私

- 本地 JSON 结构化日志与领域时间线始终可用；trace/metric 使用 OpenTelemetry，默认不外发，可配置 OTLP endpoint。首版不内置 Collector、Prometheus 或 Grafana。
- 默认只记录 ID、类型、耗时、大小、哈希和状态，不复制 prompt、源码、消息正文、token、秘密或命令输出。
- 项目可对指定类别限时开启内容采样，并应用字段级脱敏；采样配置和访问也需审计。
- 用户选择本地统一 token 估算，但未知模型不统计。已知模型使用固定版本 tokenizer；隐藏上下文、缓存和账单费用不推算，缺失值不能按 0 参与比较。

### 实验设计

- 先使用确定性微基准和故障注入验证状态机、消息、租约、恢复与去重；再在固定中型仓库运行四组：A 单 Agent、B 多 Agent Worktree、C 完整系统、D 关闭认知协商的消融组。
- 每组至少 5 次且随机运行顺序。主实验固定同一宿主、模型、提示、预算和版本，只改变协调条件；再选择至少另一宿主复验方向。
- 四种适配器分别进行 conformance 检查，不能把不同宿主混成同一统计样本。
- 预注册门槛：最终测试全部通过；故障恢复无状态丢失或重复 owner；注入 hard discrepancy 检出率至少 95%，误阻塞率不高于 5%；C 相比 B 的人工干预和冲突返工中位数至少下降 30%，完成时间劣化不超过 10%，在双方 token 可比较时估算 token 增幅不超过 25%。

### 测试与发布取舍

- 普通自动测试覆盖核心领域、协议模拟器和录制回放。
- 用户选择真实 Coding Agent smoke/e2e 首版只做手工验收，不作为 PR/nightly 自动任务；因此发布清单必须记录四宿主版本、人工场景、结果与验收人。
- 用户选择只有 Windows 测试阻止发布。macOS/Linux 测试可作为非阻塞兼容信号；对外兼容说明必须如实区分正式 Windows 支持和未阻塞平台风险。

## 自治、黑板挂起与恢复

### 责任提交与外部收敛

- 继任、退休、外部停止和副作用核对不能共享一个“成功”布尔值。逻辑 succession 在 project UoW提交后立即形成新的 current responsibility；外部工作由 parent Operation 和逐任务 child Job收敛。
- 存在事务外工作时 REST 返回 `202 Accepted`、succession resource、`operation_id` 和 `Location`；MCP/CLI返回同一 Operation 引用。无外部工作时可返回 `200 OK`。同 command/hash 重试返回原结果。
- Operation 的 `succeeded` 只表示计划内外部收敛取得可验证证据；`outcome_unknown` 保留 ResidualRiskSet，不改写已提交 succession。Task/Attempt 查询同时返回 current owner/attempt 与 convergence blockers。

### 残余风险与自治延长

- predecessor 未停止或副作用未知时，服务端根据 EffectiveAttemptScope、Lease、ResourceIntent、workspace/repository refs 和未知 Operation生成带 digest 的 ResidualRiskSet；successor preflight仅阻塞相交 write/exclusive/external-side-effect intent。
- 主 Agent可以在任务继续期间持续延长已登记风险接受，覆盖项目范围并直到任务完成；系统不按延长次数或累计时长强制用户介入。每次延长仍记录 risk digest、scope、理由、actor、关联 Attempt 和审计事件。
- 用户预设的 project/user ceiling、禁止动作、协调根边界和重大项目方向变化仍是硬约束。主 Agent不能用风险接受突破这些上限；输入 digest、workspace、repository baseline 或未知 Operation变化会使原接受失效并重新预检。

### 重大决策与黑板依赖

- 主 Agent在用户总体边界内默认自主处理普通调度、任务拆分、资源安排、适配器选择和风险处理。只有项目设计/方向、重大目标或验收变更、任务最终完成、关键不可协调冲突、ceiling外请求和用户明确保留事项创建 UserDecision。
- UserDecision 是持久依赖，不含“用户响应超时”语义。决策包保存背景、候选、推荐、影响范围、风险、可逆性、依赖动作和确认结果；确认前只将依赖动作置为 `awaiting_user_decision`，无关任务继续。
- BlackBoardBlocker 保存 blocker ID、owner task/attempt、原因类型、依赖 refs、required evidence、当前 revision、状态和可恢复条件。Agent可在 blocked 状态提交阶段性材料和新的协调事实；系统不把无新对话解释为拒绝或失败。

### Attempt 挂起与恢复

- Agent提交阶段结果、`blocked_on` 和恢复条件后，Attempt进入既有 `blocked`（必要时附 `suspended` projection）；持久化理解、假设、已完成工作、未决依赖、证据和下一步，不要求连接或对话继续存在。
- 依赖满足、契约更新、资源可用或 blocker 消除时写入 `resume_eligible` 事件。它只表示具备恢复资格；不自动唤醒，不直接恢复执行，也不要求外部工具反复重启对话。
- 原 Attempt Agent可在任意合适时机提交 `ResumeAttempt`。调度器、主 Agent和适配器可以观察、提醒、提供上下文，但不能替原 Agent决定恢复时间。恢复时重新运行权限、scope、契约、风险、workspace 和资源 preflight。
- preflight发现变化时保留原 Attempt并生成新的 typed blocker；blocked 状态仍允许认知报告、澄清、契约提案/接受、资源意图修订和 ResumeAttempt。只有会话连续性丢失、用户明确换人或无法安全继续时才创建 successor Attempt。

### 代行契约与材料权限

- 主 Agent可在 blocked 状态推进相关资源和执行条件变化；每次操作都生成新 revision、理由和审计，不伪造原 Agent报告或执行证据。
- 项目策略允许主 Agent代行某类契约决策时，契约模块记录 `proxy_acceptance`：真实 actor 是主 Agent，绑定策略 revision、授权范围、理由和受影响参与者；不把它写成其他参与者直接接受。
- 策略未授权时，主 Agent只能创建或推进 Proposal，仍需 required participants 对同一 content hash 接受。契约新 revision 生效后，受影响 Attempt重新预检。

## 仍待决定

- Codegen 最终 flags、bundle/config 文件格式和 schema subset lint 的完整规则。
- Task、TaskAttempt、EpistemicReport、Contract、Lease 等完整字段表和 REST/MCP 端点清单。
- 外部副作用操作、operation 资源、后台 job 的详细状态机和重试退避。
- SSE 游标保留、重放窗口和 project unload 对长连接的影响。
- 主 Agent 风险评估 request/response schema 和 LLM 输出不可用时的超时/重试策略。
- 模块八的人工干预定义、故障注入目录、基准仓库选择与统计报告格式。
- 发布版本、共享 schema 兼容、适配器版本矩阵更新及手工签字流程。
