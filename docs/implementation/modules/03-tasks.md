# 03 任务协调与验收

本页按 FX1/FX2 修订执行流程，公开接口以 [命令目录](../command-catalog.md) 和 protocol schemas 为准。

## 唯一执行事实

Task 同时最多一个 current Attempt；Attempt 的 owner_agent_id 不可转移。换 owner 必须关闭旧 Attempt 并创建新 Attempt。main 管理任务不等于拥有 Worker 的执行权。coordination assignment 只记录定向分工，执行状态始终读取 Task/Attempt。

Task 保存 title、objective、parent_task_id、blocks（前置任务 ID 集合）、status、revision、scope_revision、execution_scope、required_contract_ids、current_attempt_id，以及阻塞/挂起摘要。parent 只导航，不暗含依赖或父子级联取消。

Attempt 保存 task_id、owner_agent_id、status、execution_epoch、revision、started_at、ended_at。Result 保存精确 task/attempt、submitted_by、payload、digest；Review 引用明确 result。事件时间由持久化层记录，不能拿另一个实体的时间冒充创建时间。

## 外部状态转换

| 操作 | 结果及约束 |
|---|---|
| create / ready / publish | draft → ready → open；main 发布范围、目标与必要依赖 |
| begin | open/blocked → running，一次生成 Attempt、必要基线与占用、执行 Grant；失败整体回滚 |
| begin（同 owner running） | 复用原 Attempt/基线/占用；必要时重签当前 Grant |
| block | owner 记录挂起摘要，Attempt blocked，Task blocked；显式释放与撤权 |
| submit | owner running → submitted；自动采集工作区结果、固化 Result、释放与撤权，通知 main 审查 |
| review accept | 精确 submitted result → completed |
| request changes | submitted → changes_requested；关闭旧 Attempt，main 修改计划并重新发布后再 begin |
| cancel_request（仍有执行者） | cancel_requested；保持占用，等待 owner cancel_ack 或 main recover |
| cancel_request（无执行者） | 直接 cancelled，保留已提交结果；不要求不存在的执行者 ACK |
| fail / cancel_ack | owner 关闭精确当前 Attempt，释放与撤权 |
| recover | main 指定 expected_attempt_id 和处置理由，显式 reopen/cancel/fail；不复活终态 |
| follow-up | 完成任务保持 completed，另建关联任务 |

claimed/start 是编排内部短事务的原语，外部不再分步调用 claim、resume、preflight、start。公开成功的 begin 已是 running。

## begin / submit 契约

begin 输入 task_id、expected_task_revision；身份来自认证 context。检查当前版本、定向 assigned worker、真实任务依赖、明确 required_contract_ids、关联 pending UserDecision 及 main 的工作区选择。

默认 required_contract_ids 为空。只检查明确引用的契约当前是否 accepted；不要求每项任务先写认知报告，也不让无关 proposed 契约阻断工作。理解分歧仍通过认知/契约工具协调。

文件扫描、只读 Git 与内容寻址 patch 物化发生在 SQLite 写事务之前；既有进程串行锁固定准备期间的领域上下文。短 UoW 内复核状态，一次提交 Attempt、manifest、占用、Grant、事件和 outbox。扫描不是文件系统锁。

submit 输入 task_id、attempt_id、summary，可带 artifact_refs、evidence_refs、validation_metadata。workspace_result_ref 由 daemon 自动生成，Worker 不自行提供。测试命令与退出码属于 Agent 报告；观察到文件变化不等于验证业务正确。

同 command_id 重试返回原结果、不重复扫描或事件。重启后应发新的 begin 命令恢复当前授权；旧幂等结果不携带可重用的执行 token。

## 等待、范围和重启

scope 只由 main 修改。active Attempt 存在时先 owner block/确认停止或 main 显式回收，再变更 scope 与工作区策略。旧 scope_revision 的策略不能用于新范围。

提出用户决策只保存 pending 决策并通知相关 owner；不会假装宿主已停止。owner 挂起后，pending 决策阻止该任务重新 begin；无关任务继续。等待没有默认超时。

静默或同库重启不改变 Task、Attempt、owner 和资源占用。重启只撤旧执行 Grant，原 owner 再 begin 恢复；主 Agent 可显式回收。新副本 checkpoint 恢复另按不继承本地授权处理。

## 验收边界

普通任务由 main 审查结果；项目完成和重大设计仍走用户控制确认。ACK、认知契约接受、结果 submitted、Task completed、Project completed 是不同事实。

执行验证见 tests/integration/test_execution_begin.py；契约/取消完整性见 test_state_integrity.py；完整业务闭环见 test_m1_runtime_flow.py。后续计划不得重新引入模型续租、额外 ready 回执或 assignment 的重复执行状态。
