# Project 状态、Conditions 与作用域 Blockers

> 核对日期：2026-09-17。
> 状态：第 167 题已确认选项 A；作为 D90 的 Project 状态与门禁基线。

## 问题

项目同时具有生命周期意图、当前活动副本、authority transition、shared-state divergence、数据库/迁移健康、root binding、Git durability 和外部 Operation 等状态。这些维度可以任意组合。单一枚举会快速膨胀，也迫使客户端从名字猜测哪些命令可用。

Kubernetes 的 [API conventions](https://github.com/kubernetes/community/blob/master/contributors/devel/sig-architecture/api-conventions.md)已经弃用新资源使用单一 `phase` 的模式，理由包括枚举难扩展和客户端推断隐含属性；其 Condition 结构用 observed generation、last transition time 和 machine reason 表达观察来源。Tsunagou 借鉴“生命周期与观察分离”，但采用项目自己的状态、snake_case 和 action-scoped blockers。

## 选项

| 选项 | 状态模型 | 优点 | 代价 |
|---|---|---|---|
| A（推荐） | 少量正交、权威状态字段 + versioned conditions + 可作用于 project/root/repo/task/action 的 blockers；命令根据当前事实计算可用性 | 可组合、可扩展；一个 root 故障不必冻结无关任务；API 能解释为什么某动作不可用 | 查询 DTO 和 projector 比单一 enum 更复杂；客户端需显示多个原因 |
| B | 使用一个覆盖所有组合的 project status enum，每种故障/过渡新增状态值 | 初始实现直观；switch 逻辑集中 | 状态组合爆炸；新增 enum 破坏旧客户端；难表达多个同时存在的阻塞原因 |
| C | 用一组独立 booleans（active、archived、diverged、migrating 等） | 写入最简单 | 容易产生互相矛盾组合；没有来源、时效、作用域和修复语义 |

## 选项 A：权威状态

只把真正由领域命令改变、具有不变量的少量值作为 aggregate state：

### Project lifecycle

- `active`：项目允许根据其他 gates 接受协作命令；D80 规定 init 成功后直接进入 active。
- `completed`：用户已确认项目整体目标完成；停止普通任务创建、自动调度和历史任务自动恢复，保留查询、审计、checkpoint、显式 follow-up 与 `ReactivateProject`。completed 不等于 archived。
- `archived`：完成归档 checkpoint 后的只读状态；只允许 inspect/export/reactivate/unregister 等明确动作。

`completing`、`archiving`、`reactivating`、migration、backup、lineage transition 等长流程是持久 Operation，不塞进 lifecycle enum。Operation 在执行期间创建相应 blocker，完成后原子改变 lifecycle 或其他权威状态。

普通 Task达到 `completed` 不改变 Project lifecycle。owner或current main提交 `ProjectCompletionProposal`，user/control确认后才将 project从 active转为completed。user始终可从completed显式重新激活；current main仅在完成前固定的项目策略授权且不扩大user ceiling时也可执行。重新激活创建新runtime epoch，不恢复旧Attempt、Lease、grant或workspace ownership。

### Authority

- `unassigned`：没有主 Agent；用户管理命令仍可用，需要主 Agent的风险评估/Git/root/调度动作阻塞。
- `stable`：一个 current main agent 与 authority epoch 生效。
- `transitioning`：D89 的 AuthorityTransition 正在冻结/adopt/收敛。

### Replica role

- `active_writer`：当前 daemon 对此 project/lineage 的唯一可写 replica。
- `standby`：已登记 clone，只允许诊断、比较和激活预检。
- `takeover_required`：上次 writer 不可正常切换，需要用户显式恢复性接管。

这些字段分别有 revision/epoch，不能从路径、进程存活或时间戳猜测。lineage 的 open/sealed、root binding status、TaskAttempt 和 Operation 状态属于各自 aggregate，不复制为第二权威字段。

## Conditions

`ProjectCondition` 是当前观察投影，每个 `(project_id, type, scope)` 至多一条 current value，变化仍产生不可变领域/审计事件：

- `type`：稳定 snake_case，例如 `database_ready`、`shared_state_consistent`、`schema_supported`、`required_bindings_ready`、`materialization_caught_up`、`git_local_coverage`、`publication_report_fresh`；
- `status`：`true`、`false`、`unknown`，不能用 absent 代替 unknown；
- `reason_code`：稳定 machine enum；`message` 仅供人类，不能作为控制输入；
- `severity`：`info`、`warning`、`error`；
- `scope`：project 或具体 root/repository/replica/lineage；
- `observed_project_revision`、相关 aggregate revision、runtime/authority epoch、input digest；
- `observed_at`、`last_transition_at`、producer、evidence refs；
- `stale_after` 可选；过期后状态变 unknown，不自动变 false；
- `remediation_code` 与 related Operation/resource refs。

Condition 是事实观察，不直接等同于权限。例如 `publication_report_fresh=false` 只在某个动作 policy 要求新鲜发布报告时才形成 blocker；普通本机任务仍可继续。

## Blockers

`ProjectBlocker` 是从权威状态、conditions、policy 和当前命令需求派生/持久化的可解释门禁：

- `blocker_id`、stable `code`、source type/ref、severity；
- `scope_kind/id`：project、lineage、replica、root、repository、task/attempt 或 operation；
- `affected_actions`/capability selector：例如所有 domain writes、task claim/start、某 root write、Git integration、archive、replica switch；
- observed revisions/epochs 与 policy digest，防止陈旧 blocker 错误复用；
- `since`、`retryable`、`retry_after`、remediation code/required actor；
- related condition/evidence/operation，及解除它的确定性 predicate。

典型 blocker：

- `project_archived`：阻止普通写，允许 reactivate/inspect；
- `project_completed`：阻止普通 task create/publish、自动调度和批量隐式恢复，允许 inspect/audit、completion evidence、显式 follow-up和项目重激活；
- `replica_not_active_writer`：阻止当前 replica 的业务写；
- `shared_state_diverged`、`future_shared_format`、`migration_failed`、`checkpoint_corrupt`：通常阻止全项目 domain writes；
- `authority_transition`：阻止新 claim/授权/Git/root action，但允许 D89 安全收敛；
- `main_agent_required`：只阻止需要主 Agent的动作；
- `required_root_unbound`、`root_identity_changed`：只阻止引用该 root 的任务/lease；
- `repository_reconcile_required`：阻止受影响 repositories 的集成，允许无关任务；
- `outbox_backlog_hard_limit`：在持久性无法保证时阻止新增写，普通 backlog 只降级告警。

同一 source/reason 的 blocker 更新 current projection，不重复制造无限 blockers；每次出现、scope/严重性改变和解除均有事件。多个 blockers 同时返回，客户端不必一次修一个才看到下一个。

## Derived Summary

为了 CLI/UI 扫描，可以提供非权威摘要：

- `operability`: `writable`、`degraded`、`read_only`、`recovery_required`；
- `health`: `healthy`、`warning`、`error`、`unknown`；
- `active_blocker_count` 与最高 severity；
- local Git coverage/publication report、authority 和 replica 的独立摘要。

摘要必须标注 `derived_from_revision`/`computed_at`，服务端和客户端不能据此替代具体 command preflight。`degraded` 项目可能允许大多数动作，`writable` 也不表示调用者拥有权限。

## Command Evaluation

每个 command handler 在同一 Unit of Work 中：

1. 验证身份、capability、expected revision/epoch 和 idempotency。
2. 读取 action policy 所需的 lifecycle/authority/replica/conditions 与 scoped blockers。
3. 对陈旧 external conditions 选择同步刷新、创建 preflight Operation 或返回 `condition_stale`，不假设旧 true 仍有效。
4. 收集所有适用 blockers，按确定性优先级返回；不满足则不做部分 mutation。
5. 通过后提交聚合、事件、outbox/job；同一事务更新可确定的 conditions/blockers projection。

被阻止的 HTTP mutation 使用 RFC 9457 和适当 409/423/503 语义，扩展 `code`、`blockers`、current revisions 与 remediation；MCP 返回相同 machine details。不能用一个 `project_not_active` 覆盖真正原因。

## Condition Producers

- 领域事务内可知的事实（lifecycle、authority、replica、binding revision）同步投影。
- 文件/Git/adapter/外部进程等观察由持久 reconcile job 产生，记录 input snapshot 和 producer version。
- daemon 重启后先恢复权威 state，再把无法确认的外部 condition 设为 unknown/待刷新；不从旧时间戳推断健康。
- producer 不得直接改变其他模块 aggregate；它更新 condition/evidence，所属模块的 policy projector 派生 blockers。
- condition type/reason code 属于协议 schema；新增 optional condition type可兼容，旧客户端必须忽略未知 type，不能映射为 healthy。

## API 形状

`GET /api/v1/projects/{project_id}` 返回 lifecycle、authority、replica、revision/epochs、derived summary 和少量关键 conditions；完整列表分别通过 conditions/blockers endpoints 分页获取。

建议端点：

- `GET .../conditions`、`GET .../blockers`；
- `POST .../actions/archive`、`reactivate`、`activate_replica`、`takeover`，长流程返回 Operation；
- `POST .../actions/reconcile` 只接受受控 scope/kind，不暴露任意 reconciler 名称；
- `GET .../actions/{kind}/preflight` 或对应 typed preflight command，返回 requirement/blocker snapshot，但不授予执行权。

SSE 只提示 project revision/condition topics 高水位；权威 condition/blocker 内容仍经 REST 拉取。

## 后续待细化

- lifecycle/authority/replica aggregate 的字段、事件和精确转换表。
- Condition/Blocker schema、type/reason registry 与 action-to-blocker matrix。
- blocker HTTP status 选择、preflight DTO 与 CLI/Rich 展示规范。
- condition stale policy、reconcile job 优先级和故障注入用例。
