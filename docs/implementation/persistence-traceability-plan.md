# 持久化、溯源与责任留痕修复方案

> 版本：PT-1.2 · 创建时间：2026-09-27T14:39:38Z · 最终验收：2026-09-28T02:39:54Z · 状态：PT1–PT7 已实施并通过非破坏性整体验收
>
> 本文是 `.trellis/tasks/09-27-persistence-traceability` 的唯一技术细化入口。它修复现有原型的持久化和可追责缺口，沿用八大模块、主 Agent 语义决策、daemon 机械边界和本机优先原则；不把规划写成已实现能力。

## 1. 要解决的问题

用户应能在本机用 CLI 回答四个问题：

1. 这个项目事实何时产生或改变，服务端当时看到的真实时间是什么？
2. 哪个经过登记的 actor 代表谁做了动作，动作针对什么 subject，受哪个命令、版本和前置事实影响？
3. 这个结果是 Agent 自报、宿主观测、系统验证还是用户确认？验证使用了哪一组文件、工具版本和 checkpoint？
4. 守护进程重启、响应丢失、工作区被用户手工修改、旧库升级或干净 clone 后，哪些历史能够恢复，哪些权限必须重新授予？

本方案只记录能回答这些问题的结论、输入摘要和证据引用，不要求模型暴露隐藏思维链，也不把“有一行日志”冒充不可抵赖证明。拥有本机 Full Access 的用户仍可能修改本机文件；系统应如实标明证据等级。

## 2. 不改变的边界

- 仍是一个 daemon 管理多个项目；每个项目拥有自己的 scope、lineage 和本地状态目录。
- 八模块仍通过公开端口合作；workflows/blackboard 只是协调载体，不新增领域真相。
- 代码维护身份、scope、版本、状态、revision、单 owner、user-only 决定和运行时 fencing 等机械不变量；主 Agent 决定语义标签、分歧解释和 Git 操作。
- 主 Agent 控制 Git，不自动 commit、push、合并或替用户扩大文件范围。共享工作区可以多人协作，但结果记录只能证明提交身份和当时观察到的内容，不能证明逐行作者。
- Task 可以长期 `open` 或 `blocked`；没有“用户迟迟未答”计时器。上游阻塞时，子 Agent 可以结束当前 turn 并挂起，独立任务仍可继续。
- 本轮不新增数据库、第九模块、远程多租户认证、强制容器/Worktree 默认值、完整评测平台、全量终端录制、操作系统级逐文件作者证明或 token usage 强制收集。

## 3. 统一事实与时间契约（PT1）

### 3.1 公共字段

业务事件使用统一审计包络。字段名在 Schema、SQLite、HTTP、CLI 和 checkpoint 中保持一致：

| 字段 | 语义 | 规则 |
|---|---|---|
| `event_id` | 不可变事件 ID | UUID/现有 ID 格式；重放不换 ID |
| `event_seq` | 项目内单调序号 | 由 daemon 分配；游标分页使用它 |
| `occurred_at` | 事实发生/提交的服务端时间 | DB 存整数 UTC 毫秒；线协议 RFC3339 UTC 毫秒，如 `2026-09-27T14:39:38.123Z` |
| `recorded_at` | 写入持久层的服务端时间 | 只有系统确实晚于事实时间时才与 `occurred_at` 不同 |
| `actor_ref` | 已登记的 user、main Agent、worker、bridge 或 system actor | 不是 IDE 类型；不同 conversation/subagent 是不同 session/worker |
| `subject_ref` | 被操作的项目、任务、消息、契约、工作区或 artifact | 带 project/lineage scope |
| `action` / `outcome` | 规范动作和结果 | 使用 command catalog 的名字，禁止 adapter 自创同义词 |
| `reason_code` | 机器可筛选的原因 | 失败、阻塞、撤销、用户决定必须有；自由解释放在安全摘要 |
| `caused_by_command_id` | 因果命令 | 重试沿用同一 command ID |
| `revision_before` / `revision_after` | 状态 CAS 版本 | 无状态变化的只读查询不推进 revision |
| `evidence_refs` | ArtifactRef、验证回执、checkpoint 或 Git anchor 引用 | 只存引用和 digest，不把大输出塞进事件 |
| `schema_version` / `projection_version` | 解释记录的版本 | 迁移不得改写历史语义 |

实体另外使用 `created_at`、`updated_at`；不可变事件只使用 `occurred_at`。收到客户端时间时可保留为 `client_observed_at`，但排序、SLA 和责任判断只用 daemon 时间。没有可靠历史时间的旧记录使用 `null`/`unknown`，可以另存迁移执行时间 `migration_recorded_at`，绝不把迁移时间伪装成发生时间。

### 3.2 幂等、重试与来源

- 相同 `command_id`、相同 scope 和相同 request digest 重试返回原始安全 receipt，不产生第二个业务事件或新的身份；不相同 digest 返回冲突。
- 连接重建只有在 session epoch/凭据/实际宿主状态改变时产生领域事件；普通 bridge rebind、健康检查和 MCP 查询属于分层诊断，不修改领域 revision。
- 事件、状态变化、命令结果引用在同一 SQLite 事务中提交。命令结果只能写脱敏安全 receipt；不可逆外部副作用通过 operation/outbox 在提交后执行。
- 责任时间线展示 `actor_ref`、`subject_ref`、`action`、`outcome` 和证据等级，不收集或推断 CoT。

## 4. 秘密交付与旧库升级（PT2）

当前缺陷是 enrollment/reconnect 的 `secret_token`、`reconnect_nonce` 进入 command result，并可能复制进 checkpoint、WAL、patch 或导出。修复的边界如下：

1. **SQLite 与共享文件永不保存可用秘密。** command result 只保存 `receipt_id`、`delivery_ref`、过期时间、目标 actor/session、状态和安全摘要；日志、事件、checkpoint manifest、artifact 和 CLI 输出都按同一规则脱敏。
2. **一次交付而非一次生成。** 生成身份、session、ticket 的命令使用稳定幂等键。秘密放入 daemon 管理的私有 delivery bucket（Windows 使用当前用户 DPAPI/受保护 ACL；macOS/Linux 使用严格用户权限），SQLite 只保留引用/哈希。bridge 通过受认证的本机命令响应读取，先标记 delivered；原子保存私有 session 后认证 ACK，daemon 才标记 consumed 并移除秘密。在 ACK 前的短恢复窗口内，只有同一绑定命令可重试读取，不能由另一个 Agent 领取。实施语义见 [凭据交付](credential-delivery.md)。
3. **响应丢失可恢复。** command retry 重放同一 receipt；如果秘密已消费，返回“已交付/需要重新连接”的可操作状态，不创建第二个 agent。需要重新发放时，必须显式撤销旧 delivery 并创建新 session epoch，记录 user/main 决定和原因。
4. **旧库迁移先演练再执行。** 迁移前用 SQLite Backup API 创建一致副本并校验 `integrity_check`；暂停写入，撤销旧 token/nonce，重建 session credentials，清理 command result、module snapshot、checkpoint、artifact metadata、WAL/SHM 中的可见副本，再以新 schema 打开。`secure_delete` 只能减少已删除页残留，不能承诺抹除备份或磁盘取证副本；这项限制写入用户报告。真实项目迁移必须由用户在 PT7 操作单中确认，规划阶段不触碰演示库。
5. **失败安全。** 迁移任一阶段失败时保留只读备份和可诊断错误；禁止恢复带活跃旧 credential 的库。所有恢复操作都要先显示 plan digest，再由 user-only 命令确认。

## 5. 工作区、附件与验证证据（PT3）

### 5.1 内容与范围

工作区结果必须绑定 `project_id`、`lineage_id`、`workspace_id`、授权 scope、baseline digest、result digest、提交 actor、`observed_at` 和工具版本。digest 由实际允许路径的文件内容、相对路径、类型、模式和必要 Git 状态计算，不能只 hash `git status` 文本；同路径内容变化必须被发现。`.tsunagou/local`、bridge 私密目录、未提升为结果的临时文件和范围外路径一律排除。

系统扫描产生的 patch/artifact 引用是受信结果；调用者提供的 `patch_artifact_ref` 只能在 digest、owner、scope 和内容重新验证后接受，不能覆盖系统扫描结果。Artifact 查询必须先通过项目域和私有消息/收件人权限，再按 content hash 读取，不能凭 hash 直接越过域边界。

### 5.2 证据等级

每条验证回执标明一个枚举：

`agent_asserted`（Agent 自报） → `host_observed`（宿主执行/读取） → `system_verified`（daemon 重算 digest、退出码或协议结果） → `user_confirmed`（用户明确确认）。较高等级不能自动替换较低等级的原始事实；用户确认也不抹掉失败尝试。

验证记录至少含 `started_at`、`finished_at`、命令/测试标识、退出码、工具和版本 digest、工作区 digest、evidence level、actor、stdout/stderr 安全摘要。默认不保存完整输出；路径、token、环境变量和私密消息需脱敏。共享工作区结果不生成逐行作者断言。

## 6. 项目真相、checkpoint 与恢复（PT4）

### 6.1 真相分层

- SQLite 事件/领域状态是本机运行时事实；共享 `project.json`/checkpoint 是经过 DTO 白名单导出的协作快照，不是第二个可随意写的数据库。
- `runtime_epoch`、活动 grants/leases、桥接 ticket、宿主 conversation、私有收件箱和当前 job claim 属于本机动态事实，不写入共享项目真相；runtime fence 表是权威来源。
- checkpoint 使用显式 export DTO；不得用递归黑名单作为唯一安全边界。manifest 中记录 `checkpoint_id`、`parent_checkpoint_id`、`lineage_id`、`through_event_seq`、schema/projection 版本、创建时间、创建 actor、原因、文件 digest、artifact digest、Git anchor 状态和验证时间；不含 token、nonce、私有消息正文或绝对本机路径。

### 6.2 物化和初始化

项目初始化创建 genesis checkpoint/事件；之后在用户显式创建、main Agent 提议且用户确认、项目完成确认等有解释价值的里程碑生成 checkpoint，不对每次只读查询或每个传输重连生成快照。业务事务提交后再用本地 operation/outbox 物化文件并更新状态，文件失败不回滚已经提交的业务事实；重启后可幂等重试 `pending` operation。checkpoint 生成失败、重试和最终验证都留痕。

### 6.3 Git anchor 与 clone 恢复

Git anchor 只接受本机允许的 `refs/heads/*`、`refs/tags/*`，并验证 manifest/快照内容确实可从该 commit/tree 读取；不能用 digest 是否是 commit OID 的子串，不能接受 remote ref、reflog 或用户只提供的裸 OID。Git 仍由 main Agent 控制，不自动 commit/push。

恢复采用两阶段：`restore preview` 生成包含 checkpoint digest、目标路径、权限清理、schema 版本和风险的 plan digest；user-only `restore confirm <plan-digest>` 执行。干净 clone 导入历史时，新运行时默认 unassigned，撤销旧 session、grant、lease、job claim 和 bridge ticket；仅在 lineage/anchor 校验通过时保留历史链，不继承活动权限。

## 7. 查询、CLI 与 HTTP（PT5）

新增的是只读投影，不新增领域动作。CLI 名称必须映射已有权限：

```powershell
# 项目责任时间线：默认 50 条，最多 200 条，游标以 event_seq 稳定分页
tsunagou project history <project-id> --from 2026-09-27T00:00:00Z --to 2026-09-28T00:00:00Z --actor <actor-ref> --limit 50 --cursor <cursor>

# 单个任务的状态、Attempt、消息、报告、契约和验证引用
tsunagou task history <task-id> --limit 100 --json

# 查看一个事件及其因果链；仍执行项目 scope/私有消息权限
tsunagou audit event <event-id> --include-evidence

# checkpoint 清单/实际内容与 Git anchor 校验
tsunagou checkpoint list <project-id> --verify
tsunagou checkpoint verify <checkpoint-id>

# 恢复必须先预览再由用户确认
tsunagou project restore preview <project-id> --checkpoint <checkpoint-id>
tsunagou project restore confirm <plan-digest>
```

HTTP 使用同一 dispatcher 和 DTO，推荐只读路由：`GET /projects/{id}/history`、`GET /tasks/{id}/history`、`GET /audit/events/{id}`、`GET /projects/{id}/checkpoints`、`GET /checkpoints/{id}/verify`。`from`/`to` 为 RFC3339，`limit` 默认 50、最大 200，`cursor` 由 daemon 签发；响应包含 `items`、`next_cursor`、`projection_version` 和 `as_of_event_seq`。越权、私有收件箱和 artifact 读取沿用现有项目权限；查询失败不能写领域事件。恢复 confirm 仍是 user-only 命令，不由 GET 或普通 Agent 工具触发。

CLI/HTTP 不读 SQLite、不要求用户手工拼 URL。若事件没有历史时间，时间筛选中标为 `unknown_time`，不按迁移时间插入错误位置。导出以 JSONL/manifest 为限，默认只导出当前 actor 可见内容并带 schema、exported_at 和 source project/lineage。

## 8. 运行噪声、唤醒与后续修复（PT6）

业务历史与传输诊断分层：

- 领域历史：enrollment、任务领取/提交、认知报告、契约接受、权限决定、lease/fence、工作区结果、用户确认、checkpoint 和恢复。
- 诊断历史：bridge 启停、MCP rebind、A2A delivery attempt、callback 延迟、host presentation、wake requested/started/observed/unknown。它们有时间和相关 ID，但不自动等于 Agent 已被宿主唤醒。

常驻 bridge 的重复 no-op 查询不得每次制造 domain event；真正 epoch、凭据或宿主状态变化必须保留。A2A message/send 的 durable message、delivery callback、host wake 和 Agent 实际 pull/turn 是四种证据，时间线分别展示，不能以 callback 成功冒充 turn 已执行。验收后的浏览器/大文件等新工作必须创建新 task/result，并用 `caused_by`/`fixes` 关联旧问题，不追补成旧验收证据。

## 9. 八模块责任映射

| 模块 | 必须可追溯的事实 | 本轮不做 |
|---|---|---|
| `projects` | 项目/根/仓库登记、scope 与 policy 版本、用户决定、genesis/lineage | 自动扩大根目录、远程租户 |
| `agents` | 每个 conversation/subagent 的 actor/session、enroll、ticket receipt、消息收发、delivery/wake 分层 | 把 IDE 类型当唯一 agent、持久明文 secret |
| `tasks` | draft/open/claimed/running/blocked/submitted/review/complete 的 actor、时间、revision、Attempt、恢复和验收 | 由租约阻止未来领取，或用等待超时替代状态 |
| `cognition` | report/claim/assumption digest、不一致、契约 proposal/accept 的参与者和决定时间 | 主动推断 CoT/隐含分歧 |
| `resources` | 意图、scope、冲突、lease、expiry/release、fence 和原因 | 新增隐式共享资源真相 |
| `workspaces` | baseline/result 内容 digest、允许路径、提交/观察 actor、工具回执和证据等级 | 逐行作者证明、默认隔离驱动 |
| `durability` | command/event/operation/outbox/checkpoint、迁移版本、恢复点、secret delivery ref | 将所有 module JSON 改成全量 Event Sourcing |
| `evaluation` | 审计投影、查询可见性、验证/故障结果和版本 | 强制 token 统计、把研究实验当产品能力 |

## 10. 子任务和依赖

机器索引见 [persistence-traceability-tasks.json](persistence-traceability-tasks.json)，Trellis 文档见 `.trellis/tasks/09-27-trace-*`。为降低跨层歧义，实施顺序固定为：

`PT1 时间与事件契约 → PT2 秘密 receipt → PT3 工作区证据 → PT4 checkpoint/恢复 → PT5 查询/CLI → PT6 降噪/wake 关联 → PT7 迁移与整体验收`。

PT1 是所有后续前置；PT2、PT3 都必须引用同一包络和 evidence level；PT4 依赖秘密 DTO 和 artifact 引用；PT5 依赖所有可查询投影；PT6 依赖 receipt、事件和 wake 关联；PT7 依赖前六项并且是唯一整体关闭门。

## 11. 验收矩阵

实施时必须在脱敏 fixture、临时项目和真实用户选择的项目上分阶段记录 `started_at`/`finished_at`、HEAD、daemon/schema 版本、命令、退出码和证据引用：

1. 两个独立 Agent 完成消息协商、认知分歧、契约接受、结果提交、审查和用户完成决定；重复 command 不重复业务事件。
2. 注入 commit 前、commit 后、文件物化中、重启后的失败；无孤儿业务事实、checkpoint 可重试、cursor 无缺页/重复。
3. secret sentinel 在 SQLite、WAL/SHM、checkpoint、artifact、patch、audit、CLI/HTTP 响应和日志中不可见；旧库撤销旧 credential 后才能打开。
4. 同路径内容修改、tracked/untracked、范围外修改和附件嵌套测试；系统 digest 能区分内容，提交身份不升级为作者证明。
5. Git branch/tag 可验证，错误的 OID 子串、remote ref、reflog 和内容不匹配均拒绝；clone 恢复不继承活动 grant/lease/session。
6. 时间采用 UTC 毫秒、未知旧时间保持 null；`from/to`、actor、subject、cursor、权限过滤在 CLI/HTTP 等价。
7. 连接重绑、A2A callback、host wake、Agent pull 和 turn 分层可见；稳定 bridge 的 no-op 不推进领域 revision。
8. Windows 首次安装、daemon 启停、真实 CLI、文档链接和任务校验通过；所有文档写“已实现”必须附命令/版本/时间证据。

## 12. 实施前后安全闸门

用户已下令实施全部任务，代码和临时项目验收持续推进；原规划轮的“只创建文档”限制已结束。真实项目操作仍保持单独授权：不自动迁移 `D:\ALL.NET\SegaImageManageTool` 或其他运行库，不撤销外部项目会话、不重启其服务。真实库须先做 dry-run、备份和秘密扫描，由用户决定作用时间。每个 PT 完成后更新相应任务的 JSONL、测试和证据；未通过的局部任务不能标为完成。

参考机制：[RFC 3339](https://www.rfc-editor.org/rfc/rfc3339)、[SQLite Backup API](https://sqlite.org/backup.html)、[SQLite WAL](https://sqlite.org/wal.html)、[SQLite secure_delete](https://sqlite.org/pragma.html#pragma_secure_delete)。
