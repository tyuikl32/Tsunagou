# 命令授权矩阵

> 核对日期：2026-09-17。
> 状态：第 182 题已确认选项 A；作为 D106 的命令授权基线。

## 问题

固定 capability 只是名称表。实现仍需规定每条 command 如何组合 principal、grant kind、capability、领域关系和 blocker。如果直接在 handler 内自由编写条件，首发代码少，但容易出现 REST 与 MCP 路径不一致；如果引入通用策略表达式，又超出本机首发需要。

## 第 182 题：Command 如何声明授权要求

### A（已确认）：静态 CommandPolicy 注册表，一项主 Capability 加固定 predicates

每个内部 command kind 在代码中注册一条静态 policy：

```text
CommandPolicy
  command_kind
  allowed_principal_kinds
  required_capability nullable
  required_grant_kind nullable
  predicates[]
  blocker_action
```

- Agent command 恰好要求一个主 capability 和一个 grant kind；同时执行全部代码注册的 predicates，例如 current-main、attempt-owner、reviewer-round、recipient、scope、epoch/revision。
- user-only command 使用 `allowed_principal_kinds={user_control}`，capability/grant 为空；它不能被某个 Agent capability 模拟。
- REST、MCP、CLI 最终都构造同一 command kind，再调用同一 authorize-and-handle path。
- 首发不支持 `any_of`、嵌套布尔表达式、运行时 policy 文件或 handler 临时跳过授权。复杂差异拆成不同 command kind。

优点：矩阵可完整审查和测试，表达力足够覆盖当前边界，远小于策略引擎。代价：新增 command 必须同步注册 policy，否则启动/CI 失败。

### B（已否决）：每个 handler 手写授权判断

- capability、owner、epoch、scope 检查由 handler 自由组合，不维护中央注册表。

优点：起步代码最少。代价：很难证明所有入口一致，REST/MCP 或新 handler 容易漏掉某项检查；无法自动生成权限矩阵测试。

### C（已否决）：引入通用声明式策略表达式

- policy 支持 all/any/not、属性引用、条件和外部配置，运行时解释。

优点：最灵活。代价：需要策略 schema、解释器、调试、迁移和安全审查，明显超出首发范围。

## 选择 A 时的代表性矩阵

| Command kind | Principal | Grant kind | Capability | 必须同时满足 |
|---|---|---|---|---|
| `task.claim` | agent_session | agent_base | task.claim | task open、eligible、未被并发领取 |
| `task.start/update/submit` | agent_session | task_attempt | task.execute | current owner/attempt/execution epoch、scope、状态 |
| `task.review.accept/request_changes` | agent_session | task_review | task.review | current reviewer、review round、submitted task |
| `task.create/delegate/publish` | agent_session | main_authority | task.create/task.publish | current main/authority epoch、parent 非终态、scope |
| `agent.enrollment_ticket.create` | agent_session | main_authority | agent.enroll | current main、ceiling、ticket kind policy |
| `authority.handoff` | agent_session | main_authority | authority.handoff | current main、expected authority epoch |
| `message.send/respond` | agent_session | agent_base | message.send/message.respond | sender identity、recipient/response contract、subject scope |
| `contract.accept` | agent_session | agent_base | contract.accept | authenticated self 是 required participant、精确 digest |
| `project.configure/reconcile` | agent_session | main_authority | project.configure/project.reconcile | current main、ceiling、blocker scope |
| `project.completion.propose.owner` | agent_session | task_attempt | task.execute | current root/objective task owner、current attempt、精确 project/objective revision |
| `project.completion.propose.main` | agent_session | main_authority | project.configure | current main、authority epoch、精确 project/objective revision |
| `project.completion.confirm` | user_control | none | none | user-only、proposal digest、expected project revision |
| `project.reactivate.main` | agent_session | main_authority | project.configure | current main、policy允许、completed、ceiling不扩大、expected runtime/project revision |
| `project.tasks.restore_open` | agent_session | main_authority | task.coordinate | current main、active新runtime、plan digest、全部task revisions、结构不变量 |
| `authority.appoint/revoke`, `ceiling.set` | user_control | none | none | user-only、expected revision/epoch |

具体命令若需要不同 capability，应拆成独立 policy 行；不得把表中斜杠写法直接实现为模糊的多动作 endpoint。

user/control 对 `project.reactivate` 和 `project.tasks.restore_open` 使用独立 user command kind，principal-only授权，不要求伪造main grant。恢复任务时CommandPolicy不判断旧依赖是否仍有业务价值；handler只验证身份、revision、非completed、未被替换、无current owner/Attempt和batch原子性。动态依赖、scope、契约、资源、workspace与风险在claim/preflight重新计算。

## 后续待细化

- 全量 command inventory 与 capability/grant/predicate/blocker 映射；
- policy registry 的启动完整性检查和测试生成；
- query authorization 与字段脱敏矩阵；
- RFC 9457 错误码中 authentication、capability、relationship、scope、blocker 和 revision 的区分。
