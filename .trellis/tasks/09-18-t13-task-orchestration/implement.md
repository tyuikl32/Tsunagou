# T13 执行步骤与交接

## 开始前

- [x] 检查依赖 T07, T09, T10, T11, T12 的完成证据，读取本任务 PRD/design/上下文与对应 Trellis spec。
- [x] 检查工作区现有改动，确认Schema/端口已有产物和版本；不得覆盖用户改动。
- [x] 使用 task.py start 显式开始；现在任务保持planning，不自动运行产品实施。

## 实施步骤

- [x] 将所有模块证据组成带revisions/digest的PreflightResult
- [x] 实现claimed/start原子核验及Grant签发、submit撤权/Lease和review
- [x] 实现block保存快照、resume重新准备，相关scope blocker与无关工作继续
- [x] 完成两Agent显式分歧→契约→任务结果的持久端到端场景

## 检查

- [x] 任何输入变更使旧preflight失效，无半启动
- [x] blocked仍可报告/协商但不能执行
- [x] 用户无响应不timeout，resume不自动start
- [x] 流程层无自有领域表且仅用public端口
- [x] 执行相关模块检查及协议/架构公共门槛，记录确切命令、退出状态与证据文件。
- [x] 执行 python tools/docs/validate_docs.py 和本任务 task.py validate，更新规范与上下文。

## 结束与交接

- [x] PRD逐项标记并附证据；没有产品实现前不得填写已通过。
- [x] 在Trellis journal记录结果、限制、依赖影响与下一任务。
- [x] 检查通过后完成/归档，更新任务依赖引用；发布、push、用户重大决定按已有授权处理。

## 本轮补充验收

- [x] coordination-walkthrough中的main+A+B事实轨迹通过，claim/resume只准备，start才执行。
