# 03 任务协调与验收

## 核心不变量

Task 在同一时刻最多一个 current Attempt，一个 Attempt 只有一个不可改 owner。主 Agent 管理任务不等于拥有子 Agent Attempt；子 Agent 只能提交自己的 Attempt。系统不选 owner，开放任务由合格参与者原子 claim；无 offer/竞价调度器。

## 数据

| 表（`tasks_`） | 必填字段与规则 |
|---|---|
| tasks | title, objective, status, parent_task_id?, current_attempt_id?, execution_scope, scope_revision, required_capabilities, prerequisites[], acceptance_policy, policy_digest, followup_of?；parent 只导航 |
| edges | source_task_id,target_task_id,kind:blocks\|related；blocks 表示 source 满足 success prerequisite 后 target 可开始，检测 DAG；related 允许环 |
| attempts | task_id,owner_agent_id,owner_session_id,execution_epoch,status,scope_snapshot_digest,capability_snapshot_id,workspace_id?,created_input_digest,close_reason?；current 唯一约束 |
| preflights | attempt_id,input_revisions,input_digest,scope_digest,report_ref,contract_refs,lease_refs,workspace_ref,risk_ref,verdict:ready\|blocked,blockers[]；不可变，start 重验输入 |
| suspensions | attempt_id,reason_code,dependency_refs,checkpoint_summary,evidence_refs,observed_event_seq,status:active\|cleared；无默认时限 |
| results | attempt_id,summary,evidence_refs,artifact_refs,workspace_result_ref?,digest；不可变，提交不是 completed |
| review_rounds | task_id,attempt_id,result_id,policy_digest,round,status:pending\|accepted\|changes_requested\|rejected,required_slots[] |
| review_decisions | round_id,slot_id,actor_id,verdict,evidence_refs,reason,digest；每 slot 一个有效决定，修订另开 round |
| scope_requests | attempt_id,requested_scope,reason,input_revisions,digest,status:pending\|approved\|rejected\|superseded |

索引：task `(status,created_at,id)`、`parent_task_id`、attempt `(owner_agent_id,status)`；task.current_attempt 与 attempt.task 必须一致。TaskResult 绑定精确 child task/attempt/result/digest，后续子结果不替换历史引用。

## 状态转换

| 动作 | Task 前→后 | Attempt 与资源 |
|---|---|---|
| create / ready / publish | 无→draft→ready→open | 主 Agent或用户创建，ready 验证结构，publish 开放领取 |
| claim | open/blocked/orphaned→claimed | 创建 Attempt claimed；锁定当前 owner，尚无执行权。blocked/orphaned 任务不要求原 Agent 在线；新 Agent claim 时旧 Attempt 只保留历史 |
| preflight | claimed 保持；blocked 可准备恢复 | 报告、契约、scope、能力、风险、workspace、预留 Lease 全部有版本证据 |
| resume | blocked→claimed | 原 owner 的便利恢复路径，重新 preflight；不是新 Agent 领取任务的前置条件 |
| start | claimed→running | owner显式执行，重新检验，发task_attempt grant；旧执行代次失效 |
| block | running/claimed→blocked | 保存 suspension、撤执行 grant、释放 Lease；旧 Attempt 进入 blocked 历史，原 owner 可 resume，后来 Agent 可 claim |
| submit | running→submitted | 固化 result，Attempt submitted，撤执行 grant/Lease，启动 review |
| review accept | submitted→completed | all_of 所需槽通过后关闭 Attempt accepted |
| request changes | submitted→changes_requested | 关闭旧 Attempt；主 Agent publish 后新 Attempt，不复活旧结果 |
| request cancel | claimed/running/blocked→cancel_requested | 冻结执行，允许安全收敛与 stop evidence |
| finish cancel / fail | 允许收敛态→cancelled/failed | 关闭 Attempt；未知外部停止保留 residual risk |
| lost execution ownership | claimed/running→open | 旧 Attempt→orphaned；失联证据、Lease 过期或 daemon 重启只撤 Grant、释放执行 Lease，不能认定物理进程停止；任务重新进入公共领取队列 |
| recover/reassign | open/blocked/orphaned/cancelled/failed→open | 主 Agent处置历史 Attempt；不是后来 Agent claim 的前置步骤，换 owner 新建 Attempt |
| follow-up | completed 保持，创建新 draft | 不复活 completed；关联 followup_of |

draft/ready/open 无执行者，可由 main/user取消。changes_requested 重新发布前可修改 task 计划；已有 active Attempt 禁止无记录改变范围。所有状态更新递增 Task/Attempt revision 并记录事件。

## Preflight 和 scope

claim 检查 baseline、required capabilities、任务开放、project gates、eligibility；resume 核对恢复条件和已有领域证据，将 blocked 转 claimed，随后可准备workspace/申请Lease，再preflight/start。start 在同事务核对：当前 owner/session/epochs、scope digest、必要 EpistemicReport、当前有效契约、适用 blocker、工作空间 ready、完整 Lease set 仍有效。任何一项变化返回详细 blockers，不能半启动。resume成功只表示恢复准备，绝不等于running。

owner 请求扩大范围；main 在自身可委派范围内批准。批准生成新 Task scope revision，撤旧 Grant，running 进入 blocked/scope_changed、释放相关 Lease，再由 owner resume。越过 user ceiling、信任边界或协调根须 UserDecision。

execution Lease 只约束当前执行 Attempt，不约束 Task 的存在或未来领取。可在 claimed preflight 预留；未及时 start 则过期，需要重取。blocked 协商不持有/续执行 Lease；Lease 过期后任务回到 open，任意合格 Agent 可 claim。报告与契约操作通过 agent_base 的关系约束完成。

## 验收、依赖和委派

acceptance_policy 是固定 discriminated schema：`automated`（指定 checks/evidence）、`reviewer`（指定 reviewer slots）、`self`（低风险且 policy 明确允许）；混合时 `all_of`，不引入 DSL/任意布尔表达式。自动检查由 Job执行，不能在写事务跑测试。reviewer 获得 task_review grant，不获得文件写权限。主 Agent 只有被指定 reviewer 时才能以 reviewer 身份接受。

blocks 默认 source completed 满足，failed/cancelled 不自动满足；main 可显式修改依赖并留理由。parent_task_id 不自动创建 blocks。创建子任务不暂停父任务，父终态不级联取消子任务，父提交不要求所有孩子 completed。父 owner 自行解释采用哪些结果。

上游待用户确认仅阻塞关联 action/依赖；owner 主动 block/结束当前 LLM 轮次。黑板提供变化供恢复判断，变化不自动重新开始文件写入。没有外部 wake 的宿主仍满足手动/pull 恢复基线。

## 端口与测试

公开 `get_attempt_context`、`get_task_scope`、`get_review_relationship`、`close_attempt_for_succession`、`restore_open_batch`，全部返回稳定 DTO；所有写带 UoW。事件 task_created/published/claimed/started/blocked/submitted/reviewed/completed、attempt_closed、task_scope_revised。

验收包括百次并发 claim 单 owner；父子独立；旧 result/reviewer round 不可重放到新 round；blocked协调可用但执行不行；completed只能 follow-up；用户长时间不回复不改变状态；恢复批次全成或全败。实施 T08/T09/T13/T15。
