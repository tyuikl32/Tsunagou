# 规范术语、字段与数据模型

## 通用值与持久约定

| 类型 | 唯一含义与约束 |
|---|---|
| `Id` | 小写 UUIDv7 文本；不能从时间部分推导权限或父子关系 |
| `Digest` | `sha256:` + 64 位小写十六进制；结构对象先 RFC 8785 JCS 再 UTF-8 SHA256，blob 直接对原始字节哈希 |
| `Revision` / 数字 epoch | JSON 安全非负整数，最大 9007199254740991；revision 创建为 1，每次成功聚合变更 +1 |
| `runtime_epoch` | UUIDv7，区别于数字 authority/connection/execution epoch |
| `Timestamp` | UTC，精确到毫秒，`YYYY-MM-DDTHH:mm:ss.sssZ`；服务端记录事实时间，客户端时间只是 evidence |
| `EntityRef` | `{kind,id,revision?,digest?}`；证据要求精确版本时 revision/digest 必填，禁止“最新版本”别名 |
| `PathRule` | `{root_id,access:read\|write,path_prefix:string[]}`；write 含 read；`[]` 前缀覆盖整个 root；规则列表为空则无文件权限 |
| `ResourceKey` | path `{kind:path,root_id,segments}` 或 named `{kind:named,namespace,name}`，不支持 glob/正则/否定 |
| `EvidenceRef` | `{kind:entity\|artifact\|external,ref,digest?,summary?}`；外部 URI 为证据引用，服务器不自动访问 |

每个领域行至少含 `id,project_id,lineage_id,created_at`。可变 aggregate 加 `revision,updated_at`；不可变 record 无通用 PATCH。业务 FK 使用 `(project_id,lineage_id,id)`，即便 UUID 全局随机也不省略边界校验。所有引用都校验属于同项目/允许 lineage；跨 lineage 只有明确的历史 provenance 引用。

SQL TEXT 存 ID、UTC 时间和 canonical JSON；INTEGER 存 revision/epoch/count；boolean 是 CHECK 0/1。枚举有 CHECK。金额和比例不用不受限浮点参与哈希；必要小数以 schema 限定字符串。payload object 禁未知字段，扩展放显式版本化子对象。不可变记录靠 repository API 和约束保障，不支持后台“修正历史”。

## 身份层次

| 术语 | 含义 | 何时变化 |
|---|---|---|
| Project | 用户眼中的协作项目 | 只有另建独立项目才变；首发无 fork 产品功能 |
| Lineage | 允许继续追加的历史分支 | 回退旧 checkpoint、清空协作重开时新建；旧分支 sealed |
| Replica | 此 clone 在该 lineage 的本机实例 | clone 或 lineage 切换新建 |
| Runtime | 本次活动运行授权代次 | 激活切换、恢复/重激活需要 fencing 时新建；普通 HTTP reconnect 不改变 |
| Agent | 某宿主对话在项目中的工作身份 | 新对话/fork 新 Agent；明确 rebind 保持 Agent |
| Installation | adapter 本机安装档案 | 重装/明确重置改变，不能每次启动随机换 |
| HostSession | Agent 当前唯一有效接入会话 | rebind 更换；普通重连保留 |
| Connection | bridge 的逻辑连接代次 | 同一 HostSession 恢复时 CAS 增 connection_epoch；不是 TCP socket |
| Authority | 唯一 current main 身份和数字代次 | 任命、撤销、handoff 推进 authority_epoch |
| TaskAttempt | 一次任务所有权与执行 | 换 owner/返工/继任新建；挂起恢复可保留 |

## 权威状态枚举

| 对象 | 状态 |
|---|---|
| Project.lifecycle | `active,completed,archived`；长流程用 Operation，不加 completing |
| Authority.status | `unassigned,stable,transitioning` |
| Replica.role | `active_writer,standby,takeover_required` |
| Lineage.status | `open,sealed` |
| Agent.status | `provisioning,active,retired`；能力 degraded 表达在 HostSession |
| HostSession.status | `probing,degraded,ready,disconnected,ended`；断网观察不代表 ended |
| Task.status | `draft,ready,open,claimed,running,blocked,submitted,changes_requested,cancel_requested,orphaned,completed,failed,cancelled` |
| Attempt.status | `claimed,running,blocked,submitted,cancel_requested,orphaned,closed`；closed 带 close_reason，不复活 |
| Discrepancy.status | `open,clarifying,negotiating,resolved,dismissed,overridden` |
| ContractProposal.status | `proposed,accepted,rejected,superseded,withdrawn`；payload 与 participants 不改写 |
| Lease.status | `active,released,expired` |
| Workspace.status | `requested,preparing,ready,in_use,result_recorded,cleanup_pending,cleaned,failed` |
| Operation.status | `pending,running,retry_wait,cancel_requested,succeeded,failed,cancelled,outcome_unknown` |
| Job.status | `queued,running,retry_wait,succeeded,failed,cancelled` |
| UserDecision.status | `pending,approved,rejected,superseded,cancelled`；无超时状态 |
| Grant.status | `active,frozen,revoked`；替换而非扩大旧 Grant |

Task completed 是具体任务验收通过；Project completed 是用户确认整体目标完成。Message acknowledged、Contract accepted、Task accepted、UserDecision approved 都是不同事实。

Attempt 身份、owner、创建输入不可变，status/revision 是事件支持的当前投影。Task.current_attempt_id 允许 null；恢复 checkpoint 的非终态任务 blocked/recovery_review，但没有当前 Attempt。查询必须表达此情况，不能捏造 owner。

## 跨模块关系

- Project → RootRegistration / RepositoryRegistration / Grant / UserDecision 由 projects 管。
- Agent → HostSession → Connection / CapabilitySnapshot；Agent → Delivery，Authority → Agent，由 agents 管。
- Task → TaskAttempt → TaskResult / ReviewRound，由 tasks 管；parent_task_id 是委派导航，`blocks` 是显式依赖，两者不互推。
- Report/Discrepancy/Contract 引用 task/attempt/participants；cognition 不持有任务状态。
- ResourceIntent 和 Lease 引用 attempt/effective_scope_digest；resources 不持有 workspace 生命周期。
- IsolationDecision / Workspace 引用 task attempt、driver、roots/repos；GitActionRequest 由 workspaces 发出，main 提交 evidence。
- Event/Outbox/Operation/Job/Checkpoint/ArtifactBlob 由 durability 管；ArtifactRef 和读取规则由引用它的领域管理。

## 状态观察与阻塞

Condition：`{type,status:true|false|unknown,reason_code,severity,scope,observed_revisions,input_digest,observed_at,last_transition_at,stale_after?,producer,evidence_refs[]}`。它是观察，不直接代表授权。

Blocker：`{id,code,source_ref,scope,affected_actions[],observed_revisions,policy_digest,since,remediation_code,required_actor,retryable}`。命令逐项计算实际适用 blocker；一个 root 出错不冻结无关任务。可派生 operability/health 摘要，但它们不是写入判断依据。

Grant、ContractAcceptance、TaskResult、RiskSubmission、OperationResolution 都记录真实 actor 与精确输入 digest。普通查询永不返回 token/ticket/secret。recipient-only 消息不能经黑板/审计/附件间接泄露。
