# 持久 Operation、Job 与副作用恢复研究

> 核对日期：2026-09-17。
> 状态：研究结论与候选方案；标为“已确认”后才构成实现约束。

## 外部依据

- HTTP `202 Accepted` 表示请求已被接受但尚未完成；响应应描述当前状态并指向状态监视资源，不能把 202 当成最终成功。
- RFC 9110 的 `Retry-After` 表示客户端再次请求前至少等待多久；内部 job 调度仍需要自己的 `next_attempt_at`，两者职责不同。
- AWS 的幂等 API 设计建议由调用方提供唯一请求标识，同一调用者和标识返回语义等价结果；同一标识携带不同参数应作为冲突处理。
- SQLite `UPDATE ... RETURNING` 可以在更新 job 所有权的同一语句中返回被领取的行；真正提交仍受外层事务控制。

来源：

- [RFC 9110: 202 Accepted](https://www.rfc-editor.org/rfc/rfc9110.html#name-202-accepted)
- [RFC 9110: Retry-After](https://www.rfc-editor.org/rfc/rfc9110.html#name-retry-after)
- [AWS Builders' Library: Making retries safe with idempotent APIs](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/)
- [SQLite RETURNING](https://www.sqlite.org/lang_returning.html)

## 候选模型

### Operation：调用者可见的异步结果

- 任何不能在一个数据库事务内完成的命令先创建 `Operation`；HTTP 返回 `202`、Operation 表示和 `Location`。快速查询、纯数据库命令仍可同步返回，不强制创建 Operation。
- 状态固定为 `pending`、`running`、`retry_wait`、`cancel_requested`、`succeeded`、`failed`、`cancelled`、`outcome_unknown`。
- 最小字段：`operation_id`、`project_id`、`kind`、`subject_refs`、`requested_by`、`idempotency_key`、`request_hash`、`status`、`progress`、`result_ref/result`、`error`、`cancel_supported`、`created_at/started_at/finished_at`、`revision`。
- `succeeded` 只表示已取得可验证的完成证据；`failed` 表示已知未完成且不再自动重试；`outcome_unknown` 表示副作用可能已发生但当前无法证明。
- `progress` 是可选的结构化快照，不是事件真相；状态变化仍写领域事件并推进 project sequence。

### Job：内部执行与重试

- 创建 Operation 的同一 Unit of Work 同时写入首个 `Job` 和 outbox/event；崩溃不会出现“Operation 已存在但没有执行计划”。
- Job 状态固定为 `queued`、`running`、`retry_wait`、`succeeded`、`failed`、`cancelled`。每次领取生成不可变 `JobAttempt`，保存 attempt number、worker/daemon instance、lease、开始/结束时间、结果摘要和错误分类。
- worker 通过 SQLite 条件 `UPDATE ... RETURNING` 原子领取到期且未被占用的 job。job execution lease 只保护 worker 所有权，不代替领域 Resource Lease。
- 同一 Operation 可按步骤拥有多个有依赖关系的 Job，但首版不提供任意工作流 DSL；步骤图由每种 operation handler 在代码中固定。
- job 成功或决定重试/失败时，以短事务更新 Job、Operation、事件和后续 job；外部调用永远不在数据库事务内执行。

### 幂等键和请求去重

- 调用方为所有可创建 Operation 的命令提供 `idempotency_key`；服务端作用域为 `project_id + principal_id + command_kind + key`。
- 首次请求保存规范化 request hash。相同键和相同 hash 返回原 Operation，不创建新 Job；相同键但不同 hash 返回 `409 idempotency_key_reused`。
- 幂等记录随 Operation 历史保留，不采用短 TTL 后静默复用。用户明确创建新意图时必须使用新 key。
- 外部资源尽可能带 `operation_id` 或派生 marker，便于崩溃后证明“这是本次请求创建的对象”。

### 副作用恢复等级

- `idempotent`：使用相同 operation key 重复调用仍得到同一语义结果，可自动重试。
- `reconcilable`：调用本身不完全幂等，但可以通过确定路径、instance nonce、PID/健康端点、Git marker 或宿主 receipt 探测并接管既有结果；先 reconcile，再决定完成或重试。
- `unverifiable`：无法证明副作用是否发生。丢失完成回执后进入 `outcome_unknown`，禁止自动重试；用户或具备权限的主 Agent只能在查看证据后选择 `mark_succeeded`、`mark_failed` 或以新 Operation 重做。
- 每种 handler 必须在注册时声明恢复等级、超时、可取消性、最大尝试次数和 reconcile 函数；缺失声明不能启动。

### 取消和结果语义

- cancel 是请求，不保证撤销。`cancel_requested` 后 worker 在安全检查点停止；若副作用已完成并可验证，Operation 收敛为 `succeeded`；已证明未发生或已撤销时才是 `cancelled`。
- `outcome_unknown` 是终止自动执行的人工处理态，不伪装为 `failed`。解决动作必须记录操作者、证据和理由。
- Operation 终态不可改写；对误判的修正通过 resolution event 和补偿/新 Operation 表达，保留原始历史。

## 典型映射

| 副作用 | 恢复等级 | 主要完成证据 |
|---|---|---|
| 创建 Git worktree | reconcilable | 确定目录、Git worktree 列表、operation marker、目标 commit |
| 启动受管 Agent | reconcilable | instance nonce、PID 创建时间、健康握手和会话绑定 |
| 写共享 checkpoint | idempotent | 内容哈希、目标 revision、原子替换后的 checkpoint 记录 |
| bridge 推送通知 | idempotent 或 unverifiable | 宿主 receipt/delivery ID；缺失时只依赖持久 inbox，不宣称推送成功 |
| 删除本地运行产物 | reconcilable | 受保护根校验、目标 identity、删除后不存在性检查 |

## 下一步需要决定

- Operation/Job/JobAttempt、幂等冲突和三种恢复等级已确认。
- 是否确认下列 job lease、重试、并发和关机默认值。
- worker 数、`concurrency_key`、公平领取和守护进程关闭宽限期。
- 每种 operation kind 的步骤、补偿、证据字段和人工 resolution 权限。

## 候选调度默认值

### 领取与存活

- 守护进程内使用 4 个异步 worker；内存事件负责即时唤醒，1 秒 polling 只作漏信号兜底。
- job execution lease 为 60 秒，运行 attempt 每 15 秒续租。续租事务只更新 lease/heartbeat，不写领域事件。
- lease 过期只说明旧 worker 不再拥有执行权。新 worker 先把旧 JobAttempt 记为 `lease_expired` 并执行 handler reconcile；只有确认副作用未发生或可安全重复时才开始下一 attempt。
- handler 必须声明 attempt timeout，默认 120 秒；允许每种 operation 在 5 秒到 10 分钟范围覆盖。超时与 lease 过期均不直接证明外部副作用失败。

### 错误分类与重试

- 错误固定分类为 `transient`、`conflict`、`invalid`、`permission_denied`、`cancelled`、`ambiguous` 和 `internal_bug`。
- 只有 `transient` 自动重试；`ambiguous` 先 reconcile；conflict/invalid/permission_denied 立即已知失败；`internal_bug` 停止该 operation 的自动执行并保留完整诊断摘要。
- 默认最多 5 次 attempt（包含首次）；handler 可以在注册元数据中降低或提高到最多 10 次，不能由单个 API 请求任意扩大。
- 第 n 次重试使用 full jitter：从 `0..min(60s, 1s * 2^(n-1))` 均匀取值。若可信下游返回更长的 `Retry-After`，取两者较大值，但单次默认不超过 15 分钟；超过时记录截断。
- attempts 耗尽后，已知未发生副作用则 Operation `failed`；无法证明则 `outcome_unknown`。不存在静默无限重试。

### 并发与公平

- job 可带一个 `concurrency_key`；同一 key 同时最多一个 running attempt。Git 变更、Agent 生命周期和同一投递目标分别使用稳定 key。
- 领取顺序按 base priority、等待 aging、`available_at`、创建顺序决定。取消/reconcile 高于普通操作，用户触发操作高于清理和遥测；aging 保证低优先级最终可运行。
- Resource Lease 继续负责领域资源冲突；`concurrency_key` 只避免相同外部目标被并发 handler 操作，不能替代 preflight 或权限检查。

### 项目加载与关机

- 存在 queued/running/retry_wait job 的项目不能因空闲而卸载。守护进程重启后扫描所有已登记项目数据库并恢复到期 job。
- 正常关闭先停止领取，通知运行 handler 到安全检查点，等待 15 秒。确认停止的 attempt 写回 retry/cancel 结果；未确认停止的 attempt 保留 lease，由下次启动在过期后 reconcile。
- 关机不得提前释放仍可能执行副作用的 job lease，也不得因为 daemon 退出就把 Operation 标为 failed/cancelled。

研究依据：

- [AWS Architecture Blog: Exponential Backoff and Jitter](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/)
- [AWS SDK retry behavior](https://docs.aws.amazon.com/sdkref/latest/guide/feature-retry-behavior.html)
- [SQLite transactions](https://www.sqlite.org/lang_transaction.html)
