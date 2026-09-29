# 05 资源占用与冲突

本页按 FX2 更新。资源协调使用 ResourceReservation；后台 Job 的内部 lease 是另一类对象。

## 数据与边界

每条占用包含 reservation_id、task_id、attempt_id、owner_agent_id、execution_epoch、scope_digest、resources、status、created_at、released_at、release_reason。status 只有 active/released；内部时间为 UTC 毫秒，查询输出 RFC3339 毫秒。没有 TTL、到期、续租、模型 heartbeat 或资源等待队列。

占用由 task.begin 根据 main 已确认的 execution_scope 一次创建。Worker 不重复声明范围，也不能通过 begin 增加文件路径。空 scope 表示非文件任务；仅 named 资源不制造工作区。

占用是协调中心内的权限记录，不是操作系统文件锁。Full Access Agent 或用户手工写入的责任由实际观察和主 Agent 判断，系统不猜测写入者。

## 冲突规则

| 相同物理根且路径前缀交叠 | read | consistent_read | exclusive_write |
|---|---|---|---|
| read | 允许 | 允许 | 允许 |
| consistent_read | 允许 | 允许 | 冲突 |
| exclusive_write | 允许 | 冲突 | 冲突 |

named 资源仅在 namespace/name 相同且双方 exclusive_use 时冲突。不同名称互不阻塞。路径根别名按持久化的物理 identity 归一，segments 按现有路径规范比较。

整组占用全成或全败；失败返回 HTTP 409、code=resource_conflict，以及 blockers 中真实的 resource_key、reservation_id、task_id、attempt_id、owner_agent_id。不创建部分占用，不自动等待或抢占。主 Agent 判断下一步。

## 释放与恢复

submit、owner block/fail/cancel_ack、无执行者取消、main recover/takeover 在同一 command UoW 更新任务、释放占用并撤销执行 Grant。取消请求和用户决策提案不会假定运行中的 Worker 已停止。

断线、静默、长构建和同库重启均保留 owner/占用。同库重启撤旧执行 Grant；原 owner 重新 begin 得到同一 Attempt 的当前授权。他人不能借重启领取。main 显式回收后新 owner 才能开始。新副本的 checkpoint 导入不继承活动占用。

release_for_attempt 幂等；重复调用不改首次 released_at/release_reason。task.progress 只记录进度。

## 实施与验收

领域实现为 modules/resources.py；编排为 application/workflows/execution_commands.py；持久化走已有 SQLite module_state、审计与 outbox。模块不启动后台线程或第二个数据库。

验证入口：tests/unit/test_resources.py、tests/unit/test_runtime_maintenance.py、tests/integration/test_execution_begin.py。覆盖冲突矩阵、根别名、不同 named 资源、原子回滚、长时间静默、重启恢复及各显式释放路径。实际验收状态见 [FX2 进度](../../../.trellis/tasks/09-28-fx2-execution-flow/implementation-progress.md)。
