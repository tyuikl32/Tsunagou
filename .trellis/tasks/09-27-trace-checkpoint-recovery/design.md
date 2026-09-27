# PT4 设计

created_at: 2026-09-27T14:39:38Z

运行时 SQLite 是事实源；共享 checkpoint 由白名单 export DTO 生成，明确排除 secret、runtime epoch、grant/lease、host conversation、private message 和绝对路径。业务事务提交后产生 checkpoint operation，由提交后 worker/重启 reconcile 物化，失败不回滚业务事实。

GitAnchorScanner 解析允许的本地 `refs/heads/*`/`refs/tags/*` 并读取 tree 中 manifest 内容核验 digest。恢复是 preview/confirm：导入历史后创建新 runtime fence，撤销旧 session、grant、lease、job claim 和 bridge ticket。

## 实施补充：提交后写入与 clean clone（2026-09-27）

- CommandDispatcher 在领域 snapshot/event 持久化后，仍在同一事务内保存 `checkpoint.materialize` Job 和 outbox，Job payload 是这一里程碑的白名单快照，不在重试时重新抓取当前状态。
- SQLite commit 返回后才执行 CheckpointWorker；HTTP 返回中的 checkpoint 状态来自对应 Operation 的最新观察。原命令 receipt 保存请求的 Operation ID，重放不另建业务事件。
- 工作进程只领取 checkpoint handler；Job claim/finish/expire 和 Operation 变化使用真实 actor、UTC 毫秒与业务事件同一包络。失败保留 completed，CLI retry 定位原 Operation。
- 项目 JSON/bindings 是可重建投影；daemon 运行期间模块 `_save` 不写文件。启动时优先从 SQLite 恢复项目 ID 与状态，再重建共享文件；共享 project.json 不再带 replica/runtime epoch。
- `project restore --coordination-root <clone> --checkpoint-digest <digest>` 是离线只读预览；追加 `--confirm-plan-digest` 通过现有 U `project.replica.activate` 的离线维护入口确认。不是新的 Agent 权限。
- 此入口只接受未初始化本地数据库且没有 bridge/credential/binding 残留的 clean clone。确认锁定 bootstrap，重新验证 Git anchor、manifest、预览摘要与目标物理身份；暂存完整 SQLite 并原子安装。已有运行库不覆盖，回退/清空另循原 lineage reset 设计。
- 导入保留公共历史的原 actor/时间/序列，恢复动作另追加用户事件。非终态任务 blocked/recovery_review，旧 claimed/running Attempt orphaned，根目录 unbound，历史 Agent retired，Authority unassigned；所有 session/grant/lease/preflight/job claim/ticket 都不导入。
- 未确认 clone 不得自动创建空数据库或生成新的 genesis 覆盖历史。确认后正常启动，再由用户接入/任命主 Agent、绑定根目录并审阅未完成任务。
