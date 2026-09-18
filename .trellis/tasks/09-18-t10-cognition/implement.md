# T10 执行步骤与交接

## 开始前

- [x] 检查依赖 T08 的完成证据，读取本任务 PRD/design/上下文与对应 Trellis spec。
- [x] 检查工作区现有改动，确认Schema/端口已有产物和版本；不得覆盖用户改动。
- [x] 使用 task.py start 显式开始；现在任务保持planning，不自动运行产品实施。

## 实施步骤

- [x] 实现版本化认知报告和显式claims/uncertainties，报告边界校验
- [x] 实现显式分歧和固定类型/字面/hash/resource规则及去重
- [x] 实现proposal不可变payload/participants、全required exact digest接受和获准proxy
- [x] 实现main风险请求/建议、120秒fallback、input digest风险接受有效性

## 检查

- [x] 无语义模型/文本相似度硬判定
- [x] 参与者或内容变化需新proposal及新接受
- [x] proxy保留真实actor，policy不允许则拒绝
- [x] 风险接受不能越ceiling或把unknown判成功
- [x] 执行相关模块检查及协议/架构公共门槛，记录确切命令、退出状态与证据文件。
- [x] 执行 python tools/docs/validate_docs.py 和本任务 task.py validate，更新规范与上下文。

## 结束与交接

- [x] PRD逐项标记并附证据；没有产品实现前不得填写已通过。
- [x] 在Trellis journal记录结果、限制、依赖影响与下一任务。
- [x] 检查通过后完成/归档，更新任务依赖引用；发布、push、用户重大决定按已有授权处理。
