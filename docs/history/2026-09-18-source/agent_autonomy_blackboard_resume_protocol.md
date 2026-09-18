# 主 Agent 自治、黑板阻塞与 Attempt 恢复协议

> 核对日期：2026-09-17。
> 状态：第 211–236 题已确认并落盘；对应 D135–D160。第 228–236 题的项目完成细节另见 [project_completion_protocol.md](./project_completion_protocol.md)。
> 目的：在尽量减少用户强制决策的前提下，定义重大决策门槛、持久阻塞、Agent自然挂起、事件恢复、风险接受和契约代理接受。

## 决策映射

| 题号 | 决策 | 选择 | 决策号 |
|---|---|---|---|
| 211 | 逻辑继任与外部收敛分层 | A | D135 |
| 212 | outcome_unknown 只精确阻塞相交动作 | A | D136 |
| 213 | 主 Agent可持续延长风险接受 | B | D137 |
| 214 | 项目范围内不增加时间/范围上限 | B | D138 |
| 215 | 默认自治，重大事项用户确认的混合模式 | A 为主，吸收 B 的重大确认点 | D139 |
| 216 | 最小重大决策集合 | A | D140 |
| 217 | 结构化决策包，只阻塞受影响动作 | A | D141 |
| 218 | 用户未响应是持久依赖，不是超时 | A 的代码方向，经用户语义修正 | D142 |
| 219 | 阶段结果 + blocked_on 后自然挂起 | A | D143 |
| 220 | 依赖满足产生 resume_eligible 并重做预检 | A | D144 |
| 221 | 原 Attempt Agent自主决定何时恢复 | C | D145 |
| 222 | ResumeAttempt 重新计算 blocker/preflight | A | D146 |
| 223 | 变化时保留原 Attempt并重新阻塞 | A | D147 |
| 224 | blocked 状态允许协调性写入 | A | D148 |
| 225 | 主 Agent可推进相关契约/资源变化 | C，受 D150 的策略边界细化 | D149 |
| 226 | 契约直接代行由项目策略授权 | A | D150 |
| 227 | 代理接受记录真实 actor 和授权来源 | A | D151 |
| 228 | 普通任务由协作角色完成，用户只确认项目整体完成 | C | D152 |
| 229 | owner/main 提议项目完成，用户确认 | A | D153 |
| 230 | 用户确认后进入可恢复的 completed | A | D154 |
| 231 | user 始终可重激活，main 按策略也可 | A+B | D155 |
| 232 | 重激活后只恢复显式选择的历史任务 | A | D156 |
| 233 | main 可原子批量选择恢复任务 | A | D157 |
| 234 | 批量事务直接把选中任务置为 open | B | D158 |
| 235 | 内核最小结构校验，业务判断交给 main | C+D 混合 | D159 |
| 236 | 项目完成前由 main 收敛执行面，内核只验证静止 | 是 | D160 |

## 核心产品语义

### 没有上下文就是持久阻塞

- Agent没有新对话上下文、用户没有回复或上游事实尚未出现时，不启动倒计时，不推断拒绝，不把 Attempt标记失败，也不要求宿主进程持续在线。
- Agent可以先提交阶段性结果、当前理解、未决依赖和恢复条件，然后正常结束当前回合。协调中心保存这些事实，后续回合从黑板读取。
- blocker解除只是新事实，不代表 Agent必须立即工作。原 Attempt Agent决定何时发起恢复；系统不依赖外部工具反复重启对话来维持“等待”。

### 黑板是投影，不是第九个业务模块

“黑板”是跨八个模块的只读查询与变化信号面，不能成为绕过领域命令的通用可写 JSON 存储：

| 权威信息 | 所属模块 | 黑板投影 |
|---|---|---|
| UserDecision、用户 ceiling、项目方向状态 | `projects` | 待确认事项、依赖动作、决议摘要 |
| TaskAttempt、blocker、阶段结果、恢复资格 | `tasks` | 运行/挂起状态、blocked_on、resume eligibility |
| EpistemicReport、Proposal、Contract、Acceptance | `cognition` | 未决分歧、契约版本和所需证据 |
| ResourceIntent、Lease、ResidualRiskSet | `resources` | 冲突范围、等待资源、风险 blocker |
| Agent/HostSession/Connection 能力与连续性 | `agents` | 是否能继续原 Attempt、可用投递能力 |
| Workspace/Repository state | `workspaces` | workspace readiness、baseline change |
| Operation/Job/outbox/event | `durability` | 外部收敛进度、outcome_unknown、watermark |
| 指标与实验观察 | `evaluation` | 阻塞时长仅作观察，不驱动用户超时 |

黑板查询可以由 API query facade 聚合这些投影，但写入必须调用 owning module 的类型化命令。

## 权威对象

### UserDecision

```text
UserDecision
  decision_id, project_id, revision
  kind design_change | project_direction | major_goal_or_acceptance_change
       | project_overall_completion | reserved_milestone
       | unresolvable_critical_conflict
       | ceiling_expansion | user_reserved
  status pending | resolved | withdrawn | superseded
  created_by_agent_id, authority_epoch
  background, candidate_options[], recommended_option_id
  impact_scope, risk_summary, reversibility
  affected_action_refs[], affected_task_refs[]
  required_user_principal
  resolution, resolved_by, resolved_at
  created_at, supersedes_decision_id?
```

- `pending` 没有 deadline、expiry 或自动选择推荐方案的语义。
- resolution 必须绑定当前 decision revision；修改候选、影响范围或推荐方案创建新 revision/新 decision，不能让用户确认旧摘要后执行新动作。
- `project_overall_completion` 指业务上宣告项目整体目标完成的用户门槛。普通 Task由 owner、reviewer或current main按任务验收策略完成；技术子步骤、自动测试通过、子任务提交和 Operation完成不自动升级为用户确认。只有用户明确保留的关键里程碑使用 `reserved_milestone`。

### AttemptBlocker

```text
AttemptBlocker
  blocker_id, project_id, task_id, attempt_id
  blocker_type, status active | resolved | superseded
  action_scope, resource_scope
  dependency_refs[], required_evidence[]
  source_revision_digest
  created_at, resolved_at?, resolution_evidence_refs[]
```

- blocker 针对动作和范围，不默认冻结整个 Project或整个 Attempt。
- `awaiting_user_decision`、`waiting_on_children`、`contract_changed`、`resource_conflict`、`residual_risk`、`workspace_changed`、`scope_changed` 等使用稳定类型。
- blocker只能由拥有事实的模块写入或解决；黑板 projector不自行推断解除。

### SuspensionSnapshot

```text
SuspensionSnapshot
  suspension_id, task_id, attempt_id, owner_agent_id
  attempt_revision, execution_epoch
  phase_result_summary, artifact_refs[], evidence_refs[]
  current_understanding, assumptions[], uncertainties[]
  completed_work[], remaining_work[]
  blocked_on[], resume_conditions[]
  next_actions[], submitted_at
  supersedes_suspension_id?
```

- snapshot 是不可变阶段记录，更新通过 supersedes 串联。
- 正文遵循内容采集与权限规则；大对象使用 artifact/resource refs。
- Task继续使用既有 `blocked` 状态；`suspended` 是查询投影/原因，不扩张 D33 的 Task状态枚举。

### ResumeEligibility

```text
ResumeEligibility
  eligibility_id, task_id, attempt_id
  triggering_event_refs[]
  evaluated_blocker_revisions[]
  status eligible | consumed | stale | superseded
  created_at, consumed_by_command_id?
```

- 它是提示和 CAS 输入，不授予执行权，不恢复 Lease，不唤醒模型，不改变 Attempt owner。
- 后续 blocker或依赖 revision变化会使 eligibility stale；Agent仍可直接请求 ResumeAttempt，由服务端读取最新事实。

### RiskAcceptance

```text
RiskAcceptance
  risk_acceptance_id, project_id
  risk_set_id, risk_digest
  task_id, attempt_id, action_scope
  accepted_by_agent_id, authority_epoch
  reason, evidence_refs[]
  valid_until_task_terminal: true
  revision, status active | stale | revoked | ended
  created_at, extended_at?
```

- current main可以持续延长或重申接受，不设置累计时长和延长次数上限；延长必须仍处于用户/project ceiling内并记录审计。
- task terminal、risk digest变化、Attempt替换、scope/baseline变化或用户撤销使接受结束或 stale。
- 风险接受不创建 capability、不扩大 root scope、不改变用户 ceiling，也不把 outcome_unknown改写成 succeeded。

### ProxyAcceptance

```text
ContractAcceptance
  acceptance_id, proposal_id, content_hash
  acceptance_kind direct | proxy
  actor_agent_id
  represented_participant_ids[]
  policy_id, policy_revision, authorization_scope_digest
  reason, evidence_refs[]
  authority_epoch, created_at
```

- `direct` 只代表 actor本人接受；`proxy` 明确表示主 Agent依据策略代行。
- 代理接受的 actor永远是实际 current main，不能把 `actor_agent_id` 写成被代表 Agent。
- proposal content hash 必须覆盖参与者集合、可代理类别和适用 scope；策略 revision或授权范围改变后，旧代理接受不能静默扩展。

## 状态与命令

### `CreateUserDecision`

- 允许 user/control 或 current main创建；普通 Agent通过消息/领域请求建议创建。
- 同一 UoW 写 UserDecision、受影响动作 blocker、事件和 outbox。
- 命令必须给精确 affected actions；禁止使用“冻结整个项目”作为默认影响范围。

### `ResolveUserDecision`

- 仅 user/control 可解决默认重大决策；请求绑定 decision revision、选项/自定义决议、理由和必要的 ceiling变更。
- 同一事务写 resolution 与领域事件；owning modules消费事件并重评 blocker。决议本身不直接恢复 Attempt。

### `SuspendAttempt`

- 仅 current Attempt owner可提交自身 SuspensionSnapshot；主 Agent可以请求或提醒，但不能伪造其理解和阶段结果。
- 命令验证 attempt/revision/execution epoch，保存 snapshot，释放执行 Lease，并使 Task/Attempt进入既有 `blocked` 语义。
- suspend成功不要求 HostSession继续在线；对话可安全结束。

### `ResumeAttempt`

- 仅原 Attempt owner的有效、连续 HostSession可调用；不能通过 body指定另一个 actor。
- 输入含 command ID、attempt ID、expected attempt revision、可选 eligibility ID、最新报告/intent/contract refs。
- 同一 UoW重新评估 active blockers和完整 preflight。全部通过时进入 `claimed`，重新取得 grant/资源后显式 start到 `running`；失败保持 `blocked`并返回 typed blockers。
- 如果 HostSession/conversation连续性无法证明、Attempt已被 successor替换或 owner不再匹配，返回不可恢复错误并进入 succession流程。

### `ExtendRiskAcceptance`

- current main在 active authority epoch内调用；绑定精确 risk digest、Attempt、action scope和当前 revisions。
- 无额外的累计时长/次数上限，但每次调用重新检查用户/project ceiling和重大方向门槛。
- 输入事实未变时幂等延长/重申；事实变化返回 stale_risk_acceptance并要求重新建立接受。

### `ApplyProxyAcceptance`

- 只有 current main且项目策略对 contract kind/scope明确授予 proxy权限时可调用。
- command验证 proposal/content hash、required participants、policy revision、authority epoch和代表范围；成功写明确的 proxy acceptance。
- 策略未授权返回 `proxy_acceptance_not_allowed`，主 Agent只能继续正常 Proposal/Acceptance流程或创建重大决策包。

## REST、MCP 与事件轮廓

### REST actions

- `POST /api/v1/projects/{project_id}/decisions`
- `POST /api/v1/projects/{project_id}/decisions/{decision_id}:resolve`
- `POST /api/v1/projects/{project_id}/tasks/{task_id}/attempts/{attempt_id}:suspend`
- `POST /api/v1/projects/{project_id}/tasks/{task_id}/attempts/{attempt_id}:resume`
- `POST /api/v1/projects/{project_id}/risks/{risk_set_id}:accept-or-extend`
- `POST /api/v1/projects/{project_id}/contract-proposals/{proposal_id}:proxy-accept`
- `GET /api/v1/projects/{project_id}/blackboard`：只读聚合投影，使用 after_seq 或稳定 keyset cursor。

MCP工具投影使用相同应用命令：`decision_create`、`attempt_suspend`、`attempt_resume`、`risk_accept_or_extend`、`contract_proxy_accept`、`blackboard_read`。用户决议仍通过 control/user界面，不给普通 Agent伪造用户确认的工具。

### 领域事件

- `UserDecisionCreated`、`UserDecisionResolved`、`UserDecisionSuperseded`
- `AttemptSuspended`、`AttemptResumeEligible`、`AttemptResumeRequested`
- `AttemptResumePreflightPassed`、`AttemptResumeBlocked`
- `AttemptBlockerAdded`、`AttemptBlockerResolved`
- `RiskAcceptanceCreated`、`RiskAcceptanceExtended`、`RiskAcceptanceStale`
- `ContractProxyAccepted`、`ContractProxyAcceptanceRejected`

SSE只发送这些变化类型、subject refs和最新 project event sequence；可靠内容仍通过 REST/MCP查询。事件出现不要求 adapter立即启动新模型回合。

## 不变量与并发

1. 用户沉默不产生 timeout、拒绝、默认批准或失败。
2. `resume_eligible` 不等于 resumed；只有 owner提交 `ResumeAttempt` 且preflight通过才恢复。
3. blocker按动作/scope生效；无关任务和不相交动作继续。
4. blocked Agent仍可做协调性写入，但这些命令不能取得执行 Lease或绕过 blocker。
5. main Agent不能伪造普通 Agent的 EpistemicReport、直接 ContractAcceptance或执行证据。
6. proxy acceptance保留真实 actor和策略来源；策略未授权时不得生效。
7. 所有 mutation使用 command ID、expected revision和必要的 authority/execution epoch；提交前再次校验。
8. Operation/outcome_unknown不会回滚已经提交的逻辑 responsibility，只影响相交动作的安全许可。
9. 投影可从领域事件重建；黑板数据损坏不能改变权威状态。
10. 用户/project ceiling始终是硬边界；主 Agent自治减少审批次数，不扩大最终授权来源。

## 关键验收场景

- 用户决策保持 pending 数小时或数天，相关 Attempt保持 blocked，其他任务正常完成；没有自动超时动作。
- 子 Agent提交 SuspensionSnapshot后连接关闭；daemon重启后黑板仍展示精确 blocker和恢复条件。
- 依赖解除产生 resume_eligible，但系统不自动唤醒；原 Agent稍后 ResumeAttempt并通过新 preflight继续同一 Attempt。
- resume前 contract/workspace已变化：原 Attempt保持 blocked并获得新 blocker，不创建 successor或静默接受变化。
- outcome_unknown与 successor write scope部分相交：只阻塞交集，不相交只读/写入继续。
- 主 Agent多次延长同一风险接受无需用户逐次确认；risk digest变化后旧接受立即 stale。
- policy允许 proxy acceptance时记录实际主 Agent和被代表参与者；policy禁止时不能让 Contract生效。
- 主 Agent提交任务最终完成建议时创建 UserDecision；用户确认前只阻塞最终完成动作，补充证据与无关任务继续。

## 后续待决定

- 项目完成确认时如何收敛仍在执行或仍绑定current Attempt的非终态任务，见 [project_completion_protocol.md](./project_completion_protocol.md)。
- UserDecision、AttemptBlocker、SuspensionSnapshot、RiskAcceptance 和 ProxyAcceptance 的完整 JSON Schema与数据库索引。
- 四个适配器如何呈现 resume_eligible，而不把“可恢复”误实现成强制新模型回合。
