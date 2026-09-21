# T21 执行步骤与交接

## 开始前

- [x] 检查依赖 T17 的完成证据，读取本任务 PRD/design/上下文与对应 Trellis spec。
- [x] 检查工作区现有改动，确认 Schema/端口已有产物和版本；不得覆盖用户改动。
- [x] 使用 task.py start 显式开始；现在任务保持 planning，不自动运行产品实施。

## 实施步骤

- [x] 确认 T02 指定 Harness 产品/版本及 session 事件对象，不以模型 API 替代
- [x] 绑定持久 conversation 和新分支、处理重复事件/重启统一语义
- [x] 接共享 SDK 工具/消息/黑板，声明可用 enhancement
- [ ] 执行 11 项 baseline 与恢复/去重/并行会话真实验收（0.1.5-rc.2 临时家目录已完成 session isolation；恢复、去重、工具和协作语义仍待补证）

## 检查

- [ ] 11 项通过才正式支持，资料或软件不可用明确阻断
- [x] 模型 API 调用成功不能当作 Harness 集成成功
- [x] 事件回放不重复业务动作
- [x] 与其他三 adapter 协议和身份语义一致
- [x] 执行相关模块检查及协议/架构公共门槛，记录确切命令、退出状态与证据文件。
- [x] 执行 `python tools/docs/validate_docs.py` 和本任务 `task.py validate`，更新规范与上下文。

## 结束与交接

- [ ] PRD逐项标记并附证据；没有产品实现前不得填写已通过。
- [ ] 在Trellis journal记录结果、限制、依赖影响与下一任务。
- [ ] 检查通过后完成/归档，更新任务依赖引用；发布、push、用户重大决定按已有授权处理。

## 2026-09-19 T23 补证

- 官方 `@deepseek-ai/dsh 0.1.5-rc.2` 使用隔离 Harness home 复跑成功；一次性 token 未写日志、命令行或仓库，session isolation/list 证据已脱敏。
- adapter 增加身份绑定和生命周期连续性校验；剩余 10 项真实 Harness bridge baseline 继续 unknown，未以模型 API 替代。
