# FX2 实施顺序与验证

前置：FX1 已通过、用户已授权。下面步骤已经实施；最终结果见 [实施记录](implementation-progress.md)。

## 按文件推进

1. 阅读 modules/resources.py、tasks.py、workspaces.py、coordination.py、application/workflows/task_execution.py、handlers.py、platform/state.py、maintenance.py；搜索全部 renew/expire/worker.ready 调用，形成删除清单，区分 Job lease。
2. 改资源占用模型和冲突判断，增加 release 原因/时间；删到期扫描、进度续租及 lease_guidance。同库恢复保留 owner/占用，撤销旧 Grant。测试显式回收 claimed/running 及 expected_attempt_id。
3. 将工作区决策归属 task；基线仍归属 Attempt。将 main 选择输入与 Worker 实际执行上下文对应，原 main Git 权限不变。
4. 在现有 workflow/handler 实现 begin；UoW 完成或整体回滚。测试资源冲突、无效工作区、中途异常和响应丢失，不另造准备状态机。
5. 扩展 submit 自动收集 workspace.result；block/fail/cancel/recover 同事务释放与撤权。审查继续调用既有 TaskService.review。
6. 删除 worker.ready 及 coordination 重复执行状态；保留定向分派约束，将依赖投影归到 Task。实现 required_contract_ids 明确关联，删除全项目契约摘要。
7. 同步 docs/implementation/command-catalog.md、protocol/schemas/commands/、registry、生成物、CLI router、bridge 工具和 runtime prompts。正常 Skill 改为读任务→begin→工作→submit，不残留分步续租提示。
8. 更新任务/资源/工作区/认知模块文档、CLI 手册和首次验收操作文档；明确这些在代码实现完成后才生效，不把设计命令写成已经测试通过。

## 自动验证

优先修改已有 tests/unit/test_resources.py、test_tasks.py、test_task_execution.py、test_workspaces.py、test_runtime_maintenance.py、test_coordination.py、test_coordination_reliability.py。废弃 test_submit_lease_reliability.py / test_lease_assignment_sync.py 中原到期语义，但保留转化后的并发与事务性质断言。

新增 tests/integration/test_execution_begin.py，通过真实应用命令路径测试：

- 两个 Worker 同时 begin，同 task 或重叠写范围只有一人成功；无半套占用。
- 可控时钟跨越旧 120 秒及很长静默仍能 submit；Job 的内部超时仍有效。
- 模拟基线采集失败不遗留新 Attempt/Grant；重试成功只有一个 Attempt。
- 同库重启不改 owner；旧 Grant 拒绝、原 owner begin 恢复、他人拒绝；main 回收后新 owner 可执行。
- 主 Agent 只选一次隔离策略，新 Attempt 基线反映其开始时实际文件内容。
- 无关契约改变不影响 begin；明确 required 的契约不满足时阻塞；非 required 的撤销历史不阻塞。
- 无 worker.ready 也能执行；错误 assigned worker、未完成的真实任务依赖仍拒绝。
- submit、挂起和取消各只产生一次终态，资源/Grant/事件一致。

PowerShell，D:\Tsunagou：

```powershell
.\.venv\Scripts\python.exe tools/codegen/generate_protocol.py
.\.venv\Scripts\python.exe tools/codegen/validate_protocol.py
.\.venv\Scripts\python.exe -m pytest tests/unit/test_resources.py tests/unit/test_tasks.py tests/unit/test_task_execution.py tests/unit/test_workspaces.py tests/unit/test_runtime_maintenance.py tests/unit/test_coordination.py tests/integration/test_execution_begin.py tests/integration/test_state_integrity.py -q
corepack pnpm -r run check
corepack pnpm exec vitest run
.\.venv\Scripts\python.exe tools/dev/check_architecture.py
.\.venv\Scripts\python.exe tools/docs/validate_docs.py
```

## 真进程验证与完成条件

在全新临时项目状态启动 daemon，使用两个独立 Worker 身份实际 begin/submit；中途正常停止再启动同库 daemon。记录 E1–E8 对应命令、返回、退出码、起止 UTC 时间和事件引用。长静默用可控时钟单测证明，不要求模型空转等待。

实际新命令的 CLI help 与 PowerShell 示例在本任务实施时补入用户验收文档。测试不能依靠直接修改 SQLite、替代 owner 或人工恢复状态通过。此任务完成不表示 Desktop 唤醒已经完成；后者仍是 FX-D03 的独立必达验收。
