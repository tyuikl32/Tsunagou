# 主 Agent 向子 Agent 委派任务的模型

> 核对日期：2026-09-17。
> 状态：第 170 题已确认选项 A；作为 D94 的父子任务式委派基线。

## 已确认方案 A

- 主 Agent继续拥有父 TaskAttempt，拆出的每项可验收工作创建带 `parent_task_id` 的独立子 Task。
- 子 Agent只领取和执行子任务；其输出成为父任务的结构化依赖/证据，不能直接提交、完成或改变父任务 owner。
- 父任务由主 Agent汇总，并自行选择采用或忽略哪些子结果。若主 Agent失联，仍需先关闭旧 attempt，再按恢复流程创建新 attempt。
- 小型咨询可使用 request/response Message；需要工作区写入、Lease、独立产物或验收时必须创建子任务。
- 首发不实现同任务 contributor ACL，也不因创建子任务而强制暂停父任务。

## 已确定的硬边界

- 请求主体由 session token 映射，客户端不能自报成主 Agent或其他 task owner。
- 一个 TaskAttempt 始终只有一个不可变 `owner_agent_id`。
- 运行中的 attempt 不提供原地换 owner；恢复或转交必须关闭旧 attempt 并创建新 attempt。
- 主 Agent角色与任务 owner 是两条独立关系。主 Agent可以协调其他任务，但不能借管理角色代替 owner 写入其 attempt 结果；子 Agent同样不能代替主 Agent执行父 attempt。

## 方案记录

### A（已确认）：父任务保留主 Agent，委派工作创建子任务

- 主 Agent继续拥有父 TaskAttempt，拆出的每项工作创建带 `parent_task_id` 的独立子 Task。
- 子 Agent只领取和执行子任务；其输出成为父任务的结构化依赖/证据，不能直接完成父任务。
- 父任务可在主动等待某些子任务时进入 `blocked`，或在主 Agent仍有独立工作时继续 `running`；子任务状态不构成提交门禁。
- 父任务由主 Agent汇总、选择采用的结果并完成。若主 Agent失联，走关闭旧 attempt 后新建 attempt 的恢复流程。

优点：完全复用单 owner、attempt、依赖图、验收和权限机制，审计最清晰；最符合“不接管主任务”。代价：细小委派也产生 Task/Attempt 记录，需要 CLI/MCP 提供快速创建子任务的组合命令。

### B（已否决）：同一任务增加受限 Contributor

- 主 Agent仍是唯一 owner；为子 Agent创建 task-scoped contributor grant，可附加消息、证据或 artifact，但不能 start/submit/complete/cancel/改变 owner。
- contributor 的每类写入都需要新增 action、数据归属、并发与撤销规则。

优点：很小的咨询或局部工作不必创建子任务。代价：引入第二套参与语义和共享工作面，权限矩阵、冲突处理及审计更复杂；工期风险最高。

### C（已否决）：主 Agent先拆分并暂停自身 attempt，子任务全部完成后再恢复

- 委派时父 attempt 离开 running 并释放资源；所有委派均成为子任务。
- 子任务达到要求后，主 Agent重新 preflight 并恢复父任务。

优点：父子不会同时写入，资源边界最保守。代价：协调期间主 Agent不能并行推进自身部分；频繁重新 preflight，效率较低。

## 后续待细化

- 子任务取消、失败、返工和父任务终态时的传播；
- 父 TaskResult 中采用/忽略子结果的通用 evidence refs；
- 快速委派的 REST/MCP 组合命令与幂等边界。

## 第 171 题：子任务执行期间父任务的状态（已确认 A）

[Temporal Child Workflows](https://docs.temporal.io/develop/python/child-workflows)区分启动子工作、持有 handle 和等待子工作完成；[GitHub Actions `needs`](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idneeds)则把依赖成功作为后续工作运行的门槛。二者共同说明：父级是否继续活动与子级是否成为完成前置条件是两个维度，不应由“创建子任务”这个动作隐式混合。

### A（已确认）：不增加状态，父 owner 显式决定继续或阻塞

- 创建子任务不自动改变父 Task/Attempt 状态。
- 主 Agent仍有汇总、设计或协调工作时，父 attempt 保持 `running`；它只能持有自身仍需的 leases，不能借父任务占用已委派给子任务的资源。
- 主 Agent当前选择等待某些子任务时，显式调用 `block(reason=waiting_on_children, child_task_ids=[...])`，父任务进入现有 `blocked` 并释放 leases。
- 被观察的子任务状态变化只生成通知，不自动判断等待条件是否满足；父 owner 自行决定何时显式 resume 并重新 preflight。
- 第 172 题后续选择 C，覆盖本方案原先关于 required child 阻止 submit 的候选描述；子任务不构成父任务系统门禁。

优点：不扩充状态机；保留主 Agent并行协调能力；沿用 D36 的显式 block/resume 与资源释放语义。代价：主 Agent需要明确表示自己是否仍在工作。

### B（已否决）：增加 `waiting_children` 状态

- 只要父任务暂时等待 required children，就进入专门状态；保留 owner、释放 leases，子任务满足后转为可恢复。
- 与外部 blocker 的 `blocked` 分开统计和展示。

优点：界面与指标直观。代价：增加整个状态机、API、事件、过滤、恢复和迁移分支；其执行语义与 typed `blocked` 高度重复。

### C（已否决）：创建 required child 时自动阻塞，完成时自动恢复

- 首个 required child 发布后，系统自动把父任务置为 blocked；全部成功后自动回到 claimed/running。

优点：调用步骤少。代价：阻止父子并行；自动恢复可能在 owner 离线、资源或契约已经变化时误启动；与显式 preflight 原则冲突。

## 第 172 题：子任务如何成为父任务的完成条件（已确认 C）

这里需要区分“子任务是否必须成功”和“父任务具体使用了哪一版子结果”。只看 `parent_task_id` 会导致所有探索性子任务都阻塞父任务；只看自然语言又无法稳定验证父任务是否遗漏了必要工作。

### A（已否决）：显式 required/optional 关系并绑定结果

- 每条父子关系带不可变 `contribution_mode=required|optional`，在子任务发布为 open 后不得原地改变；需要改变时 supersede 该关系并记录理由。
- required child 必须达到 `completed`，且父 TaskAttempt 必须绑定其不可变 `TaskResultRef(task_id, attempt_id, result_id, digest)`，父任务才允许 submit。
- optional child 永不阻塞父任务；若父 owner 使用其产物，也必须绑定精确 ResultRef，使审计能重建使用版本。
- 子任务自身的 acceptance policy 决定何时进入 completed。父 owner只有在被列为该子任务 reviewer 时才负责验收，不再增加一层模糊的“父级接受”。
- 父任务 preflight/submit 检查 required 关系当前 revision、子任务终态和 ResultRef digest；子任务后续 follow-up 不静默替换已经绑定的结果。

优点：必要工作有机器门禁，探索/建议不拖住父任务，并复用既有任务验收。代价：父 attempt 需要显式 bind-result 动作。

### B（已否决）：所有子任务都必须 completed

- 任一直接子任务未 completed，父任务都不能 submit；完成后自动使用最新结果。

优点：字段和规则最少。代价：探索性、备用或后来放弃的子任务会阻塞父任务；“最新结果”不具备稳定重放性。

### C（已确认）：所有子任务都不自动构成门禁

- `parent_task_id` 只表达委派来源、导航和审计关系，不附带 `required|optional` 字段。
- 父 owner 自行判断哪些子工作足以支撑父结果；系统不因子任务未完成、失败或取消而阻止父任务 submit。
- 不增加独立 `bind-result` 命令。父 TaskResult 使用通用 evidence/result refs 引用实际采用的精确 child task/attempt/result/digest；未使用的子结果无需绑定。
- 提交可以附带未完成、失败或被忽略子任务的简短说明，供既有 automated/reviewer/self 验收策略判断；该说明不是新的状态门禁。
- 子任务后续产生的新 attempt/result 不会改写父结果已经记录的引用；需要采用新结果时通过父任务返工或 follow-up 产生新结果记录。

优点：最灵活。代价：必要子任务失败或仍在运行时父任务也能提交，削弱任务图和验收的可信度。

## 第 173 题：父任务终止时如何处理未结束的子任务（已确认 B）

[Temporal 的 Parent Close Policy](https://docs.temporal.io/develop/python/child-workflows#parent-close-policy)明确把父工作关闭后的子工作行为作为独立生命周期问题，并提供 terminate/request-cancel/abandon 等策略。Tsunagou 首发可以固定一种行为，避免引入每条关系的策略字段。

### A（已否决）：父任务终态后递归请求取消未结束子任务

- 父任务进入 `completed|failed|cancelled` 的同一事务，为所有非终态 descendants 创建幂等 `cancel_requested` 命令/通知；父任务本身无需等待子任务收敛即可提交终态。
- 子任务沿用 D36 两阶段取消：owner 停止并提交证据后 cancelled；失联或外部进程未停进入既有 orphaned/residual-risk 处理。
- 已 completed/failed/cancelled 的子任务历史不改写。子任务失败或取消只通知父 owner，不反向自动终止父任务。

优点：不会在父任务结束后继续无目标工作，也不增加 per-link policy。代价：父任务提前完成会取消仍可能有价值的探索；若要保留，首发需先把它创建为独立根任务，而非子任务。

### B（已确认）：父任务终态不影响子任务

- 所有既有子孙任务继续原状态，保留各自 owner、attempt、grants 和 leases，直到自身完成或被合法主体显式取消。
- 子任务仍保留原 `parent_task_id`，不自动 detach 或改成根任务。父任务终态事件通知仍活跃的 descendant owners 和当前主 Agent。
- 晚到结果进入任务树和项目时间线，但不能重开、补写或改写已经终态的父任务；需要使用时创建 follow-up 任务并引用精确结果。
- 父任务终态后禁止再创建新的直接子任务。子任务失败/取消也只产生通知，不反向改变父任务历史终态。

优点：没有级联副作用。代价：容易产生父任务已经结束但仍占资源、继续写入的陈旧工作，需要人工清理。

### C（已否决）：父任务终态前逐个选择 cancel 或 detach

- 只要有非终态子任务，父任务不能进入终态；owner 必须逐个请求取消或把子任务 detach 为独立任务。

优点：每项工作去向明确。代价：重新引入完成门禁和 detach/reparent 状态机，首发实现量最大。

## 第 174 题：谁可以创建和发布子任务（已确认 A）

子任务已经拥有独立 owner 和 attempt，因此“允许普通 task owner 继续向下委派”会形成递归任务树，也会要求权限、预算和 root scope 沿层级收窄。工期受限时，可以把创建权集中在主 Agent，同时让普通 Agent通过消息请求拆分。

### A（已确认）：仅用户和当前主 Agent创建/发布子任务

- 普通 Agent不能直接调用 create-child；需要拆分时发送类型化 `DelegationRequest` 给当前主 Agent，包含 parent task、目标、建议 scope、原因和预期产物。
- 主 Agent决定是否创建子任务，并在用户/project ceilings 内设置任务 scope、能力、资源和验收策略。
- 任务树可以多层，但每一层的新任务都由当前主 Agent创建；普通 Agent不会获得可转授 capability。
- `DelegationRequest` 复用 D73 Message/ResponseObligation；主 Agent以 child task ref 或结构化拒绝响应，不新增 delegation approval 表。
- child scope 必须落在 parent task 的有效 scope 内；若确需扩大，先修改父任务并重做相应授权/preflight，禁止以创建子任务绕过父范围。
- 当前主 Agent离线时用户仍可创建；否则请求保持 pending，普通 Agent不能因超时自行创建。

优点：授权规则最少，符合“主 Agent控制调度”，避免普通 Agent递归扩散任务和权限。代价：主 Agent成为拆分吞吐瓶颈，离线时普通 Agent只能等待或继续原任务。

### B（已否决）：任何 task owner 在 `task.delegate` grant 内可直接创建并发布子任务

- 子任务 scope/capabilities/budget 必须是父 attempt grant 的子集；支持多层递归委派。
- 每层 owner 对自己的子任务负责，主 Agent只观察或干预异常。

优点：Agent-to-Agent 自治最强，主 Agent负担小。代价：需要可靠的可转授授权、深度/数量/预算限制和递归回收，首发边界更复杂。

### C（已否决）：普通 owner 可创建 draft，当前主 Agent审核后发布

- owner 物化子任务草稿，但草稿无 owner、grant、workspace 或 lease；主 Agent批准后才进入 ready/open。

优点：保留结构化提案和主 Agent控制。代价：增加 draft 审批队列、修改权和并发规则；相比消息请求节省有限。

## 第 175 题：主 Agent创建子任务时的发布步骤（已确认 A）

现有 Task 状态包含 `draft`、`ready` 和 `open`。首发需要决定 `create child` 是直接完成创建与发布，还是要求主 Agent分两次命令推进。

### A（已确认）：原子 create-and-open，另保留可选 draft 命令

- 常用 `DelegateChildTask` 在一个 UoW 校验 parent 非终态、expected revisions、scope、policy、验收配置和幂等键，然后创建 child 并直接进入 `open`；同事务写事件、inbox 和 outbox。
- 任一校验失败不留下半成品 child。child 进入 open 后仍由 D33 的所有合格 Agent原子 claim，不做定向 offer 或自动 owner 分配。
- 对确实需要稍后补充内容的场景，通用 `CreateTaskDraft` 仍可创建 draft，之后由用户/主 Agent显式 publish；普通 DelegationRequest 默认不走该慢路径。
- 成功时 child 没有 owner/attempt/workspace/lease；这些都在后续 claim/preflight 创建。`TaskCreated` 直接记录 initial status `open`，不制造没有实际意义的 draft/ready 过渡事件。
- 命令输入至少包含 command/idempotency key、parent task 和 expected revision、child objective/scope/constraints、priority、acceptance policy，以及可选 DelegationRequest message ID；actor、project 和 authority epoch 由认证上下文与服务端状态取得。

优点：常用委派只有一次命令，同时保留复杂任务的草稿能力；不改变既有状态机。代价：需要一个组合 command handler，但其内部仍复用创建和发布规则。

### B（已否决）：所有子任务必须 draft -> ready -> open 三步推进

- 主 Agent先创建 draft，补齐字段后标 ready，再单独 publish 为 open。

优点：每一步都可查看和修改。代价：本地无 Web 工作台的首发中交互冗长，容易留下大量未发布草稿。

### C（已否决）：创建时固定为 ready，再单独 publish

- 子任务创建即要求字段完整，但仍需第二条命令进入 open；不允许 child draft。

优点：比 B 少一个阶段，发布动作明确。代价：每次委派仍需两个往返，且无法解释为何字段已完整却不能直接开放领取。

## 第 176 题：一个 DelegationRequest 可以如何被主 Agent落实（已确认 A）

普通 Agent提交的是拆分建议，而当前主 Agent负责全局任务图。如果请求边界过大、与现有任务重复或需要多个互不冲突的工作包，强制一对一会让主 Agent先拒绝再重新沟通。

### A（已确认）：允许主 Agent重构为零到多个子任务

- `DelegationRequest` 的建议目标/scope 不直接成为命令；主 Agent可收窄、拆成多个 child、合并到现有 task，或拒绝，但不能借此扩大 parent scope。
- 一个响应使用 `resolution=created|linked_existing|rejected`，携带零到多个 task refs、每项与请求的 mapping/rationale，以及未采纳部分说明。
- 创建多个 child 时使用一个 parent `DelegateOperation`/command envelope：数据库内的 task/events/message response 同一 UoW；后续 workspace 等外部准备仍分别进行。
- request obligation 在该结构化 resolution 持久化后满足，不要求请求者再次接受；请求者可另发澄清/新请求。
- 全部新 task、task events、resolution、inbox/outbox 和原 request obligation satisfaction 在同一 UoW 原子提交；相同 idempotency key/request hash 只返回原 task refs。

优点：主 Agent能做真正的任务分解，减少往返；仍只增加一个 response schema。代价：响应不是简单 child_task_id，需要 task refs 数组和 mapping。

### B（已否决）：严格一请求一子任务，只能原样接受或拒绝

- 主 Agent不能修改目标/scope，也不能一次拆多个；任何调整都拒绝并要求 requester 重发。

优点：协议最简单。代价：把任务分解责任推回普通 Agent，增加消息轮次，并与主 Agent集中调度的选择冲突。

### C（已否决）：主 Agent可提出重构，但请求者必须接受后才创建

- 主 Agent返回 proposal，普通 Agent接受后再运行 DelegateChildTask。

优点：请求者确认语义。代价：重新引入 proposal/accept 状态、超时和竞态，与主 Agent拥有最终调度权及紧工期不符。
