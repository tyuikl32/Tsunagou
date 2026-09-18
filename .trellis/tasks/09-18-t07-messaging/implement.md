# T07 执行步骤与交接

## 开始前

- [x] 检查依赖 T06 的完成证据，读取本任务 PRD/design/上下文与对应 Trellis spec。
- [x] 检查工作区现有改动，确认Schema/端口已有产物和版本；不得覆盖用户改动。
- [x] 使用 task.py start 显式开始；现在任务保持planning，不自动运行产品实施。

## 实施步骤

- [x] 固化sender/recipient/response contract和payload限制，正文领域授权
- [x] 实现投递租约、批量限制、优先级aging、fetch后去重、defer和ACK
- [x] 实现response/waive/supersede义务与发送同UoW；ACK不满足义务
- [x] 实现push失败抑制和SSE提示，重连REST sync，无replay真相表

## 检查

- [x] 重传不重复消息/回应，主Agent不能读取他人inbox
- [x] 无push仍能完整pull恢复
- [x] 无presented证据不标已呈现，无retry次数自动deadletter
- [x] payload/summary/batch限制与过期租约行为跨语言一致
- [x] 执行相关模块检查及协议/架构公共门槛，记录确切命令、退出状态与证据文件。
- [x] 执行 python tools/docs/validate_docs.py 和本任务 task.py validate，更新规范与上下文。

## 结束与交接

- [x] PRD逐项标记并附证据；没有产品实现前不得填写已通过。
- [x] 在Trellis journal记录结果、限制、依赖影响与下一任务。
- [x] 检查通过后完成/归档，更新任务依赖引用；发布、push、用户重大决定按已有授权处理。
