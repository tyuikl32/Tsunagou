# 首发授权记录模型

> 核对日期：2026-09-17。
> 状态：第 177 题已确认选项 A；作为 D101 的首发 Grant 存储基线。

## 已确定前提

- 首发只在本机 loopback 运行，session token 只识别 user/control 或具体 Agent HostSession，不承载 role/scope/capability claims。
- 服务端每次根据当前 authority、task owner、授权范围和 project blockers 判断动作。
- 角色只能作为默认能力模板；客户端自报 `role=main` 不能产生权限。
- 同一 OS 用户下 Full Access 恶意进程不在首发防护范围；正式 API/MCP 上的身份混淆、越权和陈旧授权必须被拒绝。
- 权限范围仍需要表达 capability、root/resource selector、subject、task/attempt、authority epoch、状态和可选失效时间。

## 第 177 题：授权记录采用哪种模型

### A（已确认）：单表当前状态 Grant，加领域事件审计

使用一张 `authorization_grants` 表保存权威当前状态：

- `grant_id`、project/lineage/replica；
- subject agent/session，以及可选 task/attempt；
- issuer user/current-main/system 与 `authority_epoch`；
- 固定 capability 集、root/resource scope、policy/ceiling digest；
- `status=active|frozen|revoked|expired`、revision、created/expires/revoked times 和 reason。

签发创建一行；收窄可创建新行并撤销旧行，纯状态收敛直接以 expected revision 更新 status。每次变化仍写不可变领域事件和 audit timeline，但不再为 revocation/supersession 各建一套领域实体或物化投影。

授权判断直接查询当前 active grant，并与 authority epoch、session、task owner、project policy 和 blockers 取交集。handoff 可批量冻结/撤销旧 epoch 行并创建新行；session token 无需重签或携带权限。

优点：表、handler、查询和迁移最少；能满足撤销、交接、任务边界和审计。代价：数据库当前行不是完整不可变账本，历史重建依赖领域事件；未来分布式/远程模式可能需要升级。

### B（已否决）：不可变 Grant + Revocation + Supersession，另建有效权限投影

- 每次签发、撤销、冻结、接管和替代都是不可变记录；后台/事务内投影生成当前有效授权。
- token/grant provenance、因果链和历史重放最强。

优点：审计和复杂交接最严谨，适合未来多机。代价：实体、投影、一致性和迁移显著增加，不符合本机首发的工期目标。

### C（已否决）：只存 Agent role 和 Task owner，不建立 Grant 记录

- `main|worker` role 决定管理能力，TaskAttempt owner 决定执行能力；root scope 直接挂在 Agent/Task 上。

优点：初始表最少。代价：无法可靠表达临时 capability、root 子范围、session/attempt 绑定、冻结/撤销和 authority epoch；角色容易变成隐式扩权，无法满足已有边界。

## 选择 A 时的最小规则

- Grant 是服务端记录，不是 OAuth grant，也不需要 JWT、签名或 refresh token。
- role template 仅在签发时展开为 capability 集；运行时不以 role 名称直接放行。
- 普通 worker grant 不可转授；只有 user/current-main 对应 handler 能签发，且不能超过自身 ceiling/delegable scope。
- 每个写命令同时验证 authenticated agent、session、current grant、task/attempt owner、authority epoch 和 expected revision。
- `frozen` 只允许 D89 明确的安全收敛动作；`revoked|expired` 不允许新业务动作。
- 任何 scope/capability 扩大都创建新 grant 并经过正常授权；不能就地扩大旧行。
- secret token 不存于 grant 表；grant ID 可以进入事件和审计，token hash 留在 credential 表。

## 权威当前表

首发至少使用以下字段；capabilities 和 selectors 采用规范 JSON/JCS digest，具体 schema 在模块计划中展开：

```text
authorization_grants
  grant_id UUIDv7 primary key
  project_id, lineage_id, replica_id
  grant_kind agent_base | main_authority | task_attempt | task_review | handoff_transition
  subject_agent_id, subject_session_id nullable
  task_id nullable, attempt_id nullable
  issuer_kind user | main_agent | system
  issuer_agent_id nullable, authority_epoch
  capabilities_json, resource_scope_json, scope_digest
  policy_revision, ceiling_revision
  status active | frozen | revoked | expired
  revision
  created_at, expires_at nullable, frozen_at nullable, revoked_at nullable
  reason_code nullable, replacement_grant_id nullable
```

索引至少覆盖 `(project_id, subject_agent_id, status, grant_kind)`、`(attempt_id, status)` 和 `(authority_epoch, status)`。数据库约束保证 task-attempt grant 必须绑定 task/attempt，task-review grant 必须绑定被审 task/attempt/review round，main-authority grant 必须绑定 authority epoch。

不同 kind 不做无条件权限并集：management action 必须命中 current epoch 的 `main_authority`；TaskAttempt 写动作必须命中绑定当前 attempt 的 `task_attempt` 且 actor 是 owner；review 必须命中当前 round 的 `task_review`；普通项目读取使用 `agent_base`。所有结果仍受更高层 ceilings/policy/blockers 收窄。

## 第 178 题：Grant 生命周期采用哪种方式（已确认 A）

### A（已确认）：由领域生命周期撤销，默认不定时续期

- `agent_base` 与 HostSession/Agent membership 绑定，detach、session invalidate 或 retire 时同步撤销。
- `main_authority` 与 `authority_epoch` 绑定，handoff/revoke 时同步冻结或撤销。
- `task_attempt` 与 attempt 绑定；attempt 离开允许执行的状态时同步冻结/撤销，恢复或新 attempt 重新签发。
- 普通 grant 默认 `expires_at=null`，不做小时级续期、refresh token 或 grant heartbeat。只有 enrollment ticket 的十分钟有效期、D89 handoff transition 的 120 秒窗口及用户显式临时授权使用期限。
- daemon 启动恢复时扫描“grant active 但其 session/epoch/attempt 已失效”的不变量并收敛；即使扫描尚未完成，授权 handler 的实时关联校验也会拒绝。

优点：最少后台作业和适配器协议；生命周期边界清晰，符合本机可信首发。代价：若某个领域终态 handler 漏掉撤销，需依赖实时关联校验和启动 reconcile 兜底。

### B（已否决）：所有 Grant 固定一小时并由 bridge 定时续期

- grant 到期前由每个 HostSession 心跳刷新；失联自然过期。

优点：遗漏撤销最终会自愈。代价：重新引入续期协议、时钟、离线误过期和后台负载，与取消 refresh 的 D93 方向相悖。

### C（已否决）：Agent/main Grant 生命周期绑定，task grant 使用短 TTL 续期

- 身份和管理授权不续期；运行任务 grant 随 attempt heartbeat 延长。

优点：对失联执行者更快收敛。代价：Lease 已经有 30 秒 heartbeat/120 秒 TTL，重复实现一套相近但不同的定时状态机。

## 后续待细化

- capability 枚举和每个 REST/MCP action 的要求矩阵；
- root/resource selector 的规范 JSON 结构及索引；
- grant 状态转移、批量 handoff SQL 与并发条件；
- 默认期限和 task/attempt 结束时的收敛规则。
