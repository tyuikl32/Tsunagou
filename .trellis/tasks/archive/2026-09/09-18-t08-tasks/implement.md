# T08 执行步骤与交接

## 开始前

- [x] 检查依赖 T06 的完成证据，读取本任务 PRD/design/上下文与对应 Trellis spec。
- [x] 检查工作区现有改动，确认Schema/端口已有产物和版本；不得覆盖用户改动。
- [x] 使用 task.py start 显式开始；现在任务保持planning，不自动运行产品实施。

## 实施步骤

- [x] 实现create/ready/publish/claim与单owner current Attempt约束
- [x] 实现block/resume准备态、submit/review/self/automated、cancel/orphan/recover
- [x] 实现parent导航与blocks DAG独立，completed follow-up，精确子ResultRef
- [x] 实现scope request/批准后撤Grant阻塞与批量restore_open端口

## 检查

- [x] 并发claim一个owner；主权限不替代Attempt owner
- [x] resume到claimed，start才running；关闭Attempt不复活
- [x] 父终态不级联，孩子状态不自动挡父提交
- [x] review exact result/round，返工新Attempt，batch全成或全败
- [x] 执行相关模块检查及协议/架构公共门槛，记录确切命令、退出状态与证据文件。
- [x] 执行 python tools/docs/validate_docs.py 和本任务 task.py validate，更新规范与上下文。

## 结束与交接

- [x] PRD逐项标记并附证据；没有产品实现前不得填写已通过。
- [x] 在Trellis journal记录结果、限制、依赖影响与下一任务。
- [x] 检查通过后完成/归档，更新任务依赖引用；发布、push、用户重大决定按已有授权处理。
