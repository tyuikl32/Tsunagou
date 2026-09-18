# 05 资源意图、冲突与 Lease

## 边界和数据

ResourceIntent 表示“准备使用什么”，Lease 表示“协调中心当前允许哪个 Attempt 使用”。二者都不是 OS 文件锁或文件系统 fencing。Job worker lease 与资源 Lease 是不同类型、不同表、不同 API。

| 表（`resources_`） | 字段与约束 |
|---|---|
| intents | task_id,attempt_id,owner_agent_id,scope_digest,resources[],reason,revision；resources 每项 ResourceKey+mode |
| acquisition_requests | attempt_id,intent_id,intent_revision,request_digest,status:waiting\|granted\|cancelled,base_priority,enqueued_at,lease_set_id? |
| lease_sets | attempt_id,execution_epoch,scope_digest,request_digest,status,expires_at,last_renewed_at |
| leases | lease_set_id,resource_key,physical_identity?,mode:read\|consistent_read\|exclusive_write\|exclusive_use,status |
| observations | resource_key,source,evidence_digest,observed_at,kind:external_write\|identity_changed\|unexpected_owner；只记录观察 |

索引 active lease resource canonical key/prefix、lease_set attempt/status/expiry；意图必须在 EffectiveAttemptScope 内。同一 acquisition request 原子获取整组，不能先给一半再等另一半。服务端按规范资源 key 排序检查，避免请求顺序导致差异。

## 冲突规则

| 同一物理路径或前缀交叠 | read | consistent_read | exclusive_write |
|---|---|---|---|
| read | 允许 | 允许 | 允许（读者承认可变化） |
| consistent_read | 允许 | 允许 | 冲突 |
| exclusive_write | 允许 | 冲突 | 冲突 |

named resource 的 exclusive_use 与任何另一个 active exclusive_use 冲突；不把它伪装成 path write。不同根别名指向同一物理实体时必须统一冲突，路径祖先/后代覆盖按规范 segments 与本机 identity 判断。

普通 read 不保证读时稳定。需要稳定快照的流程必须声明 consistent_read 或使用 workspace baseline。核心只验证声明，无法推断 Agent 未报告的真实文件需求。

## 租约与等待

execution Lease 默认 TTL 120 秒，bridge 每 30 秒 renew，renew 带完整 lease_set_id、attempt/execution_epoch、scope_digest。Lease 不按每个资源增加 fencing counter；Attempt.execution_epoch + session/runtime fencing 保护系统 API。到期在单写 UoW 标 expired、撤 execution grant、Task orphaned，追加事件；不宣称已杀死物理进程。

claimed 的 preflight 可预留 Lease；start 时再次验证。Task 离开 running、取消 claimed、owner ended、权限撤销时释放；blocked 不续租。短事务内的 preflight→start 可使用同一 lease set，不能跳过仍有效检查。

等待队列按 effective_priority、enqueued_at、id 排序；每 5 分钟 aging 一档，最多 high，无抢占。释放后仅通知候选重新检查，不能在 owner 无上下文时自动开始任务。用户等待不消耗执行 Lease。

## 端口和事件

`check_conflicts(intent,read)->ConflictSet`；`reserve_set(request,ctx,uow)->LeaseSet`；`validate_lease_set(attempt_context,uow)`；`release_for_attempt` / `expire_due` 供同事务流程使用。仅 resources 写自身表。事件 resource_intent_declared、resource_waiting、lease_set_granted/renewed/released/expired、external_resource_change_observed。

## 验收

交叠 prefix 与 alias 冲突，跨根不同物理目录不误冲突；all-or-none 获取；相同 command_id 不重复租；旧 epoch renew 拒绝；用户等待期间无 execution Lease；外部写入只告警/证据，不自动回滚或扩大系统强制边界。实施 T09，依赖 T05/T06/T08。
