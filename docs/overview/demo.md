# 演示与成功标准

演示应回答：多个 Agent 是否能够在分歧中继续可靠协作，而不仅是同时输出代码。

## 十分钟主线

| 场景 | 展示内容 | 可核验结果 |
|---|---|---|
| 初始化与身份 | 一个协调仓库、额外根目录、主 Agent 和两个子 Agent | 独立 HostSession；子 Agent 任命主权限请求被拒绝 |
| 并行任务 | API 与调用方任务、依赖关系、claim | 同任务并发 claim 只有一个 owner |
| 显式理解差异 | 两份报告针对同字段作不同声明 | Discrepancy 与参与者都可查询 |
| 契约协商 | 所有人接受同一 schema proposal | 相同 digest；旧版本接受不生效 |
| 等待用户 | 主 Agent 发出重大设计 UserDecision | 相关任务挂起、无关任务继续；等待不自动失败 |
| 恢复 | 重启 bridge/daemon，重复提交同 command_id | 无消息丢失、无重复业务动作、旧 epoch 拒绝 |
| 完成 | 用户确认项目完成，展示 checkpoint 状态 | completed 与 durability pending/failed 分开可见 |

四个 adapter 各有共同基线真宿主记录。可以在主线使用其中两个，但不能借此宣称其余两个已实测。

## 两种验收

**工程交付门槛**：协议 fixtures、权限矩阵、原子 claim、断线防重放、持久消息、契约哈希、资源冲突、Operation 不确定结果、checkpoint 恢复等都通过自动化验证；Windows 为发布阻断平台。macOS/Linux 按已支持范围单列结果。

**研究效果门槛**：A 单 Agent、B 多 Agent + Worktree、C 完整系统、D 去掉认知协调，统一任务、预算和宿主；每组至少五次，正式多 Agent 组至少三个 Agent，随机化顺序，再用另一个宿主复验。正确性测试全部通过；注入的硬分歧识别率至少 95%，误阻塞率不超过 5%；C 相对 B 的人工干预和返工中位数减少至少 30%，耗时增加不超过 10%，可比 token 消耗增加不超过 25%。

这些是目标，尚无实测结果。缺少 tokenizer 或账单数据标为 unavailable，不能填零。未达到研究效果时公开结果与限制，即使工程功能已可用也不能宣称目标达成。

运行报告应包含宿主/模型/adapter/schema 版本、配置摘要、任务集、样本数、原始结果引用及失败样例，不保存隐藏思维链或凭据。详细方案见[验证与交付](../implementation/validation.md)。
