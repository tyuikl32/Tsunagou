# 首发 Capability 注册表设计

> 核对日期：2026-09-17。
> 状态：第 179 题已确认选项 A；作为 D103 的 Capability 颗粒度基线。

## 设计目标

[NIST 对最小权限的定义](https://csrc.nist.gov/glossary/term/least_privilege)要求实体只获得完成职能所需的最少资源和授权。[Kubernetes RBAC](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)将动作规则与资源范围分开表达，并明确其权限规则是 additive。Tsunagou 不照搬 Kubernetes，但采用“稳定动作 ID + 独立资源 scope”的简单结构；deny 和 ceiling 仍由既有 system/user/project 层处理。

Capability 只回答“允许尝试哪类动作”，不能独立完成授权。服务端还必须验证 principal、project、authority epoch、TaskAttempt owner、grant kind、scope、policy、blocker 和 expected revision。

## 第 179 题：Capability 采用什么颗粒度

### A（已确认）：固定的领域动作 Capability，无通配符

- 使用代码注册的稳定字符串，如 `task.claim`、`task.execute`、`agent.enroll`、`contract.accept`；capability 与 root/task/resource selector 分开。
- 一个 capability 覆盖语义一致的一组 command，不与具体 HTTP method/path 绑定；REST/MCP 都映射到同一内部 action ID。
- 首发不支持 `*`、前缀匹配、自定义 capability、策略脚本或运行时注册。
- role/template 只是签发时展开一组 capability IDs；grant 保存展开后的集合和 template version/digest，运行时不查 role 名放行。
- 未知 capability 在 schema/attach 时拒绝，不能静默忽略或解释成更宽权限。

优点：边界明确，能区分主 Agent、owner、reviewer 和普通读取，同时不引入策略语言。代价：需要维护 action-to-capability 矩阵及版本兼容。

### B（已否决）：每个模块只设 `read|write|manage` 三档

- 例如 `tasks.read`、`tasks.write`、`tasks.manage`，模块内所有写命令共享一项权限。

优点：capability 数量少。代价：`tasks.write` 很难同时容纳 claim、自身 execute、review 和 cancel-other；容易为了某个动作给出过宽权限，无法稳妥保证子 Agent边界。

### C（已否决）：直接把 HTTP/MCP 方法名作为 Capability

- 每个 endpoint/tool 自动对应权限字符串，例如 `POST:/tasks/{id}/claim` 或 `task_submit`。

优点：实现映射直观。代价：REST 与 MCP 名称漂移，重构 API 会变成授权迁移；同一业务动作出现两套权限，领域层难复用。

## 选择 A 时的首版候选集合

最终名称还需逐 command 核验，先按以下动作族控制规模：

| 领域 | 候选 capability | 额外硬条件示例 |
|---|---|---|
| Project | `project.read`, `project.configure`, `project.reconcile` | configure 覆盖策略允许的完成提议/重激活，仍受 user ceiling、current-main和lifecycle限制；完成确认user-only |
| Authority | `authority.handoff` | actor 必须是 current main；appoint/revoke 为 user-only，不可授予 |
| Agents | `agent.enroll`, `agent.manage` | 共享摘要由 project.read 覆盖；enroll 不能超过 issuer ceiling；普通 worker 不持有 manage |
| Tasks | `task.create`, `task.publish`, `task.claim`, `task.execute`, `task.review`, `task.coordinate` | 共享查询由 project.read 覆盖；execute 必须是 current attempt owner；create/publish 首发只给 user/main |
| Messages | `message.read`, `message.send`, `message.respond` | 受 inbox/recipient/subject scope 限制 |
| Cognition | `cognition.report`, `discrepancy.coordinate`, `contract.propose`, `contract.accept` | accept 只能代表 authenticated self |
| Resources | `resource.intent`, `resource.lease` | lease holder 必须绑定 current attempt |
| Workspaces | `workspace.use`, `workspace.manage` | use 绑定 attempt；manage 仅协调者 |
| Git/Durability | `git.report`, `git.coordinate`, `checkpoint.report`, `reconcile.report` | Git 执行仍由 D83 的主 Agent宿主完成 |

`user/control` 的 user-only commands 由 principal kind + command policy 判断，不创建一个可下发的 `user.admin` capability。

为控制首发复杂度，不为每个Project lifecycle动作新增capability：current main的`project.configure`覆盖策略允许的`project.completion.propose`和`project.reactivate`，`task.coordinate`覆盖批量历史Task恢复；具体lifecycle、policy、revision、authority和结构不变量由固定CommandPolicy predicates校验。user确认项目完成仍是principal-only command，不能下发为Agent capability。

## 需要继续细化

- 每个 command 对应的单一 required capability 和额外 predicate；
- worker/main/attempt 模板的精确 capability 集；
- capability 新增、弃用与 protocol current/N-1 的协商规则；
- 只读 query 是否统一要求 domain read capability，还是由 inbox/task 可见性直接决定。

## 第 180 题：项目内只读可见性如何授权（已确认 A）

### A（已确认）：共享协调状态默认对项目成员可读，敏感类别例外

- 所有 active project Agent 的 `agent_base` 都包含 `project.read`，可读取非秘密的任务图、Task/Attempt 摘要与结果、认知报告、契约、资源意图/lease 摘要、Agent capability 摘要和项目事件。
- 不再为这些共享对象维护逐对象 read ACL，也不要求同时拥有 `task.read`、`agent.read` 等重复 capability；查询仍按 project/lineage 隔离。
- 明确例外：消息正文/收件箱只对发送时固化的 routing recipient 开放，主 Agent也不能任意读取他人 inbox；token/ticket/credential 永不作为业务对象读取；用户 ceiling、本机绝对路径、敏感配置和受限内容采样按专用 principal/policy 返回或脱敏。
- `open` task 可以返回足以判断是否 claim 的完整协调描述，但源码读取仍受 root scope；读取不赋予 claim/execute/review/write 权限。

优点：最符合本机协作和减少工作量的目标；Agent容易发现依赖与理解分歧，授权查询简单。代价：同项目 Agent之间没有任务内容保密，未来多用户/远程模式必须增加可见性层。

### B（已否决）：每个领域保留独立 read capability

- `task.read`、`agent.read`、`cognition.read`、`resource.read` 等分别签发；对象仍大体项目共享。

优点：可关闭整个领域的读取。代价：模板和 action matrix 增大，但并没有实现真正的对象隔离；首发收益有限。

### C（已否决）：按参与关系做对象级 read ACL

- user/main 可见全部；普通 Agent只看自己拥有/依赖/被路由的任务和对象，open task 仅显示精简摘要，claim 后再开放正文。

优点：最小披露。代价：每种对象都要定义参与关系、列表过滤、影响图和脱敏 DTO；容易妨碍 Agent主动发现分歧，首发实现量最大。

## 第 181 题：写权限如何分配到 Grant（已确认 A）

### A（已确认）：按生命周期分层 Grant

- `agent_base` 长期只给项目读取、自己的消息操作和 `task.claim` 等低风险共同能力。
- `main_authority` 仅给 current main，承载 agent enrollment、task create/publish/coordinate、project configure/reconcile、authority handoff 等管理能力，并绑定 authority epoch。
- `task_attempt` 在 claim/preflight 为 owner 签发，承载 `task.execute`、cognition report、resource intent/lease、workspace use 和当前任务 root scope；Attempt 离开可执行状态即撤销。
- `task_review` 仅在 acceptance policy 指定 reviewer 时签发，绑定 task/attempt/review round；不能借此执行被审任务。
- 一个 action 必须命中指定 grant kind，不能把多个 grant 中互不相干的 capability/scope 拼成更宽授权。

优点：主 Agent、普通成员、执行 owner 和 reviewer 边界直接对应已有生命周期；撤销清晰。代价：同一 Agent可能同时有数行 grant，handler 要明确要求哪一种 kind。

### B（已否决）：把大多数 capability 放入长期 `agent_base`

- worker base 包含 task.execute/review/resource/workspace 等 capability，服务端依靠 owner/reviewer/attempt predicate 拒绝无关对象；仅主 Agent管理权单独成 grant。

优点：签发/撤销行较少。代价：capability 本身变得接近装饰，scope 难以绑定具体 attempt；遗漏任一 predicate 就会扩大权限。

### C（已否决）：每次状态变化重建一条 Session Grant

- 每个 HostSession 始终只有一条 active grant，claim、review、handoff 时重新计算全部 capability/scope，撤销旧行并生成新行。

优点：查询只命中一条 grant。代价：并行多个 task/review scope 难表示，频繁重签并容易因一次变化影响无关工作。
