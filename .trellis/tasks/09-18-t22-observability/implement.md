# T22 执行步骤与交接

## 开始前

- [ ] 检查依赖 T04, T07, T08, T10 的完成证据，读取本任务 PRD/design/上下文与对应 Trellis spec。
- [ ] 检查工作区现有改动，确认Schema/端口已有产物和版本；不得覆盖用户改动。
- [ ] 使用 task.py start 显式开始；现在任务保持planning，不自动运行产品实施。

## 实施步骤

- [ ] 实现脱敏事件投影/只读审计，权限过滤不可被main绕过
- [ ] 实现intervention/rework/latency/token来源与availability口径
- [ ] 实现固定实验定义digest、随机种子、预算/版本记录和原始结果引用
- [ ] 实现报告Job及统计，不删除失败样本；OTLP默认关闭

## 检查

- [ ] secret哨兵不会经日志/error/export/telemetry泄漏
- [ ] 无usage标unavailable不是0
- [ ] 审计不能修改业务真相
- [ ] 统计对相同输入可复现，样本/限制公开
- [ ] 执行相关模块检查及协议/架构公共门槛，记录确切命令、退出状态与证据文件。
- [ ] 执行 python tools/docs/validate_docs.py 和本任务 task.py validate，更新规范与上下文。

## 结束与交接

- [ ] PRD逐项标记并附证据；没有产品实现前不得填写已通过。
- [ ] 在Trellis journal记录结果、限制、依赖影响与下一任务。
- [ ] 检查通过后完成/归档，更新任务依赖引用；发布、push、用户重大决定按已有授权处理。
