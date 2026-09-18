# T18 执行步骤与交接

## 开始前

- [ ] 检查依赖 T17 的完成证据，读取本任务 PRD/design/上下文与对应 Trellis spec。
- [ ] 检查工作区现有改动，确认Schema/端口已有产物和版本；不得覆盖用户改动。
- [ ] 使用 task.py start 显式开始；现在任务保持planning，不自动运行产品实施。

## 实施步骤

- [ ] 采用T02已验证的Codex官方会话/工具接口，绑定installation和conversation
- [ ] 连接共享SDK，处理resume/compact/new/clear/fork事件与工具调用上下文
- [ ] 映射实际可用hook/wake/gate，不修改用户全局Full Access设定
- [ ] 执行11项baseline与跨同目录会话、重启、故障真宿主验收

## 检查

- [ ] 11项全部通过才ready/正式支持
- [ ] 无可靠ID就diagnostic，不用猜测
- [ ] 增强矩阵与实际启用配置一致
- [ ] 安装可逆且不把token写prompt/env/MCP args
- [ ] 执行相关模块检查及协议/架构公共门槛，记录确切命令、退出状态与证据文件。
- [ ] 执行 python tools/docs/validate_docs.py 和本任务 task.py validate，更新规范与上下文。

## 结束与交接

- [ ] PRD逐项标记并附证据；没有产品实现前不得填写已通过。
- [ ] 在Trellis journal记录结果、限制、依赖影响与下一任务。
- [ ] 检查通过后完成/归档，更新任务依赖引用；发布、push、用户重大决定按已有授权处理。
