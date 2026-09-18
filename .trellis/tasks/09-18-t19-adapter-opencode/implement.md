# T19 执行步骤与交接

## 开始前

- [ ] 检查依赖 T17 的完成证据，读取本任务 PRD/design/上下文与对应 Trellis spec。
- [ ] 检查工作区现有改动，确认Schema/端口已有产物和版本；不得覆盖用户改动。
- [ ] 使用 task.py start 显式开始；现在任务保持planning，不自动运行产品实施。

## 实施步骤

- [ ] 采用T02确认的SDK session/plugin事件并绑定工具请求
- [ ] 共享bridge身份/消息/恢复实现，验证多session同目录隔离
- [ ] 映射wake/工具观察/生命周期增强，未知证据保守处理
- [ ] 执行baseline、重复事件、乱序事件、断线恢复真宿主测试

## 检查

- [ ] 11项通过且和Codex用同一conformance口径
- [ ] plugin关闭/能力下降转相应degraded或降级
- [ ] 模型不能指定sender/owner
- [ ] 不复制领域Schema或绕REST授权
- [ ] 执行相关模块检查及协议/架构公共门槛，记录确切命令、退出状态与证据文件。
- [ ] 执行 python tools/docs/validate_docs.py 和本任务 task.py validate，更新规范与上下文。

## 结束与交接

- [ ] PRD逐项标记并附证据；没有产品实现前不得填写已通过。
- [ ] 在Trellis journal记录结果、限制、依赖影响与下一任务。
- [ ] 检查通过后完成/归档，更新任务依赖引用；发布、push、用户重大决定按已有授权处理。
