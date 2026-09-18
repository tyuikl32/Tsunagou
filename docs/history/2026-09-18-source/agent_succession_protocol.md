# Agent 继任与工作迁移

> 核对日期：2026-09-17。
> 状态：第 200-202、204-205、207-212 题已确认 A，第 203、213-214 题已确认 B，第 206 题已确认 C。承接 D16-D17、D34-D36、D39、D41、D51、D63、D73-D74、D89、D92、D94 和 D123-D138；自治与恢复细节见 [agent_autonomy_blackboard_resume_protocol.md](./agent_autonomy_blackboard_resume_protocol.md)。

## 适用边界

- 同一 installation + conversation 只是 token/Session 损坏时使用 D123 rebind，继续同一 `agent_id`，不叫继任。
- 新 conversation、clear、fork、installation reset 或无法证明 continuity 时创建新 `agent_id`。若新 Agent要接替旧工作，必须建立显式 succession。
- 当前主 Agent的替换走 D92 authority handoff；普通 Agent succession 不能暗中改变 current main。
- 历史 TaskAttempt owner、消息作者、契约接受者、报告作者和审计 actor 永不改写。

## 第 200 题：继任时如何迁移未完成工作（已确认 A）

### A：显式选择任务，关闭旧 Attempt并创建新 Attempt；不转移 Lease（已确认）

- user/control 或 current main 提交 `ApproveAgentSuccession`，指定 predecessor、successor、reason、expected revisions，以及零到多个未完成 task IDs；可用“全部当前未完成任务”作为服务端展开后固化的批量选择。
- 对每个选中任务：使旧 execution epoch/grant 失效；有可信停止证据时关闭为 `handed_off`，否则进入 `orphaned`/residual-risk；释放或等待收敛旧 leases；为 successor 创建新的不可变 TaskAttempt，初始为 `claimed` 或带 reconcile blocker 的 `blocked`。
- successor 必须重新运行 workspace/risk/cognition/contract/scope/resource preflight；不继承旧 Lease、workspace ownership、未完成副作用 intent、approval 或 execution grant。可引用旧 attempt 的结果/证据作为输入。
- 未选任务保持原状态，不因 succession 自动迁移。submitted/completed 历史不换 owner；若之后 changes_requested，需要显式创建 successor 新 attempt。
- 发送给 predecessor 且仍有未满足 ResponseObligation 的 actionable request，可在同一操作中为 successor 新建 routing/inbox entry，并把旧 obligation 标为 `superseded_by_successor`；已 fetched/ACK/response 和普通历史消息不移动、不改收件人。
- 批量操作以 parent Operation 记录逐 task child result；数据库内可一次完成的状态变化按 project UoW 原子提交，外部停止/reconcile 仍按持久 jobs 收敛。

优点：与不可变 Attempt、Lease 重取和身份审计一致；既支持任务级选择也支持整体退休。代价：successor 需要重新 preflight，不能无缝接着旧进程写。

### B：原地把旧 Attempt、Lease 和 inbox owner 改为 Successor（已否决）

- 修改 owner_agent_id/session_id，保留原 execution epoch、workspace 和 Lease，继续执行。

优点：交接最快。代价：改写历史身份，旧外部进程仍可能并行；Lease/Grant/契约接受证据不再可信，违反 D34。

### C：只建立 Succession 关系，不自动处理任务或消息（已否决）

- 记录 predecessor/successor 后，由主 Agent逐个取消、重开、重新发送消息。

优点：继任 command 最小。代价：大量重复操作容易遗漏，无法提供 D17 已要求的任务级/整体继任语义。

## 选择 A 时的 Succession 记录

```text
AgentSuccession
  succession_id, project_id
  predecessor_agent_id, successor_agent_id
  initiated_by, authority_epoch
  mode selected_tasks | all_unfinished
  expanded_task_ids, request_obligation_ids
  reason_code, created_at
  operation_id, status
```

每个新 TaskAttempt 保存 `predecessor_attempt_id` 与 `succession_id`。这只是 provenance，不允许 successor 代表 predecessor 接受契约或响应历史消息。

## 第 201 题：`handed_off` 应如何进入状态模型（已确认 A）

### A：作为 Attempt 的终态关闭原因，不新增 Task 状态（已确认）

- Task 继续沿用既有扁平状态；succession 创建新 Attempt 后，Task 指向 successor 的 current attempt，并进入 `claimed` 或 `blocked`。
- 旧 Attempt 进入统一终态 `closed`，以 `close_reason=handed_off`、`closed_by`、`closed_at`、停止证据和 `successor_attempt_id` 表达交接结果。
- 只有已取得可信停止证据时才允许 `handed_off`。外部执行是否停止仍未知时，旧 Attempt 保持 `orphaned`，新 Attempt 带 overlap/reconcile blocker，直到风险收敛或用户显式接受残余风险。
- 指标可按 close reason 区分 handoff、retry、changes_requested、cancel、failure 等原因，不扩张 Task 状态机和 API 过滤集合。

### B：把 `handed_off` 加为 Task 的独立状态（已否决）

- 旧 owner 退出后 Task 先进入 `handed_off`，再由 successor claim。

优点：界面直接显示交接。代价：它是瞬时流程步骤而非业务状态；批量继任时增加额外转移、事件与恢复分支，并且无法单独表达旧 Attempt 尚未停止而新 Attempt 已建立的情况。

### C：统一映射为 `cancelled`（已否决）

- 旧 Attempt和 Task 都按取消处理，在 reason 中记录 succession，新 Agent需要重新 open/claim。

优点：状态种类最少。代价：把任务被放弃与执行者更换混为一谈，破坏成功交接统计，也使同一 Task 上的新 Attempt 语义不自然。

## 第 202 题：旧执行未确认停止时如何阻塞继任工作（已确认 A）

### A：按冲突 scope 精确阻塞，越权接受沿既有授权层级（已确认）

- 服务端从 predecessor 的 EffectiveAttemptScope、未收敛 Lease、ResourceIntent、workspace/repository refs 和 `outcome_unknown` Operations 生成不可变 `ResidualRiskSet` 与 digest。
- successor 的每项 preflight intent 与风险集合求交；只有相交的 write/exclusive/external-side-effect 动作被阻塞。可证明不相交的任务和只读动作可以继续；风险 scope 无法确定时按受影响 root/repository 的最宽边界阻塞。
- stop/reconcile evidence 可使对应风险项自动 resolved。current main 只能在自己的 delegable scope 且不涉及 user-only/high-sensitivity 边界时批准精确风险接受；其余必须由 user/control 批准。
- 风险接受必须绑定 risk digest、successor attempt、动作/scope、理由和有效窗口；任何 scope、workspace、repository baseline 或未知 Operation 变化都会使批准失效并重新 preflight。

### B：阻塞整个 Task，由当前主 Agent统一强制继续（已否决）

- 任一旧执行风险都使 successor Task blocked；current main 可用一次 force-resume 解除全部风险。

优点：实现简单。代价：无关工作也停顿，且一次宽泛批准会掩盖多个不同副作用与资源冲突。

### C：冻结整个 Project，只允许用户在旧进程停止后解除（已否决）

- 任何 predecessor 未停止或 Operation outcome unknown 都阻止全项目写入；不提供风险接受，只认机械停止和 reconcile evidence。

优点：最保守。代价：一个失联 Agent即可长期冻结多仓库项目，不符合本机多 Agent持续协作目标。

## 第 203 题：未决响应义务能否转给 successor（已确认 B）

### A：由 ResponseContract 显式声明可替换，并创建关联的新 obligation（已否决）

- 每种 request topic 的注册 ResponseContract 固定 `recipient_replacement_policy=forbidden|agent_successor`；默认 `forbidden`。契约接受、身份签字、特定 reviewer 判断等主体绑定义务必须禁止替换。
- 对允许替换且仍为 pending 的 obligation，succession UoW 原子创建同一 request 下的新 successor obligation/routing/inbox entry，并把旧 obligation 终结为 `superseded`，保存 `superseded_by_obligation_id` 和 succession evidence。
- 新 obligation 继承原 response schema、allowed evidence 和原始 deadline，不因继任延长期限；原 request 的聚合从旧 obligation 改为等待新 obligation。该动作既不等于 waive，也不等于 satisfied。
- predecessor 后续 response 仍作为不可变 late/superseded evidence 保存，但不能满足 successor obligation；successor 必须以自己的身份提交合法 response/domain evidence。
- 不允许替换的 pending obligation 保持原状，直到 owning module 按其规则超时、waive、取消业务动作或创建一条新的 request；通用 succession API不能绕过领域参与者要求。

### B：自动把所有 pending obligation 转给 successor（已确认）

- 只要 Agent建立 succession，所有未满足 request 都改由 successor 响应。

优点：交接最省操作。代价：继任者可替代原参与者接受契约、签字或作出专属判断，破坏身份与共识语义。

### C：永不替换 obligation，只允许创建全新 request（已否决）

- 原 obligation 保持到 timeout/waive；需要 successor 处理时由 owning module 重新发送一个完整 request。

优点：语义最严格。代价：对普通状态查询、任务补充信息等可安全继承的请求产生重复请求和两个并行 deadline。

## 第 204 题：契约参与者被 successor 替换后如何处理既有接受（已确认 A）

### A：生成新 Proposal revision，并要求全部必要参与者重新接受（已确认）

- succession 自动创建一个正文与 scope 相同、但 `required_participants` 已将 predecessor 替换为 successor 的新不可变 proposal revision；新 participant set 进入 content hash。
- 原 proposal 与其未决 acceptance obligations 被 supersede；原有 acceptances 保留为历史 evidence，但因为绑定旧 hash，不能计入新 revision。
- 为新 revision 的全部 required participants 自动创建 acceptance obligations；successor 和其他参与者都必须对同一新 hash 明确接受，之后才能形成生效 Contract。
- 已经生效的 Contract 不被继任静默改写；若 successor 的工作需要取代其中 predecessor 的职责，必须自动发起 superseding proposal，并使相关 Task在迁移前保持 contract blocker。

### B：只要求 successor 接受，其他参与者的旧接受继续有效（已否决）

- participant list 改变并产生新 hash，但系统把其他参与者对旧 hash 的接受自动沿用到新 proposal。

优点：交接快。代价：系统把“正文未变”推断成参与者同意“责任主体已变”，旧签名/接受证据实际上不覆盖新 hash。

### C：successor 直接占用 predecessor 的接受槽位（已否决）

- 不创建新 proposal；successor 的 response 满足指向 predecessor 的原 obligation，既有 hash 与 acceptances 全部保留。

优点：数据变化最少。代价：required participant、响应 actor 和接受主体彼此不一致，直接破坏 D39 的身份与同一哈希约束。

## 第 205 题：主 Agent交接、全部工作继任与退休如何组合（已确认 A）

### A：提供单一原子 `ReplaceAndRetireAgent` 组合命令（已确认）

- user/control 始终可调用；current main 仅在 policy 允许其 handoff、successor 与全部目标范围都不超过自身可委派边界时，可用该命令替换并退休自己。普通 Agent整体退休也复用同一 orchestration。
- 命令在写事务前展开并冻结完整计划：expected project/authority/agent/task/obligation revisions、全部未完成 task IDs、pending obligation IDs、受影响 contracts、grants、sessions 和 residual risks。遗漏任何仍归属 predecessor 的可执行责任即拒绝退休。
- 一个 project UoW 内按逻辑顺序完成：验证全计划；若 predecessor 是 current main，先切换 current main 并递增 authority epoch；创建 AgentSuccession 与 successor Attempts；执行 D127 obligation replacements 和 D128 proposal revisions；撤销旧 credential/grants；最后把 predecessor 标为 retired，并写 events/outbox/jobs。
- 整个数据库变更一起提交或回滚，不产生“已换主但任务未迁移”的可见中间态。事务提交后，predecessor 自有 Attempts走 D125-D126；其他 workers 的 running grants 才进入 D89 adoption。外部停止/reconcile 是持久 Operation/Job，不延迟逻辑退休。
- 若只想换主但保留旧 Agent为普通成员，继续使用现有 `HandoffMainAgent`；若只迁移部分任务，不允许在同一命令中 retire predecessor。

### B：严格串行执行 handoff、succession、retire 三个命令（已否决）

- 每步独立提交；调用方根据前一步结果继续，失败后人工恢复。

优点：复用现有命令最多。代价：中间状态可见且进程崩溃后需要复杂恢复，旧主 Agent可能已失去执行后续步骤的权限。

### C：组合替换只允许 user/control，主 Agent不能自我交接并退休（已否决）

- 仍提供原子组合命令，但 current main只能请求用户执行。

优点：退休主 Agent的控制边界最保守。代价：计划性会话轮换也必须打断用户，弱化主 Agent在用户 ceiling 内的自治。

## 第 206 题：退休身份、迟到流量和旧宿主进程如何处理（已确认 C）

### A：`retired` 是不可逆身份终态，全部迟到协调写入拒绝（已否决）

- retirement UoW 撤销 Agent 的全部 HostSessions、credentials、connections、grants 和 inbox delivery leases；每个授权 handler 在提交前复核 Agent 仍为 active，因此事务前已进入、退休后才提交的命令也返回 `agent_retired`，不产生领域写入。
- 旧 token、同一 conversation 的 resume/rebind/enrollment 都不能恢复该 `agent_id`。若用户之后确实要让该宿主对话重新参与，必须创建新的 Agent identity，并以 provenance 指向 retired Agent；不能 unretire。
- predecessor 的迟到 ACK/response/progress/lease renew 均拒绝；请求 payload 不落入业务历史，只记录受限的认证/审计元数据。需要保留的旧进程产物由 user、successor 或 current main 作为明确来源的 external evidence 重新提交。
- managed-launch 进程由系统发优雅停止并按已批准策略终止；attached 进程只收到 stop/detach 通知并被撤销协调权限。无法证明停止时保留 D126 ResidualRiskSet，不能宣称进程已被隔离。

### B：退休后保留 120 秒只读/收尾宽限期（已否决）

- 旧 session 在宽限期内可提交最终进度、ACK、response 和停止证据，但不能领取新任务或获得新 lease；到期后彻底撤销。

优点：更容易收集最后状态。代价：退休不再是清晰的提交边界，D127 已替换的 obligations 可能收到双重响应，在途命令权限更难判断。

### C：`retired` 可由原 conversation 重连后重新激活（已确认）

- 保留身份与 HostSession历史；用户或主 Agent可撤销 retirement 并恢复同一 agent_id。

优点：误退休恢复方便。代价：继任链、撤权、契约参与者替换和旧身份终态都可被逆转，审计与并发语义显著复杂化。

## 第 207 题：恢复 retired Agent 时由谁批准、恢复哪些状态（已确认 A）

### A：显式 Reactivate；主 Agent可在策略内批准；只恢复成员身份（已确认）

- 原 conversation 发起 `ReactivateAgentRequest`，提交同 installation/conversation evidence 和 fresh capability probe；user/control 始终可批准，current main 仅在持有 `agent.reactivate`、项目 policy 允许且未越过 user-only ceiling 时可批准。
- 批准 UoW 把 Agent 从 retired 改为 active，创建全新的 HostSession、credential、CapabilitySnapshot 和 `agent_base` grant。旧 session/token/connection 不恢复，也不走 D123 rebind。
- 不恢复旧 main authority、TaskAttempt ownership、Lease、workspace ownership、task/review grant、pending obligation、contract participant slot 或旧 approval。此前 succession、replacement attempts、obligation replacement 和 proposal revisions 全部保持有效。
- 需要重新承担工作时，由 current main/user 创建新的 succession/task assignment、contract revision 或 authority appointment；reactivation 本身不能抢回 successor 正在执行的责任。

### B：只有 user/control 可以显式 Reactivate；仍只恢复成员身份（已否决）

- 技术行为与 A 相同，但 current main没有批准能力。

优点：身份复活边界更保守。代价：主 Agent可以新接入一个 Agent，却不能恢复具有同等基线且连续性更强的旧身份，日常会话轮换需要用户介入。

### C：验证原 conversation 后自动恢复退休前全部状态（已否决）

- reconnect 自动激活 Agent，并尝试恢复原角色、tasks、grants、obligations 和 contract positions。

优点：表面连续性最好。代价：会夺回已经迁移给 successor 的责任，复活旧 authority epoch/授权证据，并破坏 D124-D129 的不可变迁移结果。

## 第 208 题：连续多次、部分任务继任如何查询 successor（已确认 A）

### A：保留不可变 Succession DAG，按责任范围维护解析投影（已确认）

- `AgentSuccession` edge 永不重写，包含精确 task/obligation/contract scope；因为同一 Agent可把不同任务交给不同 successors，系统不为普通部分继任声明唯一的全局 `current_successor_agent_id`。
- Task 查询以 `current_attempt_id` 为权威，同时返回不可变 `predecessor_attempt_id/succession_id` 链摘要；obligation 和 proposal 各自通过 replacement/supersedes refs 查询当前项。
- 只有 `ReplaceAndRetireAgent` 的全量替换关系维护 `current_replacement_head` 物化投影，便于从 A -> B -> C 直接找到 C；投影可重建，原始 A->B、B->C edges 与各步证据保留。
- reactivation 旧 Agent只改变成员状态，不改写投影、不回滚 successor，也不自动重新成为任何任务的 current owner。新的反向继任会产生新 edge，并禁止同一责任范围形成环。

### B：把全部继任链压缩为全局唯一 successor（已否决）

- A -> B -> C 后把 A、B 的 successor 都改为 C，并把旧任务/消息查询统一重定向到 C。

优点：查询最简单。代价：无法表达 A 的不同任务分别交给 B/C，也会隐藏中间责任、接受和残余风险证据。

### C：只保存原始 edges，不维护任何解析投影（已否决）

- 所有调用方按需遍历 succession、attempt、obligation 和 proposal 链。

优点：写模型最小。代价：每个 API/适配器重复实现遍历、环检测和范围筛选，长链查询与一致性更难控制。

## 第 209 题：责任能否在多次继任后转回早期 Agent（已确认 A）

### A：允许 Agent ID 重复，以不可变 transition 次序判定当前责任（已确认）

- A 全量替换为 B 后，若 A 已按 D131 恢复为 active，合法的新命令可再把 B 的责任交给 A；这会形成时间序列 A -> B -> A，但不是实体引用环。
- 每个 `AgentSuccession` 保存 `sequence`、`predecessor_replacement_head_revision` 和可选 `previous_full_replacement_id`；新全量替换使用 CAS 推进 head。当前责任由最新已提交 transition 决定，不通过 Agent ID 递归追到“从未出现过的末端”。
- TaskAttempt、ResponseObligation 和 ContractProposal 使用每次新建的实体 ID 形成严格无环 replacement chain。Agent ID 可以重复，attempt/obligation/proposal ID 不得重复或回指祖先。
- 不设业务上的最大继任次数；历史列表使用 keyset pagination，常用查询读取物化 current head。投影可按 succession sequence/event 重建；同一 expected head 的并发分叉只有一个 CAS 成功。

### B：禁止责任转回继任链中出现过的任何 Agent（已否决）

- 全量 replacement ancestry 中出现过的 Agent永远不能再次成为该链 successor，即使已重新激活。

优点：Agent级图天然无环。代价：D130-D131 恢复旧身份后仍不能承担原项目的整体职责，用户必须不断创建新身份。

### C：允许转回，但覆盖或压缩旧 succession edges（已否决）

- B -> A 时删除或重写 A -> B，使当前关系再次表现为 A。

优点：当前图很短。代价：丢失责任曾由 B 承担的审计、契约、残余风险和时间顺序。

## 第 210 题：一次选择多个任务继任时是否允许部分提交（已确认 A）

### A：内部迁移全有或全无，外部收敛逐任务进行（已确认）

- `ApproveAgentSuccession` 先解析 selector 并固化 task IDs，再读取每个 Task/current Attempt、predecessor/successor Agent、authority、obligation、contract 和 scope revisions，生成不可变 plan digest。
- 一个 project UoW 重新验证全部 expected revisions。任一任务已换 owner、进入不允许状态、scope 不合法或 replacement 冲突时，整个内部迁移失败，不创建任何 succession/new Attempt/replacement obligation。
- 成功时全部选中任务、新 Attempts、obligation replacements、proposal revisions、events/outbox/jobs 一次提交，使读取者不会看到同一批责任只迁移一半。
- 事务后的 stop、workspace reconcile、Lease释放和外部副作用核对按任务 child Operation独立收敛，可分别 succeeded/blocked/outcome_unknown；这不回滚已经提交的逻辑继任，失败项通过 D126 blocker 暴露。

### B：按任务 best-effort 提交，允许同一批次部分成功（已否决）

- 每个任务独立事务；parent Operation 汇总 succeeded/failed 列表。

优点：一个陈旧任务不阻塞其他任务迁移。代价：调用者在崩溃或重试后必须理解半迁移责任，契约/obligation 跨任务关系可能只更新一部分。

### C：批量 API 只展开成客户端逐任务命令（已否决）

- 服务端不提供批量事务或 parent Operation；CLI/主 Agent循环调用单任务 succession。

优点：服务端命令最小。代价：没有一致 plan digest，无法可靠支持“全部未完成任务并退休”之外的多任务原子交接。

## 第 211 题：API 如何区分逻辑继任提交与外部收敛（已确认 A）

### A：双层结果；逻辑提交立即可见，外部收敛由 Operation 表达（已确认）

- succession command 在 project UoW提交后立即产生不可变 `AgentSuccession` 和新的 current responsibilities；响应明确 `logical_status=committed`，不会等宿主进程、workspace、Lease 或外部副作用核对完成。
- 只要存在事务外工作，REST 返回 `202 Accepted`、succession resource ref、`operation_id` 和 `Location`；MCP/CLI 返回同一 Operation ref。Operation/child jobs 跟踪 stop/reconcile/convergence，最终结果不改写已提交 succession。
- 完全没有外部工作时可返回 `200 OK` 的已提交资源；相同 command ID/hash 重试必须返回原 HTTP 语义和资源/Operation refs。
- Task/Attempt 查询同时暴露 current owner/attempt 与 convergence blockers；`Operation.succeeded` 只表示计划内收敛工作有证据完成，`outcome_unknown` 保留 D126 风险并阻止相交动作。

### B：等待全部外部工作完成后才提交并返回成功（已否决）

- 旧进程停止、Lease释放、workspace与副作用核对全部完成后，才在数据库切换责任。

优点：一个“成功”概念。代价：外部动作无法纳入 SQLite事务，长时间等待会让旧 owner 与 successor 的权威边界保持模糊，崩溃恢复困难。

### C：逻辑提交后统一返回 200，不创建 Operation（已否决）

- 外部收敛只通过 Task blockers、日志和事件观察。

优点：接口较少。代价：调用方无法可靠等待、查询、重试或区分尚未完成与无法确认的外部工作。

## 第 212 题：外部收敛为 outcome_unknown 时能否继续（已确认 A）

### A：不相交工作继续，按 ResidualRiskSet 精确阻塞（已确认）

- `outcome_unknown` 不把整个 successor Attempt或 Project冻结。preflight 将新 intent 与 D126 ResidualRiskSet 求交，只阻塞可能冲突的 write、exclusive 和 external-side-effect 动作。
- 不相交的执行与只读分析可继续；解除 blocker 需要新的 reconcile evidence 或对当前 risk digest 的精确风险接受。

### B：整个 successor Attempt保持 blocked（已否决）

- 任一未知 Operation 都阻塞全部工作，直到被明确标记 succeeded/failed。

### C：允许全部工作继续，最终提交前再处理（已否决）

- 不在执行阶段阻塞，风险延迟到任务提交时统一处置。

## 第 213 题：长期无法核对时的风险接受期限（已确认 B）

### B：主 Agent可持续延长到任务完成（已确认）

- current main 可对仍有效的 risk digest 持续延长接受，直到关联任务完成；每次延长记录 actor、reason、scope、evidence 与 audit，不要求用户逐次确认。
- risk input digest、workspace、repository baseline、未知 Operation集合或 Attempt发生变化时，旧接受失效并重新评估，不能把“持续延长”实现成不绑定输入的永久豁免。

## 第 214 题：长期风险接受的限制（已确认 B）

### B：项目范围内不设置额外时间或范围上限（已确认）

- 在用户已经设置的 project/user ceilings、禁止动作和协调根边界内，current main 可覆盖整个项目的相关风险并持续到任务完成；系统不再增加累计时长、次数或二次用户批准门槛。
- 该自治不能扩张用户 ceiling，也不能绕过 D140 的重大项目方向/目标变更确认。风险接受改变的是已知残余风险的执行许可，不是新的 root、capability 或项目目标授权。

## 后续待细化

- succession/retirement/reactivation 的完整命令 DTO、事件和错误码。
