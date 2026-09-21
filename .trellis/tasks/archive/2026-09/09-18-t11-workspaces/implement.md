# T11 执行步骤与交接

## 开始前

- [x] 检查依赖 T09, T10 的完成证据，读取本任务 PRD/design/上下文与对应 Trellis spec。
- [x] 检查工作区现有改动，确认Schema/端口已有产物和版本；不得覆盖用户改动。
- [x] 使用 task.py start 显式开始；现在任务保持planning，不自动运行产品实施。

## 实施步骤

- [x] 实现driver候选与hard constraints校验，不规定单一默认隔离
- [x] 把worktree创建/移除及所有Git写操作转为main请求，daemon仅核验
- [x] 实现baseline/result、单repo worktree、未提交patch引用和多repo部分结果
- [x] 实现integration/cleanup计划与terminal+checkpoint屏障，dirty强制user-only

## 检查

- [x] 抓取daemon Git调用无mutation或网络Git
- [x] 无main时保持pending不兜底执行
- [x] dirty/untracked baseline、HEAD变化明确阻塞
- [x] 清理不跨scope，最后副本风险单独控制
- [x] 执行相关模块检查及协议/架构公共门槛，记录确切命令、退出状态与证据文件。
- [x] 执行 python tools/docs/validate_docs.py 和本任务 task.py validate，更新规范与上下文。

## 结束与交接

- [x] PRD逐项标记并附证据；没有产品实现前不得填写已通过。
- [x] 在Trellis journal记录结果、限制、依赖影响与下一任务。
- [x] 检查通过后完成/归档，更新任务依赖引用；发布、push、用户重大决定按已有授权处理。
