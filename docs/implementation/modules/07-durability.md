# 07 持久化、Operation、checkpoint 与附件

## 真相与事务

SQLite 是当前 runtime 的领域真相；事件同事务追加，不采用从事件重建一切的完整 Event Sourcing。checkpoint 是版本化的共享快照与必要历史；Git 是由 main 管理的持久载体，不是业务数据库。

durability 拥有数据库 bootstrap/UoW 接口、事件序列、outbox、幂等、Job/Operation、checkpoint、blob 与 migration/backup 机制；不得拥有其他模块的业务 repository。跨模块导出通过各自 `export_checkpoint(read,profile)`，导入通过所有者的校验/导入端口。

## 表

| 表（`durability_`） | 字段与约束 |
|---|---|
| events | event_seq,event_id,type,schema_version,aggregate_ref,actor_ref,command_id,occurred_at,payload,digest；`(lineage,event_seq)` 唯一，只追加 |
| commands | principal_id,command_kind,command_id,input_hash,result_json,event_seq；四元组（含 project）唯一，秘密交付结果除外 |
| outbox | event_seq,kind,target_ref,payload_digest,status:pending|running|done|failed,attempt_count,next_attempt_at；去重 kind/target/event |
| operations | kind,requested_by,input_digest,status,result_ref?,error?,cancel_requested_at?,revision；展示逻辑工作 |
| resolutions | operation_id,actor,conclusion:verified_succeeded|verified_failed|risk_accepted|retry_authorized,evidence_refs,reason,followup_operation_id?,digest；只追加 |
| jobs | operation_id,handler_kind,payload_ref,input_digest,status,available_at,attempt_count,max_attempts,timeout_seconds,lease_owner?,lease_epoch,lease_until? |
| job_attempts | job_id,attempt_no,lease_epoch,worker_id,started_at,finished_at?,outcome,external_effect_ref?,error_code?；不可改历史归属 |
| checkpoints | digest,parent_digest?,lineage_id,through_event_seq,format_version,schema_bundle_digest,manifest_ref,status:staging|sealed|failed,reason |
| materializations | generation_id,through_event_seq,staging_path,manifest_digest,status,operation_id；恢复能定位崩溃窗口 |
| artifact_blobs | digest,size_bytes,media_type,storage_state:local|promoted,local_relative_path,verified_at；digest 唯一 |
| artifact_uploads | intent_id,domain_ref,actor,size_limit,expected_digest?,received_bytes,status:pending|uploaded|finalized|expired,expires_at,temp_path |
| anchor_observations | checkpoint_digest,repository_id,ref_name,commit_oid,verified_at,tree_digest,status；仅本机 heads/tags |

## Job 与未知结果

默认 4 workers、每秒扫描；job lease 60 秒、每 15 秒 renew；最多 5 attempts，可配上限 10。单次默认 timeout 120 秒，范围 5 秒～10 分钟；指数 full jitter 1～60 秒，Retry-After最多15分钟。退出给予15秒收敛，未完成由恢复接管。

Job handler 分类必须声明 `effect_kind:pure|idempotent|reconcilable|unverifiable`。纯/幂等可原 command input重试；外部 ambiguous 先 reconcile；不可证明是否执行则 Operation outcome_unknown，不能因超时直接失败并重做。调用前持久 intent，调用后持久 result，中途崩溃由 effect receipt/key核验。

Operation outcome_unknown 是历史终态。main 在其可授权范围内追加 OperationResolution，有证据可给 verified 结论，或创建新 Operation授权重试；user-only 动作仍需用户。risk_accepted 表示承认风险，effective_outcome 仍不能显示 succeeded。API 同时返回 original status、latest_resolution、effective_outcome。

## Outbox 与文件物化

1. 写事务提交领域状态、event、outbox、必要 Operation/Job。
2. worker 从稳定读 snapshot 导出各模块数据到同卷 staging，计算 manifest/条目 digests，flush/fsync。
3. 将不可变 checkpoint directory rename 到 digest目标，最后以 replace切换小型 manifest/pointer；重启扫描 staging和既有digest，校验后幂等继续。
4. 成功另一个事务推进 materialization watermark，标 sealed；失败保留可诊断状态，不回滚原业务事实。

Windows 使用同卷 atomic replace 和文件关闭后重试，不能假设 Unix rename 可覆盖打开文件；T04/T14 用实际崩溃注入验证。不能在 SQLite事务里跨文件“假装原子”。

outbox软阈值默认10,000条或最老未物化5分钟告警；硬阈值100,000条阻塞新增领域写。repair、读取、撤权及已有outbox drain保留。阈值是工程默认，可配置，不以积压时间把用户任务判失败。

## checkpoint export profile

共享：Project/roots逻辑描述、policy非秘密部分、Task/Result历史、认知/契约、历史Agent作者、领域event、operation结论及显式promote的project_shared artifacts。排除可用credential/ticket/Grant/Lease/job claims、本机绝对路径、私信正文、用户ceiling秘密和未授权附件。

manifest含 `project_id,lineage_id,parent_digest,through_event_seq,shared_format_version,schema_bundle_digest,files[{path,size,digest}],artifact_digests[]`；文件路径必须相对且无逃逸；digest依规范顺序计算，manifest自身digest不参与自身哈希。每领域NDJSON按规范ID排序，事件按seq排序，UTF-8+LF、末尾换行。首次genesis parent=null。

归档、lineage切换、replica激活用 materialization barrier；用户确认完成例外：Project立刻completed，强制completion checkpoint异步。失败仅阻塞依赖该证据的后续动作，不撤销用户结论。

## Git 锚点、clone 与恢复

只读扫描同repository `refs/heads/*` 与 `refs/tags/*` 可达commit，验证 checkpoint完整目录及manifest字节。HEAD只是候选，remote refs/reflog/unreachable object均不算。观察结果有时间/输入digest；Git refs变化后重验。

unanchored项目仍能协作、完成、形成local archive。replica切换/接管按恢复性要求核验证据；最后副本删除必须另有可恢复副本或明确用户数据丢失批准。本机anchor不证明远端发布。

同lineage分叉三方比较以共同祖先checkpoint为基线：只自动合并不同实体的独立改动；同实体冲突由main提出具体选择，身份/ceiling冲突user。sealed lineage不合并；独立fork延后。

回退/清空：封存旧lineage→创建新lineage/genesis→新replica/runtime→重建SQLite→Authority unassigned，所有运行凭据/Grant/Lease/worker claims失效。非终态Task恢复blocked/recovery_review且无current Attempt；终态保留。用户重新接入/任命后main显式restore_open。

## 附件、保留与迁移

默认blob本机内容寻址，finalize验证大小+摘要，ArtifactRef/权限由领域拥有。promote只允许current main/user，且引用领域已允许project_shared；recipient-only附件禁止仅凭hash提升。首发不自动GC finalized blobs；临时上传可清理。普通运行细节可在checkpoint覆盖后保留30天；领域事件、决策、幂等与blob不沿用此过期规则。

单线Alembic迁移，项目lock下备份SQLite及版本元信息、预检可用空间，失败保持旧库/只读诊断；不自动执行downgrade。修复和恢复须验证digest、foreign keys、schema、lineage以及业务不变量，不能只检文件存在。

## 端口与验收

`append_events`、`enqueue_job`、`stage_outbox`只在UoW内；`read_snapshot`提供一致读；`request_checkpoint`返回Operation；`verify_artifact_access`必须调用所属领域query。事件operation_changed、operation_resolved、checkpoint_sealed、materialization_failed、artifact_finalized/promoted。

必须覆盖 commit前/后、external effect前/后、rename前/后崩溃；恢复无漏event/重复副作用；未来format只读；篡改manifest拒绝；秘密不入Git；未知结果不自动重试；completion checkpoint失败不回滚completed。实施T04/T12/T14/T15。
