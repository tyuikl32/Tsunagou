# FX2 合并执行入口并删除资源续租

状态：completed；2026-09-28。承接 FX-R01/02，依赖 [FX1](../09-28-fx1-state-integrity/prd.md)。E1–E8 的实际证据见 [实施记录](implementation-progress.md)，Desktop 完整实测仍单列 FX3/FX6。

## 目标与证据

普通 Worker 一次开始取得执行上下文，一次提交交付结果；长推理无需续租，恢复无需 main 重复选择工作区。

本轮 11 次领取、11 次 workspace.select、12 次 lease.expired，11 个 Attempt 中 9 个 orphaned。源码以 src/tsunagou 为根：resources.py:78 默认 120 秒；application/handlers.py:553、:913 以 worker.ready 阻挡领取及占用；application/workflows/task_execution.py 把全项目契约加入摘要；platform/state.py:537 同库重启释放占用并重开任务。

## 需求与验收

| 编号 | 结果及验收 |
| --- | --- |
| E1 | 删除资源 TTL 和模型/运行层续租；时间经过、断线及同库重启不抢走 owner |
| E2 | 一次 begin 完成领取、基线、占用、机械检查及授权；冲突失败不遗留新占用、Grant 或重复 Attempt |
| E3 | scope 与策略不变时复用 main 的工作区选择；新 Attempt 采集新基线；Git 仍由 main 控制 |
| E4 | 一次 submit 完成结果采集与提交，释放占用、撤执行权，等待 main 审查 |
| E5 | 合法 Worker 稍后加入仍能领取，无额外 ready 回执门槛；任务依赖和 owner 有效 |
| E6 | 只检查明确列为该任务必要条件的契约；无关协商不打断执行；不强迫每项任务提交认知报告 |
| E7 | main 回收后另一 Worker 可开始，旧 Attempt 不能提交；同 owner 重启恢复不重复创建 Attempt |
| E8 | CLI/HTTP/MCP 共用编排，无用户修 session、机械审批和多步 preflight 仪式 |

## 边界

遵守 FX-D01/02，无旧接口兼容或迁移。保留身份、owner、scope、版本、幂等、真实资源冲突与用户专属权限。后台 Job 内部超时不变。

设计见 [design.md](design.md)，实施见 [implement.md](implement.md)。
