# PT1–PT7 非破坏性整体验收执行单

本执行单验证当前 Tsunagou 源码和临时项目，不会接触真实用户项目，不会撤销凭据，不会确认恢复计划，也不会提交 Git。执行目录固定为 `D:\Tsunagou`；PowerShell 中遇到错误立即停止。

## 1. 预检

```powershell
Set-Location D:\Tsunagou
$ErrorActionPreference = 'Stop'
uv sync --locked --extra dev
git status --short
& .\.venv\Scripts\python.exe --version
```

`python --version` 应满足仓库 `pyproject.toml` 的 Python 3.13 约束。工作树可以有本轮未提交改动，但必须保存输出，不能把未提交改动误报成已发布版本。

## 2. 运行临时项目审计

下面命令初始化临时 Git 项目、启动 loopback daemon、建立两个后端测试 Agent、执行 A2A 消息幂等、任务边界、认知/契约、重启恢复和 CLI ticket 可见性测试，结束后自动删除临时项目。

```powershell
$audit = Join-Path (Get-Location) 'docs/standalone/persistence-traceability-runtime.json'
& .\.venv\Scripts\python.exe tools/dev/audit_standalone.py --output $audit
if ($LASTEXITCODE -ne 0) { throw "runtime audit failed: $audit" }
$runtime = Get-Content -Raw $audit | ConvertFrom-Json
$runtime.checks | Format-Table check,passed,observed -AutoSize
```

结束标准：`failed=0`、`a2a_failed=0`、退出码为 `0`。报告中的 `handler_coverage.missing` 是尚未注册的未来 command catalog 项，不属于本次 M1/PT1–PT7 查询和留痕门；不能把它改成 `supported` 来消除报告。

## 3. 运行完整非破坏性门禁

```powershell
$report = Join-Path (Get-Location) 'docs/standalone/persistence-traceability-acceptance.json'
& .\.venv\Scripts\python.exe tools/dev/persistence_acceptance.py `
  --audit-report (Resolve-Path $audit).Path `
  --output $report
if ($LASTEXITCODE -ne 0) { throw "acceptance gates failed: $report" }
Get-Content -Raw $report | ConvertFrom-Json | Format-List
```

脚本记录 `started_at`、`finished_at`、源码 `HEAD`、daemon 版本、schema bundle digest、每条命令的退出码和最后三行安全输出。默认还执行 bridge-server 的 pnpm build/check；Node 依赖不可用时可明确使用 `--skip-node`，报告必须保留该事实，不能称为完整门禁通过。

## 4. 查询与诊断复核

先启动一个临时项目 daemon，按[CLI/HTTP 手册](../overview/cli-http-manual.md)取得 `$projectId` 和 `$baseUrl`，再使用控制凭据查询：

```powershell
uv run python -m tsunagou project history $projectId --limit 200 --json
uv run python -m tsunagou project diagnostics $projectId --json
uv run python -m tsunagou checkpoint list $projectId --verify
```

单事件和任务展开需要从上一条 JSON 中取得真实 ID：

```powershell
uv run python -m tsunagou task history TASK_ID --project-id $projectId --limit 100 --json
uv run python -m tsunagou audit event EVENT_ID --project-id $projectId --include-evidence --json
uv run python -m tsunagou checkpoint verify CHECKPOINT_DIGEST
```

应看到：

- history 返回 `projection_version`、`as_of_event_seq`、`next_cursor` 和 UTC 毫秒时间；未知旧时间显示 `null`/`unknown_time`。
- task history 只包含该 task 的 task/attempt/result/workspace/report/contract 和当前调用者可见的 message 关联。
- diagnostics 中的 `callback_received`、`wake_requested`、`thread_*`、`turn_*`、`agent_presented`、`wake_unknown` 是独立证据；callback 2xx 不等于 turn 已执行。
- checkpoint verify 在无 Git 项目中也能验证 manifest/文件摘要，`git_anchors=[]`；有 Git 时只接受本地 heads/tags 的实际 tree 内容。
- 查询不新增 SQLite event、operation、revision。可在查询前后比较 `state.sqlite3` 的 `last_event_seq` 或 history 的 `as_of_event_seq`。

## 5. 失败定位与回滚边界

| 现象 | 处理 |
|---|---|
| `daemon_unreachable` 或 health 超时 | 读取临时项目 `.tsunagou/local/endpoint.json`、daemon 日志；确认没有第二个进程占用同一项目，不连接真实项目。 |
| history 401/403 | 不替换 Agent token；确认 CLI 读取当前临时项目的 user control token，重新运行 `doctor`。 |
| invalid/expired cursor | 使用相同 filters 重新从首屏查询；daemon 重启后游标必须重新获取。 |
| checkpoint verification failed | 先保留 manifest 和报告；不要手工修改 `current.json` 或覆盖 checkpoint；检查本地 Git 是否真的包含 manifest/tree。 |
| diagnostics 为空 | 说明 managed host wake 未启用或该次消息未请求 push/wake；durable inbox pull 仍是有效恢复路径。 |
| Node gate 失败 | 保留失败命令、Node/pnpm 版本和报告；不要使用 `--skip-node` 后报告“全部通过”。 |

PT7 不在这个执行单中执行 `daemon migrate-credentials --confirm-plan-digest`、`project restore --confirm-plan-digest`、真实项目停写、旧 session 撤销或任何真实项目删除。上述动作必须由用户另行明确授权，并使用专门备份/回滚计划。

## 6. 关闭标准

只有下面条件同时成立，才可以把 PT1–PT7 和父任务标记完成：

1. runtime audit `failed=0`、`a2a_failed=0`，并保存报告路径和时间。
2. `persistence_acceptance.py` 所有启用 gate 的退出码为 `0`；若跳过 Node，父任务保持未完成。
3. `uv run python tools/docs/validate_docs.py`、Trellis task validation、protocol/architecture checks 通过。
4. 无秘密进入验收 JSON、CLI 输出、audit export、diagnostics 或 checkpoint 公共文件；秘密扫描结果只记录通过/失败，不保存秘密值。
5. 真实项目字段仍为 `real_project_touched=false`、`credential_migration_or_restore_confirmed=false`；真实项目迁移另行留痕。
