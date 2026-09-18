# T23 执行步骤与交接

## 开始前

- [ ] 检查依赖 T15, T16, T17, T22 的完成证据，读取本任务 PRD/design/上下文与对应 Trellis spec。
- [ ] 检查工作区现有改动，确认Schema/端口已有产物和版本；不得覆盖用户改动。
- [ ] 使用 task.py start 显式开始；现在任务保持planning，不自动运行产品实施。

## 实施步骤

- [ ] 实现validation列出的12类最低故障，真实SQLite/Git/loopback
- [ ] 覆盖认知闭环、长期用户等待、继任、未知外部结果、完成物化失败、reset
- [ ] 校验全部命令权限矩阵、双语言fixtures、import边界与生成物
- [ ] 记录Windows基准/补丁和macOS/Linux实际支持范围

## 检查

- [ ] 无消息丢失/双owner/旧epoch授权复活
- [ ] 崩溃恢复不伪造成功和不盲重不可验证动作
- [ ] 所有工程阻断项通过，失败有最小复现
- [ ] mock adapter通过不冒称真宿主已完成
- [ ] 执行相关模块检查及协议/架构公共门槛，记录确切命令、退出状态与证据文件。
- [ ] 执行 python tools/docs/validate_docs.py 和本任务 task.py validate，更新规范与上下文。

## 结束与交接

- [ ] PRD逐项标记并附证据；没有产品实现前不得填写已通过。
- [ ] 在Trellis journal记录结果、限制、依赖影响与下一任务。
- [ ] 检查通过后完成/归档，更新任务依赖引用；发布、push、用户重大决定按已有授权处理。
