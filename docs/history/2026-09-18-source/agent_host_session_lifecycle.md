# Agent、HostSession 与 Connection 生命周期

> 核对日期：2026-09-17。
> 状态：第 188 题已确认选项 A；作为 D112 的会话恢复基线。

## 已确认前提

- `agent_id` 是项目内成员身份，绑定具体宿主对话上下文；同厂商多个对话是不同 Agent。
- 只有宿主可验证的原会话 resume/compact 可以延续身份。new/clear/fork 创建新 Agent，fork 只保留 provenance。
- 每个 HostSession 有独立 opaque token；token 只识别主体，不承载 role/capability/scope。
- 四种适配器必须支持 attach 现有会话；managed launch 只是增强能力。

## 三层对象

### Agent

项目周期内的逻辑成员：

- `agent_id`、project/lineage、adapter kind、display metadata；
- `status=active|retired|removed`；
- host conversation ID keyed digest、fork/successor provenance；
- 不保存可使用的 session secret。

Agent 的历史消息作者、契约接受者和 TaskAttempt owner 不因重连或继任而改写。根据 D130，`retired` 可在原 installation/conversation 连续性重新验证后恢复同一 `agent_id`；退休时旧 HostSession、credential 和 grants 仍已失效，不能直接恢复。

恢复必须通过显式 `ReactivateAgent`：user/control 可批准，current main仅在持有 `agent.reactivate` 且 policy/ceiling 允许时批准。恢复创建全新 HostSession、credential、CapabilitySnapshot 和 `agent_base`，不会恢复任何旧 authority、attempt、lease、obligation、contract position 或 approval。

### HostSession

一次“某宿主安装实例中的某个对话附着到某个 project runtime”的持续关系：

- `host_session_id`、agent/project/lineage/replica/runtime epoch；
- adapter/host kind/version、adapter installation ID、host conversation ID keyed digest；
- negotiated protocol/schema bundle、capability snapshot；
- `status=attached|disconnected|ended|revoked`、revision、时间戳；
- credential ID/hash 引用，不含明文 token。

### Connection

一次短暂 REST/SSE/bridge 在线连接：

- `connection_id`、host session、connection epoch、transport kind；
- connected/last-seen/disconnected times、disconnect reason；
- 不作为领域身份，也不进入共享 Git checkpoint。

## 第 188 题：Bridge 断线或重启如何恢复

### A（已确认）：证据匹配时恢复同一 HostSession，仅新建 Connection

- 网络抖动、SSE 重连、bridge 进程重启或 daemon 正常重启，不自动创建新 Agent/HostSession。
- bridge 提交原 session token、adapter installation ID、统一 `host_conversation_id`、project/replica/runtime epoch 和协议摘要；服务端逐项匹配 active/disconnected HostSession。
- 匹配成功后递增 `connection_epoch`、关闭旧 connection（若仍残留）并创建新 Connection；Agent、HostSession、base grant 和 inbox cursor 保持稳定。
- token 单独不足以证明宿主对话连续性。conversation ID 不匹配、new/clear/fork、runtime/lineage 改变、session ended/revoked 或无法提供稳定 ID 时拒绝 resume，要求新 enrollment/attach。
- compact/resume 必须保持相同 conversation ID；更新 capability snapshot 不能静默扩大授权。

优点：短暂断线不制造身份和授权 churn，同时新对话不能拿旧 token 接管；与四 adapter 的正式恢复要求一致。代价：每个 adapter 必须实现 conversation evidence extractor 和匹配测试。

### B（已否决）：每个 Bridge 进程都创建新 HostSession，但可复用 Agent

- bridge 重启使用 enrollment/reconnect 流程创建新 HostSession/token；宿主证据匹配时仍绑定旧 agent_id。

优点：HostSession 生命周期和进程一致，状态较直观。代价：bridge/daemon 更新会频繁撤销 base grant、重建 token 和投递游标；与宿主对话持续性混淆。

### C（已否决）：持有原 Session Token 即恢复，不检查宿主证据

- 只要 token/status 有效，就可以建立新 Connection；conversation/session ID 仅记录日志。

优点：实现最少。代价：新建或 fork 的对话只要取得旧 token 就能接管旧 Agent和任务，违反 D16 与身份隔离共同基线。

## 选择 A 时的恢复请求

```text
ResumeHostSessionRequest
  host_session_id
  token (Authorization header only)
  adapter_installation_id
  host_kind, host_version
  host_conversation_id
  lifecycle_source startup | resume | compact
  project_id, replica_id, runtime_epoch
  supported_protocols, schema_bundle_digest
  probed_capabilities_digest
  reconnect_nonce
```

服务端以 `(adapter_installation_id, host_kind, host_conversation_id)` 的精确匹配为连续性规则，`lifecycle_source` 只作诊断。原始 ID 经 keyed digest 后保存；transcript、会话正文和宿主 secret 不存储。adapter 必须通过生命周期 conformance 证明 resume/compact 保持 ID，而 new/clear/fork 改变 ID。

## 恢复后的不变量

- 一个 HostSession 任一时刻最多一个 current connection epoch；旧 Connection 的 renew、ACK 或 command 因 epoch 不匹配被拒绝。
- 恢复不会自动恢复 expired Lease；运行 Attempt 仍按 lease/session 连续性规则判断能否恢复或进入 orphaned。
- 若 adapter capability 下降，HostSession 可恢复，但相关 actions/attempts 进入 blocker 或要求重新 preflight；能力上升不自动扩大现有 grant。
- inbox 以持久 entry/fetched/ACK 状态继续，不按 connection 复制消息；新 Connection 可继续拉取未完成投递。
- main-authority 是否仍有效由 current authority epoch 决定，不因 HostSession 恢复而恢复旧管理权。

## 后续待细化

- Codex、OpenCode、ZCode、DeepSeek Harness 各自 conversation evidence 字段和 verifier；
- disconnected/ended 的触发来源与离线窗口；
- concurrent reconnect 的 connection fencing 规则；
- bridge 私有 token 文件的定位、权限和清理。

## 第 189 题：并发重连如何裁决（已确认 A）

### A（已确认）：每个 HostSession 单一当前 Connection，新连接以 CAS 取代旧连接

- resume/attach 请求携带 `expected_connection_epoch` 与随机 reconnect nonce；事务比较当前 HostSession revision/epoch，成功后递增 epoch、把旧 Connection 标记 `superseded` 并创建新 current Connection。
- 新 epoch 提交后，旧 Connection 的 command、Lease renew、inbox lease/fetch/ACK 和 capability report 全部返回 `stale_connection`；已进入 UoW 的命令在提交前再次核验 epoch。
- SSE 可以有同一 current Connection 下的 control/inbox topics 或重建流，但不能形成第二个独立 command authority。
- 相同 reconnect nonce/request hash 幂等返回同一 Connection；两个并发重连只有一个 CAS 成功，失败方读取新 epoch 后可判断自己是否应停止或重新发起。

优点：崩溃重启能立即接管，旧 bridge 被确定性 fencing；不需要等待超时。代价：错误重复启动会让两个 bridge 相互抢占，适配器需检测 `stale_connection` 并退出旧实例。

### B（已否决）：当前 Connection 心跳健康时拒绝新连接

- 只有旧 Connection 显式关闭或超过 offline timeout，resume 才允许；不做立即 supersede。

优点：防止重复实例抢占。代价：旧 bridge 崩溃后必须等待超时，阻塞 inbox、任务和主 Agent响应；需要人工 force takeover 路径。

### C（已否决）：允许同一 HostSession 多个并发 Connection

- 多个 bridge 可同时使用同一 token/session，每个有自己的 SSE 和 delivery lease。

优点：支持多组件并行，重连无 fencing。代价：同一 Agent可能重复处理消息、续租和提交命令，无法满足会话身份隔离与唯一 delivery owner。

## 第 190 题：在线状态与断线超时如何处理（已确认 C）

### A（已否决）：独立 Presence 心跳，只改变在线状态，不撤销身份授权

- current bridge 每 15 秒发送轻量 `ConnectionHeartbeat`；任一成功的认证请求也更新 `last_seen_at`，但不能替代长期空闲时的后台 heartbeat。
- 连续 45 秒没有 heartbeat/traffic 时，Connection 标记 `disconnected`，HostSession 派生为 offline；这是 presence 状态，不把 HostSession 置为 ended，也不撤销 agent_base/main_authority。
- offline 只影响主动推送、候选在线提示和运维 condition。主 Agent离线不会自动撤销、换届或选主；它仍按 D19/D92 等待用户动作。
- TaskAttempt 的执行存活由独立 Lease heartbeat/120 秒 TTL 决定；Connection offline 本身不立即 orphan task，避免短暂网络抖动重复状态迁移。
- 收到宿主明确 session ended/clear、新 lineage/runtime、用户 detach/revoke 或 adapter uninstall 证据时，才把 HostSession 置 `ended|revoked` 并同步撤销 credential/base grant。

优点：在线展示及时，又不把网络可达性误当授权生命周期；与 Lease 和 authority 已有语义分工明确。代价：离线 HostSession 的 base grant 会继续存在，但没有匹配的 current connection 无法正常使用，且每次授权仍复核 session 状态。

### B（已否决）：45 秒离线即结束 HostSession并撤销全部 Grant

- heartbeat 超时等同 session ended；重连必须重新 enrollment/attach。

优点：陈旧授权收敛最快。代价：短暂休眠、IDE 更新或 daemon 重启都会使身份反复接入，主 Agent和正在工作的 Agent容易被误撤销。

### C（已确认）：不做后台 Heartbeat，只依赖请求活动和宿主 lifecycle event

- 首发没有 `ConnectionHeartbeat` command、客户端定时器或固定 offline timeout。
- 成功认证请求和 SSE 建连更新 `last_seen_at`；明确 transport close/send failure 可把 Connection 标记 disconnected。没有当前证据时 HostSession presence 返回 `unknown`，而不是长期显示 online 或凭静默推断 offline。
- 服务端现有 SSE comment ping/send timeout 只维护流和发现明确 transport failure，不升级为 Agent application heartbeat，也不证明模型可见或业务处理。
- presence 不撤销身份、grant 或 main authority。TaskAttempt/资源继续使用独立 Lease heartbeat/TTL；宿主明确 end/clear/detach 等 evidence 另走会话终止命令。

优点：协议和后台定时器最少。代价：空闲但在线与已经崩溃经常只能显示 unknown，不能依据 presence 自动做调度或换届。

## 第 191 题：明确的宿主 end/clear 事件如何收敛（已确认 A）

### A（已确认）：立即终止 HostSession 和逻辑授权，运行 Attempt 进入 orphaned

- 当前 Connection 提交经过 adapter verifier 的 `HostSessionEnded(reason=end|clear|detach|uninstall, evidence_digest)`；user/control 也可 detach/revoke，不需要 Agent接受。
- 同一 UoW 把 HostSession/Connection 置终态，撤销 credential、agent_base、该 session 的未开始 grants/inbox leases，并记录领域事件/outbox。
- 该 Agent拥有的 running TaskAttempts 立即进入 `orphaned`，使 execution epoch/grant 失效并停止新协调写入；不声称 Full Access 外部进程已停止，保留 residual-risk/reconcile 提示。
- 如果该 Agent是 current main，项目不自动选主，也不把历史 authority 改给别人；保留 current-main identity 并增加 `main_agent_unavailable` condition/blocker，等待 user revoke/handoff/新身份继任。
- `clear` 后的新宿主对话必须新 enrollment/Agent；不能撤销 end 再恢复旧 HostSession。

优点：明确生命周期证据立即生效，不等待不存在的 presence timeout；旧上下文无法继续代表 Agent。代价：宿主误报 end/clear 会中断任务，只能按继任/新 attempt 恢复。

### B（已否决）：只标记 disconnected，等待 Lease 和用户处理

- end/clear 与普通 transport 断线同等处理；token/grant 仍可恢复，running attempt 等 Lease 超时。

优点：对宿主误报更宽容。代价：已明确销毁的对话仍可凭旧 token恢复，违反 D16；任务和管理权收敛较慢。

### C（已否决）：先生成请求，等待用户确认终止

- end/clear 只创建高优先级通知；用户确认后才撤销 session/grants。

优点：避免误报直接中断。代价：用户不响应时旧会话长期有效，并增加审批状态；不符合宿主可验证 lifecycle evidence 的意义。
