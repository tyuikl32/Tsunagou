# T17 执行步骤与交接

## 开始前

- [ ] 检查依赖 T16, T02 的完成证据，读取本任务 PRD/design/上下文与对应 Trellis spec。
- [ ] 检查工作区现有改动，确认Schema/端口已有产物和版本；不得覆盖用户改动。
- [ ] 使用 task.py start 显式开始；现在任务保持planning，不自动运行产品实施。

## 实施步骤

- [ ] 实现身份/私有凭据/connection、typed client和重试去重
- [ ] 实现共享MCP和逐session stdio转发，模型看不到token
- [ ] 实现inbox调度/提示裁剪/后台Lease renew与诊断
- [ ] 实现全部baseline与增强降级的统一mock-host验收

## 检查

- [ ] 两个session无凭据/上下文串用
- [ ] 断线/重传/旧epoch同协议预期
- [ ] 未知呈现/停止证据不虚报
- [ ] 四adapter仅做宿主翻译，不复制协议/任务状态机
- [ ] 执行相关模块检查及协议/架构公共门槛，记录确切命令、退出状态与证据文件。
- [ ] 执行 python tools/docs/validate_docs.py 和本任务 task.py validate，更新规范与上下文。

## 结束与交接

- [ ] PRD逐项标记并附证据；没有产品实现前不得填写已通过。
- [ ] 在Trellis journal记录结果、限制、依赖影响与下一任务。
- [ ] 检查通过后完成/归档，更新任务依赖引用；发布、push、用户重大决定按已有授权处理。

## 本轮补充验收

- [ ] attach与managed_launch增强分开；票据签发和bridge兑换保持不同principal，不能复制main token。
