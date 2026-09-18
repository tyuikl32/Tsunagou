# 01 项目空间、范围与权限

## 所有权与边界

拥有 Project、Lineage/Replica 注册、Root/Repository、Policy、UserCeiling、Grant、Condition/Blocker、UserDecision、ProjectCompletionProposal。agents 拥有身份认证和 Authority；durability 执行文件物化。项目生命周期由本模块决定，但跨模块原子转换由 workflows 编排。

## 实体和表

所有表前缀 `projects_`，通用字段见[数据模型](../data-model.md)。共享历史与本机运行字段分开导出 profile。

| 表/实体 | 必须字段（除通用字段） | 约束与索引 |
|---|---|---|
| projects / Project | name, objective, lifecycle, coordination_repository_id, current_lineage_id, current_replica_id, runtime_epoch, policy_revision | project ID 唯一；active lineage 必须 open |
| lineages / Lineage | status, parent_lineage_id?, base_checkpoint_digest?, sealed_checkpoint_digest?, transition_reason | 历史祖先引用不可改；同项目一个当前 open |
| replicas / Replica | role, registration_digest, last_checkpoint_digest?, last_runtime_epoch | 本机 registry 对 `(project,lineage)` 最多一个 active_writer；不声称跨机器强锁 |
| roots / RootRegistration | name, root_kind:directory|repository, repository_id?, required, descriptor_digest | name 项目内唯一；共享行无绝对路径 |
| bindings / RootBinding | root_id, absolute_path, physical_identity, case_mode, link_policy, status:bound|unbound|identity_changed, binding_revision | 本机私有；同实体 alias 归一；索引 physical_identity |
| repositories / RepositoryRegistration | name, root_id, git_common_dir_identity, baseline_ref?, required | 本机绑定与共享逻辑描述分离；同 common-dir 不重复登记仓库身份 |
| policies / ProjectPolicy | version, canonical_payload, digest, actor, reason | 不可变版本；current 指针带 revision；只允许注册字段 |
| ceilings / UserCeiling | subject_template, path_rules, capability_ids, full_access_allowed, reserved_decisions, digest | 本机 user-only 写；Grant 必须子集 |
| grants / Grant | kind, principal_id, session_id, runtime_epoch, authority_epoch?, task_id?, attempt_id?, execution_epoch?, scope_version, scope_json, scope_digest, capabilities, status, replaces_id? | 五 kind；外键列对应 JSON；`(session_id,status)`、`(attempt_id,status)` 索引 |
| decisions / UserDecision | kind, proposal_ref, proposal_digest, expected_revisions, choices, status, decision, reason?, decided_at? | 提交决定必须 user_control；pending 无 deadline |
| completion_proposals | objective_ref, project_revision, evidence_refs, outstanding_summary, digest, status:proposed|confirmed|superseded|rejected | 用户确认冻结 exact digest；不能随最新证据自动变更 |
| conditions / blockers | 见数据模型完整 DTO | `(type,scope)` / `(code,source_ref,scope)` current 唯一；变化另记 event |

## 根目录、路径和 scope

初始化要求 coordination root 已是 Git 仓库，`.tsunagou/` 在仓库顶层；不要求已有 commit。注册额外根不改变协调中心位置。root 目录重绑定必须对比真实 physical identity，不以字符串相等认定同一个目录。

PathRule 仅正向 segment prefix。多个允许规则取并集；和 user ceiling、main 可委派 scope、任务 scope、宿主能力取交集。大小写按本机绑定确定；Windows drive/UNC、junction、symlink 要解析验证，跨 root 的链接目标重新授权。嵌套/重叠 roots 以最具体 root 规范化，同时满足祖先上限，不能通过宽别名逃逸窄范围。

真实写入前的再检查能约束系统自己执行的 I/O；Full Access 宿主的任意写不在 OS 防护承诺内。观察到越界产生证据/告警，主 Agent 决定处置，内核不静默回滚文件。

## 授权管线

每条 command 在注册表恰有一条 policy：`allowed_principal_kinds,required_grant_kind,required_capability,predicates[],blocker_action`。不引入运行时表达式语言、any_of/not、通配 capability 或超级管理员 Grant。user-only 命令的 grant/capability 为 null；内部 system_job 独立注册。

五种 scope：agent_base 绑定 self/project；main_authority 绑定 authority epoch、可委派 capability 和 path rules；task_attempt 绑定精确 task/attempt/execution epoch、workspace、path/named resources；task_review 绑定 submitted result/review round，无写文件权；handoff_transition 仅允许指定旧对象安全收敛。

Grant 替换必须撤销旧记录，新建更窄/新的记录；不可原地扩大。blocked owner 仍能用 agent_base 提交协调信息，但不能开始文件执行或续 execution Lease。主 Agent 的角色不能代替任务 owner。

## 用户决定

固定 user-only：任命/撤销 main、扩大用户 ceiling/Full Access、变更 coordination root/信任边界、项目整体完成、需要用户批准的破坏性 Git/最后副本删除。其他业务重大性由 main 申报；核心不分析自然语言猜测。

对话收集偏好，CLI/HTTP control 提交精确 revision/digest。pending decision 只能由 current main 组织展示，CLI 同时 list/show。无 OS 通知、无“超时拒绝”、无宿主 user-role 证明捷径。输入变化使旧 proposal superseded；新批准不能套到旧目标之外。

## 公开端口与事件

- `authorize_command(command,principal,uow) -> AuthorizedContext`，带 verified grant/scope/epochs，不含 secret。
- `authorize_scope(request,ctx,uow) -> EffectiveScope`；`query_project` / `query_conditions` / `query_blockers` 返回 snapshot DTO。
- `replace_attempt_grants`、`revoke_session_grants`、`freeze_authority_grants` 仅通过 workflow 在同 UoW 调用，校验目标归属。
- 事件：project_initialized、project_lifecycle_changed、root_registered、root_binding_changed、policy_revised、grant_issued、grant_revoked、user_decision_resolved、project_condition_changed、project_blocker_changed。

## 必测行为

子 Agent 任命 main/扩大 ceiling/提交父 Attempt 全拒绝；REST/MCP 同结果；root 别名/大小写/链接无法扩大逻辑 scope；一个 root unbound 不阻塞无关任务；旧 Grant/epoch commit 前失效；user confirmation 输入变化返回 revision/digest 冲突；未锚定项目仍可普通协作与完成。

实现依赖 T03/T04，分为 T05 项目与范围、T06 身份授权集成、T15 生命周期。依据：[历史范围模型](../../history/2026-09-18-source/grant_scope_model.md)、[状态模型](../../history/2026-09-18-source/project_state_model.md)。
