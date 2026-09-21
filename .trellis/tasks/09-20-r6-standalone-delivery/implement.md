# R6 实施步骤与交接

先读 [PRD](prd.md)、[design](design.md) 和 implement.jsonl。以下拆自独立成品方案，不表示已经修改代码。

## 启动

先确认 R5 的全部验收条件通过。

```powershell
python .trellis/scripts/task.py validate .trellis/tasks/09-20-r6-standalone-delivery
python .trellis/scripts/task.py start .trellis/tasks/09-20-r6-standalone-delivery
```

## 实施顺序

实施：

1. Python wheel包含协议资源和CLI入口，Node产物有可启动的stdio bridge，lockfile冻结；提供一条安装命令和真实help。
2. 从任意cwd启动daemon；endpoint manifest包含instance/PID/port/start time，control secret另存用户私有文件。默认随机空闲loopback端口，日志不含secret。
3. 新增`tools/dev/smoke_standalone.py`与`tests/integration/standalone/`，测试只走CLI/HTTP/MCP公开入口，不直接new领域服务。包含下节所有M1断言。
4. 故障测试运行真实子进程：commit前kill、commit后响应前kill、Job物化中断、重复消息、旧会话/epoch、两个writer、用户未回复、文件在检查点间变化。
5. 独立临时venv安装wheel，断开源码导入路径，运行同一场景；打包脚本不能靠本机editable install补齐文件。
6. 改`doctor`为真实配置/DB/锁/任务恢复结果；未实现命令退出明确错误。最终用户文档中的命令逐条执行一次，并记录结果。

出口：M1的全部功能断言通过；没有任何“打印成功但未落库”的路径；用户能按操作单完成协作及重启恢复。宿主正式支持与实验报告单列，不参与此判断。

## 验证与调试

1. 逐项执行总方案第 6 节全部 12 条完成断言；使用真实 HTTP、CLI 和 MCP，不调用领域私有方法。
2. 在全新 venv、源码树以外重复相同场景；分别注入 commit 前后进程退出、Job 中断、重复消息与旧 epoch。
3. 执行锁定依赖安装及相关全量回归；操作单按干净环境逐条运行并登记输出，不能沿用旧审计数字当新结果。

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

实际实现结果（2026-09-21）：`tools/dev/package_smoke.ps1` 已可重复构建 wheel 和 bridge npm 包，在源码树外新 venv/临时目录安装、读取包内协议资源并启动 bridge；本次命令退出0，证据见 `docs/standalone/package-smoke-2026-09-21.json`。双 bridge MCP 烟测脚本位于 `packages/bridge-server/scripts/smoke-two-bridges.mjs`，完整公开入口烟测位于 `tools/dev/smoke_standalone.py`，首轮协作、真实测试、baseline conflict、用户确认、旧 execution grant 拒绝和重启恢复证据见 `docs/standalone/bridge-two-session-smoke-2026-09-21.json` 与 `docs/standalone/m1-public-smoke-2026-09-21.json`。checkpoint 物化失败保留 completed 结论并可重试，集成测试见 `docs/standalone/checkpoint-failure-2026-09-21.json`。`tools/dev/commit_window_process_smoke.py` 现在用真实 daemon 子进程覆盖 commit 前退出和 commit 后响应丢失，两种场景都能重启并按同一 command_id 重放；确定性注入的回归仍由 `test_sqlite_commit_before_response_replays_original_result` 覆盖。常驻维护会回收过期 Job lease，公共 jobs 查询和 `test_expired_job_lease_is_recovered_without_executing_effect` 已通过；主动 Job runner 中断、完整操作单和真实宿主基线仍未全部通过，因此任务保持 planning。
