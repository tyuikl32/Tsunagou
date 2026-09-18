# 02 Agent 接入、Authority 与持久消息

## 所有权

本模块证明“谁在调用”，并持有 Agent/Session/Connection、EnrollmentTicket、CapabilitySnapshot、Authority、Message/Delivery/ResponseObligation。projects 判断“可做什么”；厂商 SDK 留在 TS adapter；durability 提供同事务 outbox 和 worker。

## 表与约束

| 表（`agents_` 前缀） | 字段 | 关键约束 |
|---|---|---|
| agents | display_name, adapter_kind, installation_id, conversation_key_digest, status | active conversation 组合唯一；显示名不认证 |
| sessions | agent_id, status, credential_hash, connection_epoch, reconnect_nonce_hash, active_snapshot_id, profile_version, ended_reason? | 一个 Agent 最多一条非 ended；凭据不进入共享 export |
| connections | session_id, epoch, created_at, closed_at?, continuity_digest | `(session_id,epoch)` 唯一；TCP 重连不自行多建业务连接 |
| tickets | kind:worker|main|session_rebind, secret_hash, allowlist, ceiling_digest, installation_binding?, expires_at, consumed_at?, issued_by | 默认 10 分钟、单次消费；main ticket 绑定 expected authority epoch |
| snapshots | session_id, connection_epoch, descriptor/probe/profile versions, host/adapter versions, protocol/bundle, capabilities, config/plugin digests, snapshot_digest, supersedes_id? | 不可变；能力 status supported/unsupported/unknown |
| authority | status, current_main_agent_id?, authority_epoch, revision, transition_id? | 项目 singleton；任命只能 user_control |
| authority_transitions | source/target_agent_id, source/target_epoch, frozen_grant_refs, adopted_refs, started_at, drain_deadline, status | 120 秒是收敛执行窗口，不是用户回复期限 |
| messages | kind, sender_agent_id, subject_ref, summary, payload_json, payload_digest, routing_snapshot_id, in_reply_to? | 内容和收件集合不可变；大正文引用 ArtifactRef |
| routing_snapshots | recipient_ids, capability_snapshot_refs, routing_reason | 发送时固化，不用“当前 main”动态读取 |
| deliveries | message_id, recipient_agent_id, status, lease_owner?, lease_until?, fetched_at?, presented_at?, acknowledged_at?, defer_until?, push_failures | `(message_id,recipient)` 唯一；索引 `(recipient,status,created_at,id)` |
| response_obligations | request_id, recipient_id, requirement:required|optional, status:pending|responded|waived|superseded|expired, deadline_at?, response_id?, superseded_by? | ACK 不更新；required 全部 responded/waived 才满足 |

## 接入与恢复

bridge 自己读取宿主 conversation ID，与 installation_id 归一成服务端 keyed digest。resume/compaction 保持 conversation，fork/clear 新 conversation。无法证明连续性不伪造随机 ID，停在 degraded。

兑换 ticket 的一个 UoW 消费票据、创建 Agent/HostSession/凭据哈希/能力快照、事件与 agent_base。必需能力缺失时票据仍消费，Agent provisioning、Session degraded，仅 bootstrap diagnostics 可用；reprobe 原地修复。malformed/无效票据/conversation 冲突完全回滚。

凭据首次经 bridge 私有交付通道返回，绝不进入模型或普通查询，服务端只持久保存哈希。交付响应丢失时同一 ticket+command_id+nonce 只能取回同一次接入的非秘密 receipt，不能新建 Agent；bridge 未安全保存 token 时通过 session_rebind_ticket 恢复。不要为了重放明文 token 引入加密缓存和密钥生命周期。T02/T06 必须验证 Windows 私有文件 ACL 和无 secret 日志路径。

reconnect 用 session token、可信 continuity evidence、单次 reconnect nonce 与 expected connection_epoch CAS；成功推进 epoch 并更换 nonce，旧连接 commit 前被拒绝。重复同 nonce/command_id返回同一次连接结果，其他并发方失败。没有应用 heartbeat 不标 ended；显式 SessionEnd/rebind 才关闭身份。执行 Lease 的超时是独立机制。

## 主 Agent 与继任

任命前 ready、共同基线通过、ceiling 不扩大。handoff 仅按 policy 当前 main 发起；开始后冻结旧可执行授权，创建 transition grants 允许 stop/report/release，拒绝新 claim。目标采用明确对象，不自动继承旧 Grant。超 120 秒进入需要处置的残余风险状态，不自动选择新的主 Agent或伪造已停止。

Agent succession 总是新 Agent/新 Attempt；不能改旧 Attempt.owner。pending response/contract obligations 以 superseded 关联新项，保留原始 deadline；契约参与者变更生成新 proposal digest，并重新收集必需接受。只有消息原收件人可读历史正文；转交摘要是另一个经授权的新消息。

## 消息状态和投递

Delivery 状态为 `pending,leased,fetched,presented,acknowledged,deferred,expired,dead_letter`。pull claim 默认最多 10、最大 20，合计正文 ≤1 MiB；每 recipient 最多 20 outstanding；投递 lease 60 秒、每 15 秒 renew，单次占用最多 2 分钟。租约只防重复派发，不等于业务处理成功。fetch 后正文不再自动重复注入，未响应提醒仍保留。

ACK 允许 fetched/presented→acknowledged，幂等；lease 过期未 fetch 回 pending，fetched 后遗失 ACK 则返回待确认项和 ID，不能捏造未读。defer_until 是基础设施调度时间；request deadline 只有发送者明确设置才有。

优先级 `low,normal,high,critical`，每等待 5 分钟提升一级，最多 high；critical 仅显式授权的紧急消息。相同优先级按 created_at/id 公平排序。不因重试次数到达阈值自动 dead_letter；明确不可投递（收件人 retired 且无合法转交等）才建立诊断状态。push 连败 5 次抑制 5 分钟，pull 永远可用。无 wake 的 adapter 不承诺外部自动重启对话。

## 公开端口、事件和验收

`authenticate` 返回可信 PrincipalContext；`get_session_capabilities` 返回指定不可变快照；`stage_message`、`supersede_obligations` 参与调用者 UoW；`query_inbox/query_agent/query_authority` 只返回被授权字段。

事件包括 agent_enrolled、session_ready/degraded/ended、connection_resumed、capability_snapshot_created、authority_changed、message_created、delivery_fetched/acknowledged、response_obligation_resolved。消息事件公开投影只含可见元信息，不能泄露非收件正文。

测试：双兑换只有一次；token 不出现在 JSON日志/schema fixtures；重连后旧请求不能 commit；主 Agent不能读别人 inbox；重复 fetch/ACK/response 无重复副作用；无呈现证据不标 presented；succession 不私自复制身份或契约接受。实施 T06/T07/T15/T17–T21。
