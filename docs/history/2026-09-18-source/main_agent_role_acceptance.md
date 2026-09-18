# 主 Agent 单阶段任命协议

> 核对日期：2026-09-17。
> 状态：第 169 题已确认选项 C；作为 D92 的单阶段任命基线。

## 决策

主 Agent 的初次任命、计划性交接和撤销均为单阶段命令。不存在候选 acceptance、appointment proposal、provisional authority、接受超时或候选拒绝状态。

- 用户提交 `AppointMainAgent` 后，事务提交即产生新的 current main 和 `authority_epoch`。
- 合法主体提交 `HandoffMainAgent` 后，事务提交即完成 authority 切换；候选不需要另行接受。
- 用户提交 `RevokeMainAgent` 后，事务提交即撤销当前主 Agent；可以暂时进入 `unassigned`。
- 任命或交接通知通过持久 inbox/outbox 投递。`fetched`、`presented` 和 ACK 只表示交付进度，不控制权限是否生效。
- 通知失败、候选未读或候选随后离线不回滚 authority，也不自动选择其他 Agent。用户通过新的 revoke、appoint 或 handoff 命令纠正。

## 提交前校验

`AppointMainAgent` 与 `HandoffMainAgent` 在写事务前必须校验：

- candidate agent 属于当前 project、lineage 和 writer replica，且未 retired；
- candidate session 与 host identity 仍有效，adapter capability snapshot 满足主 Agent最低能力；
- 请求的 capabilities、root scopes 和 grant template 不超过用户 ceiling、主 Agent可委派范围及当前 project policy；
- `expected_project_revision` 和 `expected_authority_epoch` 与当前值一致；
- candidate 不是由名称、role 自报、连接先后、Full Access 或宿主类型隐式推断出来的；
- 对接入并任命流程，专用 ticket 的 candidate binding、nonce、expiry 和 `appoint_on_success` 均有效。

若 candidate 在校验后、事务提交前失效，命令整体失败，不产生半任命或可用 token。若 candidate 在提交后离线，任命仍保持有效，直到用户或授权主体显式改变 authority。

## 单阶段命令

### `AppointMainAgent`

仅本机 user/control principal 可执行首任命。命令至少包含：

- `command_id`、`project_id`、`candidate_agent_id`、`candidate_session_id`；
- `expected_project_revision`、`expected_authority_epoch`；
- `grant_template_id` 与不可变 digest、ceiling/policy revision；
- 可选 reason code 和用户可见说明。

同一 Unit of Work：设置 current main、递增 authority epoch、签发绑定新 epoch 的管理 grant/token family、创建领域事件和持久通知。D91 的专用 `main_agent_enrollment_ticket` 将 attach 与本命令合并为同一事务。

### `HandoffMainAgent`

用户始终可以执行。当前主 Agent只有在共享 policy 明确允许、其 management grant 尚有效且新授权不超过自身可委派范围时可以执行。

同一 Unit of Work：

1. 重新验证 candidate、project revision、authority epoch、policy 和 ceilings；
2. 把 current main 切换为 candidate，并递增 authority epoch；
3. 撤销旧 management token、未消费的 management intent 和 approval；
4. 为新主 Agent签发绑定新 epoch 的 grant/token family；
5. 对切换瞬间仍在运行的 attempts 启动 D89 的 grant transition/adoption；
6. 写入 authority event、inbox obligation、outbox 和必要的 reconcile job。

存在需要 adoption 的运行中 grant 时，authority 状态为 `transitioning`；否则为 `stable`。这不改变交接已经生效的事实。

### `RevokeMainAgent`

仅 user/control principal 可执行紧急撤销。事务递增 authority epoch、撤销旧管理权并启动 D89 收敛；没有同时指定且验证成功的新候选时，current main 为空，authority 为 `unassigned` 或 `transitioning`。

系统不要求旧主 Agent配合，不等待候选，也不自动把普通 Agent提升为主 Agent。

## 并发与幂等

- authority 命令使用 `command_id`、请求规范化 hash、`expected_project_revision` 和 `expected_authority_epoch`。
- 相同 idempotency key 与相同 hash 返回原结果；相同 key 与不同 hash 返回冲突。
- 两个并发任命或交接只有第一个满足 revision/epoch 条件的事务成功；后到者返回结构化 `authority_epoch_mismatch` 或 `project_revision_mismatch`。
- authority epoch 进入所有 management grants、token families、intents 和 approvals。旧 epoch 不能在重连或 replica 恢复后重新生效。
- 通知重试不得重放 authority mutation 或签发第二套 token。

## 失败与恢复语义

- **事务前校验失败**：没有 authority 变化，也不签发 grant/token。
- **事务提交结果未知**：客户端按相同 command ID 查询或重试，由 command result 表返回唯一结果。
- **事务提交后通知失败**：authority 已生效，outbox 重投；不得回滚。
- **候选随后离线或能力下降**：记录 condition/blocker，由用户 revoke/handoff；不得静默恢复旧主 Agent。
- **旧 Full Access 进程仍在运行**：旧逻辑授权已失效，但系统标记 residual risk/outcome-unknown，并要求主 Agent或用户 reconcile。
- **项目从 checkpoint/clone 恢复**：历史 authority 只作审计依据；本机 session/token 不随 Git 恢复，必须按恢复协议重新建立本机有效 authority。

## API 与工具边界

- `POST /api/v1/projects/{project_id}/authority/actions/appoint-main-agent`
- `POST /api/v1/projects/{project_id}/authority/actions/handoff-main-agent`
- `POST /api/v1/projects/{project_id}/authority/actions/revoke-main-agent`
- `GET /api/v1/projects/{project_id}/authority`

普通 Agent的 MCP 工具不暴露 self-appoint。用户/control API、当前主 Agent的 handoff 工具和普通 worker 请求使用不同 command kinds 与 authorization handlers。

`GET .../authority` 返回 current main、epoch、status、active transition refs、blockers、最近一次命令摘要和通知交付状态；不返回 ticket、token 或 secret。

## 被否决方案记录

第 169 题否决了“两阶段 proposal + candidate acceptance”设计，因此首版不得实现 proposal/accept/reject API、provisional token、接受期限或候选 counterproposal 状态。其原本解决的“候选是否已知情、是否在线”问题改由提交前验证、持久通知、condition/blocker 和显式 revoke/handoff 处理。

## 后续待细化

- main-agent minimum capability profile 和四类 adapter 的证据强度。
- 三种 authority command 的完整 DTO、错误码和 authorization matrix。
- D89 adoption 与 authority `transitioning` 条件的精确投影规则。
- 从共享 checkpoint 恢复 authority metadata 时，本机重建 current main 的命令流程。
