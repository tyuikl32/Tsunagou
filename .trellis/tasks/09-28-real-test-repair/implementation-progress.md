# FX 联合实施交接

更新：2026-09-28T15:36:30.054Z。父任务 in_progress，用户已授权全部 FX，未提交 Git。

FX1/FX2/FX7 completed；FX3/FX4/FX5/FX6 in_progress。510 Python tests passed、3 platform skips，Node 34 tests、TypeScript check/build、Ruff、mypy、架构和文档检查通过。真实业务 HTTP 9/9、WebUI Node 8/8、新 origin 的正常/CRC 损坏/截断文件页面检查通过。自动化通过不代替剩余现场场景。

详细证据：[逐项验收](../../../docs/acceptance/evidence/live-repair-20260928T150917Z/operator-review.md)、[全部偏差](../../../docs/acceptance/evidence/live-repair-20260928T125752Z/live-coordination-notes.md)。最新采集 170 条真实 span，三名原会话身份独立；main MCP ready，两名 Worker 由 daemon 原会话自动唤醒后完成业务工作。

## 当前恢复点

- 协调目录 `D:\Tsunagou-fx-live-20260928`；project `450286e4-8d1b-4220-840c-e540fe696913`。
- 尚未重启的 daemon：PID 102616，runtime `a233923d-af53-48c4-aaf2-286a004cc54e`，13:54:51.611Z 启动；后来的 queued 全 ACK 跳过等修复未在此进程加载。
- 恢复任务 `357de2e9-8990-4c1e-b99f-365057d29732`，owner Worker `e5a866e0-3c1c-4ab5-8d11-5becd613cc48`，Attempt `6c6b53f3-64b7-4f63-beb8-504276e8c8f4`，故意保持 running。main 不代用 Worker 凭据。
- 原测试服务 URL 5080 无监听；隔离业务副本服务 `http://127.0.0.1:57065/` 可实际使用。启动 5080 被命令策略拒绝，未另找启动方式绕过。
- collector 继续在本机 58561 接收 OTLP；新 daemon 需要保留 `TSUNAGOU_OTEL_ENDPOINT=http://127.0.0.1:58561/v1/traces`。

## 2026-09-28T17:48Z 当前验证边界

本轮 UserDecision 的持久内容、当前 main 通知、CLI/API 认证和公共 schema 漂移已在源码/SQLite/协议回归中修复；全量 Python 513 collected、510 passed、3 platform skips，Ruff/mypy、bridge build、OpenAPI/codegen 和文档校验通过。现场 daemon 仍保持 PID 102616/runtime `a233923d-af53-48c4-aaf2-286a004cc54e`，尚未加载这些改动。A4 的同库重启/回收拒绝与 A6 的真实用户待答、无关任务继续、原会话恢复必须在新版 daemon 上补测；不要把本节自动化结果写成现场完成。

## 下一步操作

本次工具执行 `daemon stop` 被策略拒绝；不反复改写命令绕过。用户在独立 PowerShell 中运行以下操作后，先核对 stopped/started 及新的 runtime，再继续自动验收。不要重新 enrollment、删除数据库或要求 MCP 刷新按钮。

```powershell
$cli = 'C:\Users\Tyuikl\.local\bin\tsunagou.cmd'
$project = 'D:\Tsunagou-fx-live-20260928'
$env:TSUNAGOU_OTEL_ENDPOINT = 'http://127.0.0.1:58561/v1/traces'
& $cli --project-root $project daemon stop
if ($LASTEXITCODE -eq 0) {
    & $cli --project-root $project daemon start
}
```

之后依次完成：原 owner begin 恢复同 Attempt；显式回收后旧 Attempt 提交拒绝；真实认知分歧/重大决定等待场景；处理 A7 私信证据与共享提交时间投影的目标冲突；check/export 留档，再交用户确认最终交付。保留此前失败，禁止把构建、ACK、健康查询当作完整验收。
