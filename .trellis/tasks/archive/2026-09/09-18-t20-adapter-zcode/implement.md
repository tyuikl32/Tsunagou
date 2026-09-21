# T20 执行步骤与交接

## 开始前

- [x] 检查依赖 T17 的完成证据，读取本任务 PRD/design/上下文与对应 Trellis spec。
- [x] 检查工作区现有改动，确认 Schema/端口已有产物和版本；不得覆盖用户改动。
- [x] 使用 task.py start 显式开始；现在任务保持 planning，不自动运行产品实施。

## 实施步骤

- [x] 采用 T02 记录的 SessionStart/session_id 和工具入口语义
- [x] 验证 hook 实际启用由运行证据决定，不仅检测配置文件存在
- [x] 接共享 SDK 和最小提示，对 gate/wake 准确声明强度
- [ ] 执行 baseline 与 hook 缺失/重复通知/重启真宿主测试（待安装 ZCode）

## 检查

- [ ] 11 项通过且 ID 连续性有证据
- [x] hook 缺失不能假 ready/enforced
- [x] Full Access 仍遵守 API 角色边界
- [x] 安装/卸载可复现，敏感输出脱敏
- [x] 执行相关模块检查及协议/架构公共门槛，记录确切命令、退出状态与证据文件。
- [x] 执行 `python tools/docs/validate_docs.py` 和本任务 `task.py validate`，更新规范与上下文。

## 结束与交接

- [ ] PRD逐项标记并附证据；没有产品实现前不得填写已通过。
- [ ] 在Trellis journal记录结果、限制、依赖影响与下一任务。
- [ ] 检查通过后完成/归档，更新任务依赖引用；发布、push、用户重大决定按已有授权处理。
