# A/B/C/D 实验报告状态

状态：`not_run`。本仓库目前只有实验定义和运行计划，没有可用于宣传的实测结果。

实验臂固定为 A 单 Agent、B 多 Agent + Worktree、C 完整认知协作、D 无认知协调。每组至少 5 次，正式多 Agent 组至少 3 个 Agent；任务集、预算、模型版本、宿主版本和随机顺序必须锁定。指标包括正确性、硬分歧检出、误阻塞、intervention、rework、wall time 和 token availability。

准备计划：

```powershell
uv run python tools/experiments/prepare.py --replicates 5 --output .tsunagou/evaluation/plan.json
```

准备器输出 `planned_no_results`，并为所有 20 个运行生成唯一 run identity。宿主、模型、协议和配置仍是锁定前占位符；禁止把它们当作实验数据。`unavailable` token 不等于零，失败样本不能删除。

只有报告同时公开样本数、原始 result refs、统计方法、限制和另一宿主复验情况后，才能评估 C 相对 B 的门槛：正确性 100%、硬分歧检出至少 95%、误阻塞不超过 5%、intervention/rework 中位数改善至少 30%、总耗时增加不超过 10%、可比 token 增加不超过 25%。达不到或样本不足时报告限制，不宣称效果。
