# R3 任务状态机与主从边界

状态：planning（实施计划就绪，产品修改未开始）。负责人：tyuikl32；平台：Codex；优先级：P0。

上级：[M1](../09-20-tsunagou-m1/prd.md)。前置：R2。历史责任关联：T06, T08, T13, T15（已归档，不作为启动依赖）。

范围来源：[独立运行实施方案](../../../docs/standalone/implementation-plan.md)、[当前缺口](../../../docs/standalone/status-and-gaps.md)、[路线图](../../../docs/implementation/roadmap.md)。多宿主正式认证和研究实验不作为本任务关闭条件。

## 交付内容

- 完整 draft/ready/open/claimed/running/blocked/submitted/review 相关命令语义和持久 Attempt
- 唯一 PreflightResult 与 TaskExecutionWorkflow，统一身份/版本/scope/依赖检查
- 事务内授权与释放、SuspensionSnapshot、TaskResult/ReviewRound 和指定 reviewer 权限

## 验收条件

- [ ] worker 无法 block/resume/progress/submit main 或另一 worker 的任务；失败后 owner、Attempt 和授权不变
- [ ] task.create 只产生 draft；ready/publish 独立；并发 claim 最多成功一个 owner
- [ ] HTTP/CLI/MCP 转发最终经过相同 workflow；缺报告/契约/租约/workspace 或输入陈旧时不能 running
- [ ] 任何 start 失败均无新 Grant、无部分 Task/Attempt 写入；preflight 成功后改变依赖仍会被 start 拒绝
- [ ] block 保存快照并释放执行权，resume 保留可恢复 Attempt 的原 owner；等待用户无超时失败
- [ ] 指定 reviewer 验收 Task，main 非指定 reviewer 时不能代审；request_changes 关闭旧 Attempt，重新发布产生新 Attempt；Task 完成不自动完成 Project

## 实施边界

保持主 Agent 控制 Git、用户重大确认、逐会话身份和领域所有权。代码只维护结构、状态、范围和版本不变量，语义协调由主 Agent 完成。不得返回占位成功、绕开所有权检查或伪造宿主 supported 状态。

文件责任见 [design](design.md)，执行和交接见 [implement](implement.md)。公共变更同步实施方案、Schema/registry、fixtures 与用户文档。
