# T18 执行步骤与交接

## 开始前

- [x] 检查依赖 T17 的完成证据，读取本任务 PRD/design/上下文与对应 Trellis spec。
- [x] 检查工作区现有改动，确认 Schema/端口已有产物和版本；不得覆盖用户改动。
- [x] 使用 task.py start 显式开始；现在任务保持 planning，不自动运行产品实施。

## 实施步骤

- [x] 采用 T02 已验证的 Codex 会话/工具证据接口，绑定 installation 和 conversation digest
- [x] 连接共享 SDK，处理 resume/compact/new/clear/fork 统一事件与工具调用上下文
- [x] 映射实际可用 hook/wake/gate，不修改用户全局 Full Access 设定
- [ ] 执行 11 项 baseline 与跨同目录会话、重启、故障真宿主验收（待 Codex 真实版本窗口补证据）

## 检查

- [ ] 11 项全部通过才 ready/正式支持
- [x] 无可靠 ID 就 diagnostic，不用猜测
- [x] 增强矩阵与实际启用配置一致
- [x] 安装可逆且不把 token 写 prompt/env/MCP args
- [x] 执行相关模块检查及协议/架构公共门槛，记录确切命令、退出状态与证据文件。
- [x] 执行 `python tools/docs/validate_docs.py` 和本任务 `task.py validate`，更新规范与上下文。

## 结束与交接

- [ ] PRD逐项标记并附证据；没有产品实现前不得填写已通过。
- [ ] 在Trellis journal记录结果、限制、依赖影响与下一任务。
- [ ] 检查通过后完成/归档，更新任务依赖引用；发布、push、用户重大决定按已有授权处理。
