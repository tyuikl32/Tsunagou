# M1 实施路线图与 Trellis 任务

更新：2026-09-21。开发者 **tyuikl32**，平台 **Codex**。M1 十二条最小产品标准已通过；R1-R6 仍作为完整原设计的后续实施包保留，R3 当前为 in_progress，其余 follow-on 按剩余门禁推进。

目标是交付可独立安装、启动、协作、持久保存和重启恢复的本机代码。范围、接口、数据和完成条件见[实施方案](../standalone/implementation-plan.md)，实际差距见[八模块审计](../standalone/status-and-gaps.md)，逐步调试见[操作执行单](../standalone/debugging-runbook.md)。宿主能力报告和研究实验不作为 M1 的前置条件。

## 当前任务

总任务：[M1 独立运行最小成品](../../.trellis/tasks/09-20-tsunagou-m1/prd.md)。机器索引：[task-plan.json](task-plan.json)。

| 任务 | 交付 | 前置 |
|---|---|---|
| [R1 协议与独立安装入口](../../.trellis/tasks/09-20-r1-protocol-package/prd.md) | 可独立安装的 wheel，内含 registry、Schema、OpenAPI，读取不依赖源码目录 | 无 |
| [R2 常驻 daemon、统一 SQLite 和真实 CLI](../../.trellis/tasks/09-20-r2-runtime-storage-cli/prd.md) | 唯一 ProjectRuntime、daemon lifespan、进程寿命锁、单 writer 和模块 SQL repository | R1 |
| [R3 任务状态机与主从边界](../../.trellis/tasks/09-20-r3-task-ownership/prd.md) | 完整 draft/ready/open/claimed/running/blocked/submitted/review 相关命令语义和持久 Attempt | R2 |
| [R4 认知、资源与工作空间闭环](../../.trellis/tasks/09-20-r4-coordination-loop/prd.md) | 可持久查询的报告、分歧、契约及同 proposal digest 接受流程 | R3 |
| [R5 Agent 接入、用户决定与恢复](../../.trellis/tasks/09-20-r5-agent-user-recovery/prd.md) | bridge-server 复用 bridge-sdk 的生成工具、逐动作幂等 ID、精确错误和自动读取同步 | R4 |
| [R6 封装、回归与独立交付](../../.trellis/tasks/09-20-r6-standalone-delivery/prd.md) | 可交付 Python wheel/Node bridge 产物、任意 cwd daemon 发现和真实 doctor | R5 |

顺序为 **R1 → R2 → R3 → R4 → R5 → R6**。每个任务含 PRD、design、implement、实施/检查 JSONL，明确范围、文件责任、执行步骤、拒绝场景和完成标准。依赖同时登记在 task-plan 与 meta.depends_on；Trellis parent/children 只分组，不负责调度。M1 已按十二条标准关闭；R1-R6 的剩余项不得回写为 M1 已支持能力。

## 八模块覆盖

| 模块 | 主要实施任务 |
|---|---|
| projects | R2 项目/权限持久化，R3 授权边界，R5 用户决定/完成 |
| agents | R2 身份/消息持久化，R5 bridge 接入/恢复 |
| tasks | R2 持久化，R3 状态机/owner/preflight/审查 |
| cognition | R2 持久化，R4 报告/分歧/契约 |
| resources | R2 持久化，R3 执行事务，R4 Lease/冲突/过期 |
| workspaces | R2 持久化，R4 真实 shared 基线/结果 |
| durability | R2 事务/幂等/Job，R4 附件，R5 checkpoint |
| evaluation | R2 持久化基础，R5 审计投影与查询 |

R1 为所有模块提供协议与安装资源，R6 验证八模块共同组成独立程序。两个阶段均不新增业务模块。

## 下一步命令

在仓库根目录执行：

```powershell
python .trellis/scripts/task.py list
python .trellis/scripts/task.py validate .trellis/tasks/09-20-r1-protocol-package
python tools/docs/validate_docs.py
```

前三条检查任务与文档。R1/R2/R5/R6 已有部分实现但尚未自动改成 completed，需按各自 `implement.md` 补足剩余门禁后再关闭；R3 已启动并记录当前实现证据，R4 应在 R3 前置验收后开始。需要进入某个任务时，再在 Codex/Trellis 有会话身份的终端执行 `python .trellis/scripts/task.py start <task-dir>`；无身份时报错应按提示恢复会话上下文，不能跳过上下文校验。

每项完成后把真实命令/退出码/行为结果写入 implement.md，并更新任务状态与机器索引。启动下一项前重读该任务上下文。任务 Git 自动提交关闭，不在本轮提交或发布。

## 旧任务处置

用户明确要求此前所有 Trellis 任务视为完成或放弃。2026-09-20 将当时仍在活动目录的 25 个旧任务全部移入 archive/2026-09：

- T01–T17、T22：18 个，保留 completed 与原完成时间，仅代表历史分项交付。
- T18–T21、T23–T24、旧 V1 总任务：7 个，标记 cancelled，closure.disposition=abandoned；未通过的验收不冒称完成。
- 此前已归档的 bootstrap-guidelines、docs-onboarding-manual 继续保留完成状态。

[逐项迁移清单](../standalone/trellis-transition-2026-09-20.json)、[旧机器计划](task-plan-legacy-2026-09-18.json)、[旧路线图](roadmap-legacy-2026-09-18.md)保留追溯。旧代码、设计、研究没有删除，但旧计划不参与当前任务依赖或完成判定。尚未排期的完整设计能力见实施方案 M2/M3，不能继续当作活动旧任务。

## M1 总关闭标准

六项全部验收通过后，R6 从源码树外的独立安装产物执行完整流程：初始化 → 两个独立会话 → 任务/认知协商 → 资源与真实文件执行 → 提交审查 → 用户确认 → 重启恢复。必须同时通过越权拒绝、事务回滚、幂等、旧 epoch 和文件变更检查，且用户操作单逐条可执行。当前任务整理完成不等于 M1 产品完成。
