# FX2 技术设计

状态：已实施及验证。复用 application workflow 和 command UoW。最终协议以 registry 和下面的实际路由为准；验证见 implementation-progress.md。

## 1. 对 Agent 的执行入口

| 命令 | 拟定 HTTP / 权限 | 输入与结果 |
| --- | --- | --- |
| task.begin | POST /api/v1/commands/task.begin；B / task.claim | payload 为 task_id、expected_task_revision；身份取已认证 context。返回 task_id、attempt_id、workspace_id（非文件任务为 null）、owner_agent_id、status、执行范围与当前版本 |
| task.submit | POST /api/v1/commands/task.submit；B / task.execute | payload 为 task_id、attempt_id、summary、artifact_refs、evidence_refs、validation_metadata；返回 result_id、workspace_result_ref、status=submitted |
| task.block / fail / cancel_ack | 保留对应公开命令及现有权限 | 一次处理任务状态、资源占用和撤权；字段依原语义，owner 与 attempt 必须一致 |
| task.recover | 保留；M / task.manage | expected_attempt_id、disposition=reopen/cancel/fail、reason；显式回收 claimed/running 也可用，旧 Attempt 随即失效 |

沿现有 command envelope 使用 command_id、project、scope 等上下文，不增加 actor 自报字段或用户权限。CLI 与 MCP 都调用同一个 begin/submit handler。桥接层可从已有任务上下文填充版本；发生实际版本变化应返回新上下文，让 Agent 重读变更，不能自动同意新的业务计划。

begin 是写任务的默认路径。删除外部 task.claim、task.preflight、task.start、resource.acquire/renew、workspace.prepare/result 的多步仪式，所需领域操作保留为内部方法；同步清理公开目录和生成物，不留兼容空实现。resource.intent 的准备输入由任务范围和 main 的共享资源声明提供，不要求 Worker 再填一次等价声明。resource.release 的正常执行释放并入任务终止操作，main 的异常回收经 task.recover。

submit 自动调用现有 WorkspaceEvidence/result 逻辑，Worker 不再先提交 workspace.result 再复制其 ID。validation_metadata 是 Agent 报告的测试命令、时间、退出码，不提升成操作系统强证明；是否满足业务目标由 main 审查。

## 2. begin 的事务与恢复

1. 校验项目成员、task.claim 权限、task revision、任务依赖及 main 已选定的工作区策略，解析规范化 root/scope。
2. open 可创建 Attempt；blocked 按原恢复规则处理，仍未解除的明确依赖阻止执行。同 owner 的 running Attempt 可恢复同一上下文，不重建 Attempt；其他 owner 拒绝。
3. 检查并取得全部需要的资源占用；冲突返回真实 owner/资源和阻塞原因，不等待模型续租或 worker.ready。
4. 在已有工作区取得基线，检查本任务必需契约及 scope，把 task/attempt 标为 running，签发当前运行期 Grant，并写事件/outbox。
5. 上述领域变更经既有锁与 UoW 原子提交。中途失败回滚本次 Attempt、占用和 Grant，原 open/blocked 状态保留；只写失败诊断，不写成功开始。禁止建立一个 claimed 任务再要求用户收拾半套准备。

使用现有进程级串行锁协调准备与提交，文件扫描、只读 Git 和 patch 物化在 SQLite BEGIN 之前完成；事务内重核 revision/owner/scope 并写领域状态。不会在操作尚未完成时授予 Worker 执行权；基线并非文件系统锁。外部用户手工写入仍按已有变更检测语义处理。

同 command_id 网络重试重放已有业务结果。新 begin 请求面对已经 running 的同 owner，检查当前范围、策略和 Attempt 后返回同一 Attempt；重启时重新签发当前 Grant。结果不携带可跨重启使用的旧 bearer token，不从幂等缓存恢复已撤销授权。

## 3. 工作区策略与资源占用

IsolationDecision 从 attempt 归属改为 task 归属，记录 task_id、scope_revision、decision revision、driver、root bindings 和 main 的理由。已有 workspace.select 同步移除必填 attempt_id；不设系统擅自选择的隔离默认值，main 在发布前选择一次即可。

Workspace 与 BaselineManifest 仍按 Attempt 生成。新 owner、新 Attempt 或显式 scope/策略变化需新基线，但不会因读上下文、重连或纯 task status revision 增长要求 main 重选策略。Git worktree/branch 创建及整合仍由 main 控制；begin 使用已准备好的物理路径，缺少时明确返回 main 需准备的事项，不替用户运行 Git 写命令。

资源范围由 task execution_scope 加上 main 声明的 named resources 规范化产生，不扩大到整个项目以逃避细分，也不允许 Worker 扩大 scope。没有文件或排他资源的非编码任务不制造占位 Lease 或无意义 workspace。

资源对象统一为 ResourceReservation：reservation_id、task_id、attempt_id、owner_agent_id、execution_epoch、scope_digest、resources、status、created_at、released_at、release_reason。移除 expires_at、last_renewed_at、TTL、renew；只有 active/released。时间用于溯源，不参与活性推断。后台 Job lease 保持自己的内部语义。

结束时 release_for_attempt 是幂等领域操作。submit/block/fail/cancel_ack、无执行者的取消和 main 显式回收与撤 Grant 一同提交。取消请求、断线、静默、长构建不释放占用。

同库启动不 release/orphan/open 原任务；只使旧运行期 Grant 失效。原 owner 再 begin，依据持久 scope/Attempt/策略恢复；其他 Agent 不能借重启领取。新副本 checkpoint 导入仍不继承活动授权，和同库重启明确区分。

main 改变正在执行任务的 scope 时不能仅删旧占用便开放重叠范围；先由 owner 挂起/确认停止或 main 显式回收，再发布新策略。无需新增自动死亡判定或用户审批。

## 4. 删除重复状态和不相关门槛

Task/Attempt 是执行状态唯一来源。coordination plan 保留 main 的分工意图、assigned worker、通知和投影；保留既有定向分派边界，不因为删除 ready 就让无关 Worker 接管。依赖统一读取 Task 的依赖关系，不再根据另一份 assignment.status 判断完成。

删除 worker.ready 公共命令及 require_worker_ready 的回执门槛；将身份匹配和任务依赖检查移至 begin 的正常领域检查。活动回合是否开始由宿主返回及实际 Agent 请求记录，不能让模型额外填写一份运行证明。coordination 中重复的 wake deadline/worker_ready 状态退役，使用现有 hostwake 投递记录；唤醒失败不把可领取任务改成业务 blocked。

main 可以明确指定 required_contract_ids（在任务计划中，默认空）；只检查这些当前引用。普通 proposed 报告、其他任务契约及仅供参考的协商不自动形成门禁。必需契约未接受或已撤销时返回具体引用，main 可替换/取消依赖；不能默默把明确必需条件当作满足。准备摘要只包含本任务 scope、策略及必需契约，不再包含全项目契约列表或续租时间。

## 5. 失败、审查和完成

复用现有 Problem 类型及诊断通道。失败响应说明真实阻塞、关联对象与下一步负责角色，不给模型几十项检测清单。begin 成功时间、submit 时间、main review 时间分别留档。submit 是提交成果，不等于用户确认重大交付完成。

FX1 状态修复与本任务一起验证。迁移、旧格式读取、旧客户端适配全部退出范围；源码、Skill 和打包 bridge 必须同版本。
