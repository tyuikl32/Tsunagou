# 项目完成、重新激活与历史任务恢复协议

> 核对日期：2026-09-18。
> 状态：第 228–236 题已确认；对应 D152–D160。
> 目的：区分普通任务完成、项目整体完成、项目归档和后续重新激活，并把业务判断交给主 Agent，把机械内核限制在必要的数据一致性不变量。

## 决策映射

| 题号 | 决策 | 选择 | 决策号 |
|---|---|---|---|
| 228 | 普通任务由协作角色完成，用户只确认项目整体完成 | C | D152 |
| 229 | owner/current main 提议项目完成，用户确认 | A | D153 |
| 230 | 确认后进入可恢复的 `completed` | A | D154 |
| 231 | user 始终可重激活，current main 按策略也可 | A+B | D155 |
| 232 | 重激活后只恢复显式选择的历史任务 | A | D156 |
| 233 | current main 可批量选择恢复任务 | A | D157 |
| 234 | 批量事务直接把选中任务置为 `open` | B | D158 |
| 235 | 旧依赖与业务适用性由主 Agent判断，内核只守结构不变量 | C+D 混合 | D159 |
| 236 | 完成确认前由主 Agent收敛执行面，内核只验证静止 | 是 | D160 |

## 四种不同语义

### 普通 Task 完成

- Task的`completed`由既有 acceptance policy决定：owner自验、指定reviewer、自动化验收或允许的current main验收。
- 普通Task完成不创建UserDecision，不改变Project lifecycle，也不要求用户逐项确认。
- `completed` Task仍不可重开；后续工作创建显式follow-up Task并引用原结果。

### 项目整体完成

- owner或current main可提交`ProjectCompletionProposal`，说明项目目标为何已经满足。
- 只有user/control对当前proposal revision执行`ConfirmProjectCompletion`后，Project lifecycle才从`active`转为`completed`。
- 完成是业务结论，不由“所有Task均completed”、最后一个review通过、checkpoint成功或Operation成功自动推导。

### Project completed

- `completed`停止普通Task创建/发布、自动调度、自动claim提示和历史任务隐式恢复。
- 允许查询、审计、导出、checkpoint、完成证据补充、显式follow-up提案和`ReactivateProject`。
- `completed`不是只读归档，也不封存lineage；它保留后续继续同一逻辑项目的可能性。

### Project archived

- `archived`仍沿用D59/D90：完成归档checkpoint、撤销运行凭据和租约、关闭本机运行时，只保留明确的inspect/export/reactivate/unregister能力。
- completed项目可稍后archive；二者不能合并成同一个状态或一个布尔值。

## ProjectCompletionProposal

```text
ProjectCompletionProposal
  proposal_id, project_id, lineage_id
  project_revision, proposal_revision
  proposed_by_principal, proposed_by_agent_id?
  authority_epoch?
  objective_revision, acceptance_policy_revision
  completion_summary
  objective_results[]
  key_task_result_refs[]
  contract_refs[], checkpoint_ref?
  verification_evidence_refs[]
  unresolved_items[]
  residual_risk_refs[]
  known_exceptions[]
  recommended_disposition
  content_digest
  status pending | confirmed | rejected | withdrawn | superseded
  created_at, resolved_at?
```

- owner在此处指项目目标/根任务的合法owner；普通子任务owner不能仅凭自己的子任务完成提议整个项目完成。
- proposal是不可变证据包；补充目标、风险、例外或关键证据时创建新revision并supersede旧版本。
- user确认绑定`proposal_id + proposal_revision + content_digest + expected_project_revision`，不能确认旧摘要后执行新内容。
- unresolved items和residual risks可以存在。user确认表示接受证据包中公开的例外，不把对应Task/Operation伪装成成功。

## 完成转换

### 完成前执行静止

- `ProjectCompletionProposal`可以在项目仍有活动工作时创建和补充，但user确认前，current main或user/control必须先处理全部current执行责任。
- 主 Agent按业务语义决定每个未完成Task应正常验收为completed、明确failed/cancelled，还是关闭旧Attempt并保留为未来可重开的非终态Task；系统不替它选择。
- 所有非终态current TaskAttempt必须显式关闭，所有执行Lease和`task_attempt` grants必须释放/撤销。没有可信外部停止证据时可关闭逻辑执行权并保留ResidualRiskSet/outcome_unknown，但必须写入completion evidence。
- 静止不要求所有Task都completed，也不要求所有Operation都succeeded；它只要求没有主体仍持有合法的项目执行权。
- user确认期间revision发生变化或出现新current Attempt/Lease/grant时，确认返回冲突，主 Agent重新收敛并更新proposal。

`ConfirmProjectCompletion`在一个Project UoW中：

1. 验证user/control身份、proposal digest与expected revisions；
2. 确认Project仍为active writer、lineage未变化、没有更晚的project objective revision；
3. 机械验证不存在非终态current Attempt、活动执行Lease和active/frozen可恢复的task execution grant；
4. 将proposal置为confirmed并写不可变user decision evidence；
5. 将Project lifecycle改为`completed`并递增project revision；
6. 创建`project_completed` action blocker、事件、outbox和completion checkpoint job；
7. 保留所有Task、Attempt、Contract、Operation和风险的真实状态，不批量改写为completed/cancelled。

## ReactivateProject

### 可执行主体

- user/control始终可以从`completed`显式重新激活项目。
- current main仅在完成前已生效的project policy明确授予`project.reactivate`、当前authority仍可验证且操作不扩大user ceiling时可以执行。
- 若completed期间current main身份/HostSession失效，不能仅凭历史role自报恢复权限；由user重建authority或直接执行。

### 状态效果

`ReactivateProject`创建新的`runtime_epoch`，将Project从`completed`转回`active`，并写completion history ref、actor、reason、policy/ceiling digest、事件和outbox。

它不恢复：

- 旧HostSession、Connection、token或runtime credential；
- 旧TaskAttempt owner、execution epoch或task grant；
- Lease、workspace ownership、inbox delivery lease；
- 已完成Task、已接受Contract或已提交Operation的历史状态；
- completed前被supersede、cancel或retire的身份和责任。

需要运行的Agent按正常attach/resume/reactivate规则建立当前runtime有效会话。

## 批量恢复历史任务

### RestoreProjectTasksToOpen

项目重新激活后，user或current main可提交一个独立批量命令；ReactivateProject本身不隐式恢复任何Task。

```text
RestoreProjectTasksToOpen
  command_id, project_id
  expected_project_revision, runtime_epoch
  authority_epoch?
  selector explicit_task_ids | query_snapshot
  expanded_task_ids[]
  expected_task_revisions{}
  main_agent_assessment
  reason
  plan_digest
```

- query selector只能使用固定allowlist字段；服务端先展开为精确Task IDs、revisions和plan digest，再进入写事务。
- 同一UoW将全部合法选中Task直接置为`open`、清除当前owner投影并写`TaskReopenedAfterProjectReactivation`、审计和outbox；任一结构校验失败则全部不提交。
- 命令不创建TaskAttempt、Lease、workspace、ResourceIntent或grant。进入open后仍由所有合格Agent按D33竞争claim，并按D34执行完整preflight。
- 未选Task保持原状态。`completed` Task一律不能选择，后续工作必须创建follow-up。

### 主 Agent负责的业务判断

`main_agent_assessment`至少记录：

- 为什么旧目标仍需继续；
- 哪些旧依赖已不再相关或将由后续Agent处理；
- 预期scope、结果和优先级；
- 已知契约、资源、workspace和风险变化；
- 为什么选择这批Task而非创建follow-up。

核心保存并展示该判断，不自行构建第二套业务规则去验证依赖是否“合理”、资源是否“值得”、契约是否“业务上仍适用”，也不替主Agent重排任务优先级。

### 内核必须保留的结构校验

这些检查用于防止数据损坏和并发双owner，不属于业务决策：

- project/lineage/active replica/runtime epoch精确匹配；
- command、project和全部Task revisions仍等于plan snapshot；
- 每个Task属于当前Project/lineage，未被删除、合并或supersede；
- Task不是`completed`，也没有另一个已成为current的replacement/follow-up语义冲突；
- Task没有current owner或可执行/current TaskAttempt；若仍有Attempt，主Agent先通过相应close/cancel/succession命令收敛；
- 当前actor确为user或持有当前authority epoch下相应capability的main Agent；
- expanded IDs无重复，数量/载荷不超过稳定性上限；
- 同一batch全有或全无提交。

依赖DAG、权限、root、契约、资源、workspace和风险的动态适用性留给后续claim/preflight重新计算。内核不因旧依赖暂时不满足而拒绝Task进入open，但也不允许open状态绕过claim/start时已有的硬不变量。

## API 与工具轮廓

- `POST /api/v1/projects/{project_id}/completion-proposals`
- `POST /api/v1/projects/{project_id}/completion-proposals/{proposal_id}:confirm`
- `POST /api/v1/projects/{project_id}/completion-proposals/{proposal_id}:reject`
- `POST /api/v1/projects/{project_id}:reactivate`
- `POST /api/v1/projects/{project_id}/tasks:restore-to-open`
- `GET /api/v1/projects/{project_id}/completion-history`

MCP/CLI映射到同一应用命令。普通Agent可以提交完成建议，但`confirm_project_completion`只对user/control暴露；current main的`project_reactivate`工具是否可用由当前policy和authority判定。

## 领域事件

- `ProjectCompletionProposed`
- `ProjectCompletionProposalSuperseded`
- `ProjectCompletionConfirmed`
- `ProjectCompletionRejected`
- `ProjectReactivated`
- `ProjectTaskRestorePlanCreated`
- `ProjectTasksRestoredToOpen`

事件、proposal和user confirmation永久保留。再次完成同一Project时创建新的completion proposal/confirmation cycle，并引用上一次completion和reactivation记录。

## 不变量与验收场景

1. 普通Task完成不会触发用户确认或Project lifecycle变化。
2. 所有Task完成也不会自动完成Project；缺少user confirmation时保持active。
3. completed状态禁止普通Task创建/自动调度，但允许查询、审计、follow-up提案和重激活。
4. 重激活创建新runtime epoch，不复活旧运行权限或Attempt。
5. 历史Task不会自动open；只有显式批量选择改变它们。
6. 批量恢复选中Task直接open，但不会跳过claim/preflight或创建owner。
7. current main作业务判断，内核只守并发、身份、终态和唯一owner/Attempt等结构不变量。
8. 任一Task revision在计划和提交间变化，整个batch返回冲突且零Task改变。
9. completed Task永不重开；follow-up保留与原Task的关系。
10. completed和archived保持独立、可审计的生命周期语义。
11. user确认项目完成前必须执行静止；任务处置由主 Agent决定，内核只验证没有合法执行权仍存活。

## 后续待决定

- ProjectCompletionProposal与restore plan的完整JSON Schema、索引和列表分页。
- completion checkpoint是确认事务后的必需Operation，还是允许completed先可见、checkpoint随后收敛。
