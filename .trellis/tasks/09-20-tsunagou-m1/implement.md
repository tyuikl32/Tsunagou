# M1 推进与关闭

## 当前状态

M1 十二条最小产品标准已通过；旧任务已关闭归档。R1-R6 保留为完整原设计的后续实施包，不能把 follow-on planning 误报为 M1 未运行。

## 执行顺序

1. [R1](../09-20-r1-protocol-package/implement.md)：可独立安装的 wheel，内含 registry、Schema、OpenAPI，读取不依赖源码目录。逐项验收后进入下一任务。
2. [R2](../09-20-r2-runtime-storage-cli/implement.md)：唯一 ProjectRuntime、daemon lifespan、进程寿命锁、单 writer 和模块 SQL repository。逐项验收后进入下一任务。
3. [R3](../09-20-r3-task-ownership/implement.md)：完整 draft/ready/open/claimed/running/blocked/submitted/review 相关命令语义和持久 Attempt。逐项验收后进入下一任务。
4. [R4](../09-20-r4-coordination-loop/implement.md)：可持久查询的报告、分歧、契约及同 proposal digest 接受流程。逐项验收后进入下一任务。
5. [R5](../09-20-r5-agent-user-recovery/implement.md)：bridge-server 复用 bridge-sdk 的生成工具、逐动作幂等 ID、精确错误和自动读取同步。逐项验收后进入下一任务。
6. [R6](../09-20-r6-standalone-delivery/implement.md)：可交付 Python wheel/Node bridge 产物、任意 cwd daemon 发现和真实 doctor。逐项验收后进入下一任务。

第一项从仓库根目录运行：

```powershell
python .trellis/scripts/task.py list
python .trellis/scripts/task.py validate .trellis/tasks/09-20-r1-protocol-package
python .trellis/scripts/task.py start .trellis/tasks/09-20-r1-protocol-package
```

## 总体验证

逐项执行[调试执行单](../../../docs/standalone/debugging-runbook.md)的修复后场景和 PRD 的 12 条标准。R6 生成安装包并在干净环境重复。执行单 A 是现状复现，B 仍为待交付命令，不可提前报告通过。

```powershell
uv run python -m pytest -q
corepack pnpm run check
corepack pnpm exec vitest run
python tools/docs/validate_docs.py
```

按实际变更运行对应 lint/type/schema 检查。本轮仅建任务，以上不是已通过的实现验收记录。

## 关闭

- [ ] 六个子任务真实实现与验收完成。
- [ ] wheel/bridge 在源码树外完成协作闭环。
- [ ] 故障、越权、幂等、重启、用户等待断言通过。
- [ ] 操作步骤逐条运行并记录；列出 M1 与完整设计的剩余差距。
- [ ] 写入实际结果再更新总任务；遵守用户已有 Git 授权，不自动提交或发布。

实际实现结果（2026-09-21）：R1/R2 的 wheel、协议资源、daemon、SQLite、CLI、bridge 独立启动和 16/16 standalone audit 已通过；R3/R4 补入任务恢复/scope/依赖边界、结构化 execution scope、认知分歧处置、契约拒绝/撤回、checkpoint retry、physical root alias 和基础 audit 查询，Python 110、Vitest 29、TypeScript、Ruff、协议与文档校验均通过。公开 smoke 已覆盖两个独立 bridge、真实文件测试、review、用户决定、项目完成、真实 daemon checkpoint 失败查询与 CLI retry、重启后的 tasks/attempts/results/jobs/agents/cognition/contracts/messages/workspaces/decisions/audit 查询和旧执行权拒绝；`request_changes` 会释放旧 Lease 并撤销旧 execution Grant。真实 daemon 提交窗口前/后退出重放、源码树外 wheel/npm 安装也已通过。M1 十二条标准已通过；R1-R6 中完整 workflow/风险矩阵、主动 Job runner、真实宿主基线、worktree/external 与完整协议矩阵保留为 follow-on。详见 `docs/standalone/m1-acceptance-2026-09-21.json`。
