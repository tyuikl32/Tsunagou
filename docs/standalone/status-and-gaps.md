# 2026-09-21 代码进度与八模块缺口

## 1. 结论和检查口径

当前系统能从源码或 wheel 启动本机 daemon，CLI 与 HTTP 访问同一 SQLite runtime；M1 十二条最小产品标准已通过，证据集中在 [M1 验收记录](m1-acceptance-2026-09-21.json)。原始完整设计仍有完整 resource/job runner、物化中断矩阵、八模块扩展查询和真实宿主接入等后续范围，不能把 M1 通过解读为完整设计全部完成。

检查以 `main@f9ea7b4` 为基线，包含源码调用关系、真实 uvicorn 子进程、loopback HTTP、进程重启、CLI 独立进程和 wheel 安装路径。审计脚本只使用临时目录。下面的缺口不依赖任何 IDE、Agent 能力表或模型服务。

| 量化结果 | 本轮实际结果 | 能说明什么 |
|---|---|---|
| Python 测试 | `python -m pytest -q`：以当前命令实测为准 | 基础单元/集成断言成立；未覆盖完整产品闭环 |
| TS 测试 | `corepack pnpm exec vitest run`：29 passed | SDK/适配器单元逻辑通过 |
| 命令注册 | 107 个声明命令，当前运行装配 60 个；bridge `tools/list` 暴露 49 个工具 | 47 个声明动作仍未装配；已装配动作也不等于完整闭环 |
| 公共项目查询 | `/api/v1/projects/{id}/tasks`、`/attempts`、`/results`、`/jobs`、`/roots`、`/repositories` 返回 200 | 当前可读任务、Attempt、Result、Job、agents/contracts/messages/roots/repositories，完整分页/权限查询仍待补齐 |
| 本轮运行审计 | 16/16 通过 | 覆盖幂等、draft、协议版本、所有权、原子回滚、重启、CLI 票据 |
| daemon lifecycle | 临时 Git 项目 start/status/doctor/enroll/stop 通过 | 同一 CLI 与常驻 daemon 工作；公开 M1 smoke 已加入重启恢复 |
| wheel | 包含 113 个 protocol_data 文件；源码树外干净 venv 可读 registry 并启动 CLI | R1资源缺陷已修复；完整故障场景仍属 R6 门禁 |

60/107 是入口覆盖计数，不是项目完成百分比。16 项审计是已装配后端的回归集合，不覆盖完整八模块业务闭环。原始运行结果在[审计 JSON](audit-2026-09-21.json)；bridge 工具目录探针见[bridge smoke](bridge-smoke-2026-09-21.json)。

## 2. 实际运行链路

```text
daemon start -> uvicorn -> bootstrap/container.py
             -> Authority/Task/Cognition/Message services
             -> ServiceStateRuntime <-> project/.tsunagou/local/state.sqlite3
             -> CommandDispatcher (protocol + idempotency + transaction)
             -> HTTP routes

CLI agent/doctor/decision/operation/recover -> 同一 daemon HTTP endpoint
CLI daemon start/status/stop -> endpoint.json + private control.token

Resource/Workspace/Artifact/Checkpoint/Lifecycle/Evaluation
             -> 有分项代码和测试，但完整业务装配仍是 R3-R6 缺口
```

主要源码：[装配](../../src/tsunagou/bootstrap/container.py)、[handler](../../src/tsunagou/application/handlers.py)、[CLI](../../src/tsunagou/cli/app.py)、[dispatcher](../../src/tsunagou/interfaces/runtime.py)、[HTTP](../../src/tsunagou/api/app.py)。

## 3. 八模块逐项进度

### 01 projects：项目与额外根登记已接通，用户边界和完整项目生命周期仍缺

- 已有：Git 项目初始化、`project.json`/`bindings.json`、主 Agent `root.manage` Grant、`root.register`/`root.bind`/`repository.register` handler，以及 roots/repositories 脱敏查询。2026-09-21 集成测试覆盖额外目录绑定、仓库登记和查询，证据见 [project roots smoke](project-roots-smoke-2026-09-21.json)。
- 缺少：UserCeiling 持久实体及请求授权连接、项目与 lineage 的关联校验、完整 project 生命周期命令和项目级配置查询。
- 明确偏差：原设计用 project.toml/local config + SQLite；当前 JSON 项目文件还承载部分运行字段。根登记写入 JSON，与协作事实 SQLite 事务尚未统一；root/scope 仍未作为每个业务动作的统一授权前置。
- M1 已通过：用户边界与派生 Grant、项目/根/仓库 revision 与 SQLite UoW、真实决定/完成/查询接口和项目内持久状态均有入口证据；完整项目生命周期仍是后续范围。
- 原设计余量：多项目惰性加载、replica 激活、lineage reset、共享分叉 reconcile、跨机器恢复和完整配置来源。
- 依据：[projects.py](../../src/tsunagou/modules/projects.py)、[lifecycle.py](../../src/tsunagou/application/workflows/lifecycle.py)、[原设计](../implementation/modules/01-projects.md)。

### 02 agents：身份与消息已接入持久 runtime，双 bridge 首轮 smoke 已通过

- 2026-09-21 修正身份边界：`installation_id` 只标识宿主安装；同一 IDE 下的不同 conversation/subagent 各自创建独立 `agent_id`、`session_id`、凭据和私有 bridge session 文件。服务端 rebind 同时核对 conversation digest，不能把新对话重绑到旧 Agent。

- 已有：单次票据、会话 token/epoch、用户任命 main、Grant、私有 JSON 保存；消息、投递、ACK、回应义务；真实 stdio bridge 文件。2026-09-21 的构建探针证明 bridge 能从共享 registry 读取摘要并通过 MCP `tools/list` 暴露 48 个工具，其中包含任务恢复、认知分歧、契约处置、resource、workspace、review、decision 和 completion；随后单 bridge 认证 smoke 完成 ticket redemption、main 任命、reconnect 和 task create/ready/publish，两个独立 bridge 的完整首轮 MCP 协作也已通过，证据见 [bridge tools](bridge-smoke-2026-09-21.json)、[authenticated bridge](bridge-auth-smoke-2026-09-21.json) 与 [双 bridge](bridge-two-session-smoke-2026-09-21.json)。
- 缺少：会话终止后同步撤授权、处理相关任务；消息投递租约和完整查询；主 Agent handoff/succession 实际入口；两个真实宿主 bridge 的接入回执。
- 已修复：CLI 通过同一 daemon 签发票据，运行中的 daemon 可立即兑换；Authority、Grant、Message 与任务状态在同一 SQLite runtime 快照事务中恢复。
- M1 已通过：用户决定、项目完成、checkpoint、daemon 重启和 recovery 已通过同一公开入口烟测；重启后还逐一查询 tasks、attempts、results、jobs、agents、cognition/contracts、messages、workspaces、decisions 和脱敏 audit，记录见 [m1-public-smoke-2026-09-21.json](m1-public-smoke-2026-09-21.json)。重启会释放旧 claim/Lease 并将未完成 Task 放回 `open`，旧 Attempt 保留 orphaned 历史；双 bridge 断线故障注入和本机凭据失败路径保留为完整接入后续。
- 原设计余量：高级 handoff 收敛、复杂路由、多个宿主生命周期增强、推送/唤醒。
- 依据：[authority.py](../../src/tsunagou/modules/authority.py)、[messaging.py](../../src/tsunagou/modules/messaging.py)、[bridge server](../../packages/bridge-server/src/server.ts)、[原设计](../implementation/modules/02-agents.md)。

### 03 tasks：基础状态机、owner 边界和恢复动作已接通，执行闭环仍缺关键模块

- 已有：Task/Attempt、claim、preflight、start、progress、block、submit、review、scope request 和 DAG 检查函数。
- 已验证：重启保留 Task/Attempt；重复 command_id 只返回同一事实；create 保持 draft；省略 preflight 被拒；另一个 worker 不能 block/resume；错误 attempt_id 不产生 running 副作用。
- 已接入：`task.update_plan`、`task.edge.add/remove`、`task.cancel_request/ack`、`task.fail`、`task.recover`、`task.scope.request/resolve`、`task.self_accept` 已有公开 handler；恢复会释放旧 Lease 并撤销旧执行 Grant，scope 请求校验 task/scope revision。公开入口证据见 [M1 runtime flow](../../tests/integration/test_m1_runtime_flow.py)。
- 其他缺口：依赖完成、参与资格、恢复 owner、审查槽位的完整矩阵仍未形成事务闭环。`TaskExecutionWorkflow` 已成为 handler 的 preflight/start 唯一编排，持久 `tasks.PreflightResult` 记录 digest、revision、evidence 和 blockers；可选 execution scope 已按 root/path 前缀约束 resource intent；`request_changes` 已补上旧 Attempt 的 Lease 释放和 execution Grant 撤销，仍需继续扩展审查矩阵。
- M1 已通过：持久 Task/Attempt/Result/Review、严格 owner、draft→ready→open、统一 preflight/start、失败回滚、指定审查者和重大决定阻塞/恢复均已覆盖；复杂继任、批量生命周期保留为后续。
- 原设计余量：复杂委派/依赖图、后续任务关系、批量恢复和继任计划。
- 依据：[tasks.py](../../src/tsunagou/modules/tasks.py)、[task_execution.py](../../src/tsunagou/application/workflows/task_execution.py)、[原设计](../implementation/modules/03-tasks.md)。

### 04 cognition：报告、分歧推进/解决和契约拒绝/撤回已接入，复杂联动仍缺失

- 已有：report、literal mismatch、契约参与者摘要、逐 slot 接受、风险请求/接受函数。
- 已验证：不存在的 task/attempt 不能提交 report；重启后 proposal 可继续接受。
- 已接入：`discrepancy.create/advance/resolve` 和 `contract.accept_proxy/reject/withdraw` 进入公开 handler；worker 只能推进分歧，主 Agent通过 `cognition.resolve` 解决；契约拒绝要求参与者和 digest，撤回要求提出者。`/api/v1/projects/{id}/cognition` 返回脱敏报告、discrepancy 与契约；若存在 `payload.task_id` 关联契约，未接受契约的 `task.start` 会被拒绝。
- 缺少：报告与 preflight/blocker 的完整状态关联；旧报告被替代后的判断；风险流程运行装配；proxy policy 的持久规则。
- M1 已通过：持久报告与契约、双 Agent 分歧、可查询分歧、主 Agent 协商和相关方接受解除 blocker 均已覆盖；更复杂风险 fallback 仍由 Agent 决定并保留为后续。
- 原设计余量：更多确定性规则、完整 proxy policy、风险 fallback 和历史版本治理。
- 依据：[cognition.py](../../src/tsunagou/modules/cognition.py)、[原设计](../implementation/modules/04-cognition.md)。

### 05 resources：intent/acquire/renew/release 已接入，物理alias与后台机械维护已补

- 已有：intent、路径前缀冲突、整组 reserve、renew、expire、wait 队列、external observation。
- 已接入：资源 intent、整组 acquire、release、X 会话 renew；task.start 会检查当前 Attempt 的 active Lease，失败不写 running；若任务声明 execution scope，intent 会在 Lease 前按 root/path 前缀和 mode 校验子集。
- 已接入第一轮：每次 start/acquire/renew 前检查到期 Lease；过期的 claimed/running Attempt 标为 orphaned，相关执行 Grant 撤销，Task 回到 `open` 公共队列，任何后来加入且具备基础权限的 Agent 都可重新 claim。`RuntimeMaintenance` 还会在 daemon 生命周期内后台执行同一回收，并将结果写入 SQLite 事件。Lease 只约束执行 Attempt，不约束 Task 的领取资格。
- 缺少：physical identity alias 归一、跨 root 的完整 scope 版本模型、bridge 周期续租及更完整的撤权通知事务。
- 已补：项目 root binding 的 `physical_identity` 参与 ResourceService 冲突归一；不同 root_id 指向同一物理目录时仍会冲突，回归见 `test_physical_root_aliases_conflict_even_with_distinct_root_ids`。常驻维护处理到期 Lease/Job 的机械撤权。
- M1 后续：同路径独占写、不同路径并行、Lease 通知/续租和更完整的等待恢复。Lease 继续是协调规则，不是文件系统锁。
- 原设计余量：完整排队公平性、复杂 consistent_read 和外部资源类别。
- 依据：[resources.py](../../src/tsunagou/modules/resources.py)、[原设计](../implementation/modules/05-resources.md)。

### 06 workspaces：shared baseline/result 与真实 root 扫描已接入，完整隔离驱动仍缺

- 已有：shared/worktree/external 描述、隔离决策、GitActionRequest、baseline/result、目标 HEAD 核验、dirty cleanup 拒绝。
- 已接入：main 选择 shared、worker prepare baseline、X 记录 result，workspace state 随 SQLite 快照恢复；task.start 检查 workspace ready；shared 根目录会读取 Git HEAD/branch/status，结果会生成内容寻址 patch、标记 baseline conflict，并可通过 artifact 查询读取。双 bridge smoke 还执行了一个真实 Node 检查，并在 baseline 后写入用户编辑文件，要求公开 result 返回 `baseline_conflict=true`。
- 缺少：worktree/external 实际目录/Git Job、整合/清理与主 Agent动作关联。
- 明确限制：`record_result` 比对的是已保存的 baseline digest，不等于重新扫描磁盘；HEAD 不变也可能有用户未提交改动。没有持续文件 watcher，不能自动识别某个 diff 是用户还是 Agent 写的。
- M1 已通过：用户/main 明确选择 shared，对实际 root 生成 baseline/result、记录 patch、检查手动变化并将结果交给主 Agent；worktree/external 隔离仍是后续范围。Agent 正常写代码产生 dirty 是预期结果，不能一概当作用户冲突。
- 原设计余量：worktree/external 完整 prepare/integrate/cleanup、多个仓库分步整合、跨机器环境恢复。
- 依据：[workspaces.py](../../src/tsunagou/modules/workspaces.py)、[原设计](../implementation/modules/06-workspaces.md)。

### 07 durability：核心服务已使用项目 SQLite，完成确认和失败重试已接入，完整 repository/job 仍缺失

- 已有：SQLite WAL、事务、command 幂等表、event/outbox、Operation/Job、checkpoint staging/hash、Git anchor 扫描、blob 写入与读取函数。
- 已接入：项目完成确认会生成可验证的 content-addressed checkpoint 和 succeeded operation；物化失败会保留 completed 结论并生成 failed operation，重启后的 `durability.reconcile` 可由主 Agent重新物化并收敛原 operation，用户 CLI 也有 `checkpoint retry` 路径。公开 smoke 现在用真实 daemon 查询 failed operation，再通过 CLI retry 生成 sealed pointer，测试证据见 [checkpoint-failure-2026-09-21.json](checkpoint-failure-2026-09-21.json)。
- 已补：常驻维护每 tick 调用持久 Job 的 expired-lease recovery，公共 `GET /api/v1/projects/{project_id}/jobs` 可查询状态；这只处理无人持有 lease 的机械恢复，不执行 handler。
- 缺少：八模块独立事实表和 repository、服务生命周期 Job runner/outbox worker、迁移、checkpoint/附件元数据的完整索引和完整 epoch 处置。
- 已验证：正常 daemon 请求创建并写入项目 `state.sqlite3`；任务/契约/消息重启保留；失败命令恢复内存快照并不写半成品事实；真实 daemon 在提交前退出不会留下半写事实，提交后响应窗口退出时同一 `command_id` 重放原结果且不重复执行（`tools/dev/commit_window_process_smoke.py` 与 `test_sqlite_commit_before_response_replays_original_result`）。
- M1 已通过：所有实际协作事实落项目 SQLite，跨模块 UoW、重放/重启/崩溃恢复、checkpoint 与必要附件、秘密过滤均有证据；主动 Job runner、完整附件索引和迁移仍是后续范围。
- 原设计余量：Git 可达锚点驱动跨 replica 恢复、共享 checkpoint 分叉合并、lineage reset、完整迁移版本窗口。
- 依据：[sqlite.py](../../src/tsunagou/platform/db/sqlite.py)、[checkpoints.py](../../src/tsunagou/platform/checkpoints.py)、[artifacts.py](../../src/tsunagou/modules/artifacts.py)、[原设计](../implementation/modules/07-durability.md)。

### 08 evaluation：有脱敏与统计函数，已接入基础事件审计查询

- 已有：SecretRedactor、AuditProjector、指标 availability、实验定义/run/result/report。
- 已接入：`GET /api/v1/projects/{id}/audit` 从已提交 SQLite events 生成脱敏 `AuditView`，不读取业务写端口，结果可在重启后重建。
- 缺少：分页 cursor、指标/实验 ledger 持久化、完整日志关联和失败定位信息；实验 ledger 仍是内存。
- M1 已通过：command_id/task_id/attempt_id/event_seq 可追踪，脱敏审计、查询失败原因和可复现运行结果均已覆盖；更完整分页/统计仍是后续范围。它不能修改业务状态。
- 原设计余量：A/B/C/D 研究实验、多次统计、跨宿主对照和 token 性能报告。它们不阻塞 M1。
- 依据：[evaluation.py](../../src/tsunagou/modules/evaluation.py)、[原设计](../implementation/modules/08-evaluation.md)。

## 4. 历史缺陷与当前状态

| 编号 | 操作 | 当前结果 | 必需结果 | 对应实施包 |
|---|---|---|---|---|
| F01 | 离线 resolve 不存在的决定 | 已改为非零错误 | 找不到 daemon/对象应失败 | R2/R5 |
| F02 | 相同 task.create command_id 发两次 | 同一 task_id，事务幂等 | 同一持久结果 | R2 |
| F03 | task.create | 返回 draft，ready/publish 独立 | draft，显式 ready/publish | R3 |
| F04 | protocol_version=999 | HTTP 400，未写入 | 400，未写入 | R1 |
| F05 | GET 项目 tasks | HTTP 200，返回持久列表 | 有权限的任务列表 | R2/R3 |
| F06 | 无 preflight/Lease/workspace 执行 start | HTTP 400，Task 保持 claimed | 阻塞，未签执行权 | R3/R4 |
| F07 | worker block 主 Agent任务 | HTTP 403 | 403 relationship_denied | R3 |
| F08 | worker resume 主 Agent已 block 任务 | HTTP 400，owner 不变 | 403，owner 不变 | R3 |
| F09 | start 带错误 attempt_id | HTTP 400，Task 保持 claimed | 拒绝且无任何状态写入 | R2/R3 |
| F10 | report 指向不存在的任务 | HTTP 400，无 report | 404/403，无 report | R4 |
| F11 | kill/restart 后读取已 claim 任务 | Task/Attempt 可读 | Task/Attempt 恢复 | R2 |
| F12 | restart 后接受既有 proposal | HTTP 200 | proposal 仍可查/处理 | R2/R4 |
| F13 | 执行正常协作操作 | `state.sqlite3` 已建立并写入 | 事实已提交 SQLite | R2 |
| F14 | CLI 给运行 daemon 签票后兑换 | HTTP 200 | 同 daemon签发和消费 | R2/R5 |
| F15 | 安装 wheel后离开源码树启动 | Python wheel 和 Node bridge 包内资源均可读 | 包内资源可用 | R1/R6 |

F01–F14 来自当前脚本；F15 来自 wheel 安装检查。它们是回归集合，不是无遗漏的全量安全审计。R3-R6 尚需补充的完整协作闭环仍列在下一节八模块缺口中。

## 5. 离初始设计多远

八个模块均有可复用的基础代码，但没有任何一个模块完成“原设计全部功能 + 正常服务装配 + 重启可靠 + 正式接口一致”的全套交付。工作量集中于三部分：存储和事务改造、跨模块规则贯通、可安装的 daemon/CLI/bridge 闭环。之后才是隔离驱动、复杂生命周期和研究评估的广度补齐。

下一阶段不是继续收集能力证据，也不是只修几个启动命令。按[六个实施包](implementation-plan.md)完成 M1 后，才能称为独立运行的最小成品；原设计其余范围作为 M2/M3 清楚列出，不用未验证的百分比替代交付事实。
