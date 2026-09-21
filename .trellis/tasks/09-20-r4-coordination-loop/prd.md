# R4 认知、资源与工作空间闭环

状态：planning（实施计划就绪，产品修改未开始）。负责人：tyuikl32；平台：Codex；优先级：P0。

上级：[M1](../09-20-tsunagou-m1/prd.md)。前置：R3。历史责任关联：T09, T10, T11, T12, T13（已归档，不作为启动依赖）。

范围来源：[独立运行实施方案](../../../docs/standalone/implementation-plan.md)、[当前缺口](../../../docs/standalone/status-and-gaps.md)、[路线图](../../../docs/implementation/roadmap.md)。多宿主正式认证和研究实验不作为本任务关闭条件。

## 交付内容

- 可持久查询的报告、分歧、契约及同 proposal digest 接受流程
- 真实 scope/物理路径冲突和整组 Lease 获取、续租、过期处理
- 明确选择的 shared workspace 基线/结果、真实 patch 附件与同快照黑板

## 验收条件

- [ ] main 和 worker 提交相同 subject 的不同理解，经显式协商后接受同一契约；缺接受或旧 proposal 不能 start
- [ ] 跨项目/无关报告不能挂接；superseded 报告不冒充当前理解；重启保留关联及接受状态
- [ ] alias 指向同一路径时仍冲突，整组 acquire 失败零授予；过期处理原子撤权并通知
- [ ] shared prepare 实际扫描 roots/Git/文件并由 Job 完成；未实现的隔离模式明确拒绝
- [ ] 实际修改文件后 workspace.result 有 changed paths/patch/hash/验证引用，TaskResult 只引用当前 Attempt 的有效结果
- [ ] 用户手动改文件在下次检查点出现观察或冲突，不推断作者、不回滚用户改动；无关任务可继续
- [ ] blackboard 来自同一读快照；附件和私信读取遵守领域授权

## 实施边界

保持主 Agent 控制 Git、用户重大确认、逐会话身份和领域所有权。代码只维护结构、状态、范围和版本不变量，语义协调由主 Agent 完成。不得返回占位成功、绕开所有权检查或伪造宿主 supported 状态。

文件责任见 [design](design.md)，执行和交接见 [implement](implement.md)。公共变更同步实施方案、Schema/registry、fixtures 与用户文档。
