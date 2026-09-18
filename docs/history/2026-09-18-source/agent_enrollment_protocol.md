# Agent Enrollment 与 Attach 协议

> 核对日期：2026-09-17。
> 状态：第 198 题已确认选项 A；作为 D122 的 enrollment 原子边界。

## 已确定前提

- enrollment ticket 是服务端生成的 256-bit opaque random token，默认十分钟、单次兑换，只存 hash，不进入 Git/prompt/log。
- user/control 始终可签发；current main 只有 `agent.enroll` 且不超过自身 ceiling 时可签发 worker ticket。
- worker ticket 不能任命主 Agent；D91 的 `main_agent_enrollment_ticket` 是不同 kind 和 handler。
- attach 必须提交统一 `adapter_installation_id` 和 `host_conversation_id`，并完成协议/能力探测。
- 首发没有 OAuth、JWT、refresh token 或远程账号体系。

## 第 198 题：Ticket 兑换与 Agent/Session 创建采用哪种边界

### A（已确认）：一次性兑换先原子创建 provisioning 身份，再按 probe 激活

- worker ticket 默认不要求签发者预先知道 conversation ID；ticket 固定 project/lineage、adapter/host kind allowlist、权限上限、expiry 和可选 installation binding。
- bridge 用 ticket、installation ID、conversation ID、协议协商和首轮 probe payload 调用单一 `RedeemEnrollmentTicket`。
- 一个 UoW 验证并消费 ticket，检查 `(installation, conversation)` 未绑定其他 active Agent，创建 `Agent(status=provisioning)`、`HostSession(status=probing|degraded|ready)`、credential/hash、CapabilitySnapshot 和事件/outbox。
- baseline 通过时同事务把 Agent/HostSession 置 active/ready 并签发 agent_base；baseline 缺失时 ticket 仍已消费，保留 provisioning/degraded 的 diagnostic-only 对象，修复后 D117 原地 reprobe 激活。
- malformed schema、ticket 无效/过期、adapter/host kind 不匹配或 conversation 已冲突时整个事务失败且不创建对象；是否消费无效票据不向调用方泄露区别。相同 command ID/hash 幂等返回同一结果。
- main-agent ticket 还必须绑定用户批准的 main ceiling/template 与 expected authority epoch；同一事务完成 attach/probe/ready 后才执行 D91 appoint。probe degraded 时不任命，ticket 已消费并要求用户修复或另行任命。

优点：ticket 只消费一次，失败诊断对象可原地修复；不会出现 active Agent没有可用会话，也无需签发前知道宿主 conversation ID。代价：增加 `provisioning` Agent 状态和 attach 组合事务。

### B（已否决）：Probe 全部通过后才创建任何 Agent/HostSession

- ticket 在外部 probe 期间保持未消费；全部通过后一个事务创建 active Agent/session/grant。

优点：数据库没有 provisioning/degraded 身份。代价：probe 重试期间 ticket 可被并发兑换，需要 reservation 状态；失败诊断和证据无法自然归属，最终仍会引入临时对象。

### C（已否决）：兑换立即创建 active Agent，Probe 失败再降级

- ticket 验证后先签发 agent_base 并开放项目，异步 probe 再决定是否撤销。

优点：接入最快。代价：存在尚未证明身份隔离和共同能力却能读取/操作项目的窗口，违反 D117。

## 组合请求的必要字段

```text
RedeemEnrollmentTicketRequest
  command_id
  ticket (Authorization-style secret channel, never body/log if avoidable)
  adapter_installation_id
  host_conversation_id
  adapter_kind/version, host_kind/version
  project_id, replica_id, runtime_epoch
  supported_protocol_versions, schema_bundle_digest
  baseline_profile_version
  probe_suite_version, probe_results[]
  client_nonce
```

ticket 本身是本地短期 secret，可使用专用 header；不得与 session token 混用。响应只在首次安全交付通道返回 session token，普通 JSON 查询不再显示。

## 后续待细化

- provisioning/degraded/active/retired Agent 与 probing/degraded/ready/ended Session 的状态图；
- worker/main ticket schema、签发 API 和 secret CLI 展示；
- ticket hash、nonce、idempotency 和并发兑换 SQL；
- attach 响应中 session token 的一次性安全交付与 bridge 私有存储。

## 第 199 题：一个 Agent 可以有多少个非终态 HostSession（已确认 A）

### A（已确认）：严格一个；恢复复用，丢失凭据时显式替换

- 一个 active/provisioning Agent 最多一个 `probing|degraded|ready|disconnected` HostSession；普通 reconnect 只按 D112 恢复该行并新建 Connection。
- 同一 `(installation, conversation)` 使用普通 enrollment ticket 再次兑换时返回 `conversation_already_enrolled` 和有限修复信息，不创建第二 Agent/session。
- session token/adapter 私有数据丢失但宿主 conversation ID 仍可验证时，user/control 或 current main 可签发专用 `session_rebind_ticket`；一个 UoW 撤销旧 credential/session grants、终止旧 HostSession并为同一 agent_id 创建 replacement HostSession/token。
- rebind 不恢复旧 Connection/Lease，不改变历史消息/契约/attempt 作者。running attempt 必须按 orphan/recovery 规则显式处理；current main 的新 management grant 仍需验证 authority epoch 与 replacement session。
- adapter installation ID 已改变时，不允许 rebind 为同一 Agent，因为统一 identity key 的作用域已变；创建新 Agent并走继任。

优点：Agent 与宿主对话保持一对一，授权/消息/任务 owner 不会被两个 session并发代表；仍有明确的凭据恢复路径。代价：多组件必须共享同一 bridge Connection，不能各建 HostSession。

### B（已否决）：同一 Agent允许多个并行 HostSession

- 相同 conversation ID 可在多个 installation/bridge session 下同时代表一个 agent_id，各自持有 token/grant/inbox connection。

优点：支持多个插件组件或设备。代价：消息处理、Lease、能力快照和命令身份出现多个权威来源，与单 Connection fencing 失配。

### C（已否决）：每个 HostSession 永远创建新 Agent

- 即使 conversation ID 相同，凭据丢失或重新 enrollment 都产生新 agent_id，再通过继任迁移。

优点：恢复实现最少。代价：正常凭据丢失会制造身份碎片、任务交接和历史噪声，也浪费已验证的 conversation continuity。
