# 简化执行流程：可直接重跑的验收

2026-09-28 已通过 FX2 的真实 daemon/HTTP/Node MCP 测试。此操作创建全新临时 Git 项目，自动准备主/子身份；不修改现有业务项目、不注册用户 Codex MCP，也不要求填写任何 ID。

在 PowerShell 执行：

```powershell
Set-Location D:\Tsunagou
corepack pnpm --filter @tsunagou/bridge-server run build
.\.venv\Scripts\python.exe tools/dev/execution_flow_probe.py --output .trellis/tasks/09-28-fx2-execution-flow/research/my-process-probe.json
Get-Content .trellis/tasks/09-28-fx2-execution-flow/research/my-process-probe.json
```

终止标准：命令退出码 0，末行 status=passed；报告中的 task.status=completed、mcp.review_status=completed、mcp.foreign_execution_submit=rejected。脚本 finally 停止自己启动的 daemon。项目路径在末行 project_root 中，保留供检查，不自动删除文件。

实际步骤依次是：启动 daemon；两个不同 Worker 竞争同一任务（只有一个成功）；停止/启动同库 daemon；检查 owner/占用不变而旧执行权失效；原 owner begin 恢复；main 回收并转给另一 Worker；拒绝旧 Attempt 提交；写真实文件、submit、审查；两个 Node MCP 进程独立接入，从 Worker 自身 context 读任务并开始，完成认知分歧、双方契约、消息/回复、文件测试和审查。

最终已保存报告：[process-probe-final.json](../../.trellis/tasks/09-28-fx2-execution-flow/research/process-probe-final.json)。起止 UTC 为 11:46:15.936–11:46:22.834，耗时 6.898 秒。该耗时只代表自动执行测试，不是人类部署耗时或真实 LLM 工作耗时。

正常 Agent 路径已经改为：读 context/inbox → task__begin → 工作 → task__submit。文件任务由 main 发布前 workspace__select 一次。无需 resource.acquire/renew、worker.ready 或单独 workspace.result。挂起时 owner task__block 释放占用；main 可显式 task.recover 回收。没有时间驱动的 owner 失效。

这项测试不证明原 Codex 聊天被 daemon 唤醒；FX3/FX4/FX6 仍需完成实际宿主接入及两个原会话自动协作。详见 [总计划](../implementation/live-test-repair-plan.md)。
