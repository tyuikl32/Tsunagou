# R3 实施步骤与交接

先读 [PRD](prd.md)、[design](design.md) 和 implement.jsonl。以下拆自独立成品方案，不表示已经修改代码。

## 启动

先确认 R2 的全部验收条件通过。

```powershell
python .trellis/scripts/task.py validate .trellis/tasks/09-20-r3-task-ownership
python .trellis/scripts/task.py start .trellis/tasks/09-20-r3-task-ownership
```

## 实施顺序

最小故障：worker可block/resume别人的任务；HTTP绕过编排start；失败响应后Task已running。

实施：

1. 增加Task执行scope、验收policy和依赖等原设计字段；draft→ready→open分别对应独立命令；保留父任务导航与blocks依赖的区别。
2. `block/resume/progress/submit`必须核对当前owner/session/attempt/epoch。resume只恢复原owner的可恢复Attempt；换owner走明确recovery/succession，不能在resume里偷偷new Attempt抢占。
3. 统一为一个PreflightResult：preflight_id、attempt_id、input_digest、各领域revision、blockers、有效状态。删除两个同名但不同含义的事实来源。
4. HTTP handler只调TaskExecutionWorkflow。start事务内重新读取owner、scope、reports、契约、blocker、workspace、完整Lease；必需项缺失就是blocked，不能默认True或`None`视为ready。
5. 全部检查成功后同事务写Task/Attempt running、execution Grant、事件。attempt不匹配等失败必须零副作用。preflight不是永久许可。
6. block/submit/cancel/会话结束在同事务撤执行Grant、释放Lease、更新Attempt。block必须保存SuspensionSnapshot；用户等待不设deadline，不周期改failed。
7. submit固化TaskResult和ReviewRound；指定reviewer获得R/task_review Grant。用户CLI不借main token代执行；main只有被指定reviewer才可accept。changes_requested关闭旧Attempt，重新发布创建新Attempt。

出口：F03/F06–F09解决；运行中并发claim最多一owner；错误身份、陈旧版本/epoch被拒；任务可走到completed，项目仍active，等待用户整体确认。

## 验证与调试

1. 对照 F03/F06-F09 通过公开入口重现越权与部分写入，断言状态及关联表没有变化。
2. 并发 claim、陈旧 preflight、依赖 revision 变化、缺 Lease、错误 attempt 的用例必须落到同一个生产 workflow。
3. 覆盖 running→blocked→resume、submit→review.accept、request_changes→新 Attempt；验证项目仍 active。

相关检查入口：

```powershell
uv run python -m pytest -q
corepack pnpm run check
corepack pnpm exec vitest run
python tools/docs/validate_docs.py
```

按实际变更运行对应 lint/type/schema 检查。本轮仅建任务，以上不是已通过的实现验收记录。

旧审计器若因协议变化不能运行，需迁移行为断言到正式入口测试，不能删除失败项后声称完成。

## 交接记录

- [ ] PRD 逐项通过，记录真实命令、退出码、公开查询和数据库事实。
- [ ] 公共接口同步 Schema、registry、生成类型、fixtures 与操作文档。
- [ ] 拒绝用例零部分写入；持久化改动经过重启验证。
- [ ] 记录修改文件、兼容处理、后继依赖和剩余范围，清除成功占位。
- [ ] 验收通过后更新任务/机器计划；按用户授权处理 Git，不自动提交或发布。

实际实现结果（2026-09-21）：任务 create draft、ready/publish、claim、owner/preflight/start、submit/review、user-decision blocker、lease/workspace 前置和 worker 越权拒绝已接入 dispatcher，并在 Python M1 集成与双 bridge MCP smoke 中通过。补充接入主 Agent `root.manage` Grant、`root.register`/`root.bind`/`repository.register` 和 roots/repositories 查询；`tests/integration/test_m1_runtime_flow.py::test_main_can_register_bind_and_query_multiple_project_roots` 通过。

本轮继续接入并验证：`task.update_plan`、`task.edge.add/remove`、`task.cancel_request/ack`、`task.fail`、`task.recover`、`task.scope.request/resolve`、`task.self_accept`。恢复会释放旧 attempt 的 Lease 并撤销执行 Grant，scope 请求核对 `task`/`scope` revision；任务提供可选的结构化 execution scope，resource intent 按 root/path 前缀和 mode 校验子集；公开入口证据为 `test_task_recovery_cancel_scope_and_plan_actions_are_public_and_owner_scoped` 与 `test_task_execution_scope_rejects_resource_outside_declared_prefix`。

本轮已收敛执行路径：`TaskExecutionWorkflow` 现在是 dispatcher handler 使用的唯一 preflight/start 编排，持久 `tasks.PreflightResult` 同时保存 digest、各领域 revision、evidence 和 blockers；陈旧契约或输入会在 running 前拒绝且不产生 Grant。`Task.block` 会保存 `SuspensionSnapshot`，并随 SQLite 快照恢复。指定 reviewer 的 `request_changes` 现在会同时关闭旧 Attempt、释放 Lease、撤销旧 execution Grant，下一次执行必须重新 claim/preflight/start。证据为 `test_m1_task_workspace_review_and_user_completion_survive_rebuild`、`test_stale_preflight_and_blocked_resume_never_auto_start`、`test_review_changes_requested_closes_execution_lease_and_grant` 和 `test_runtime_maintenance`。R3 尚需完整公共审查矩阵和全量 M1 故障门禁后再关闭。
