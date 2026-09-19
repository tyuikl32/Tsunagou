# T19 执行步骤与交接

## 开始前

- [x] 检查依赖 T17 的完成证据，读取本任务 PRD/design/上下文与对应 Trellis spec。
- [x] 检查工作区现有改动，确认 Schema/端口已有产物和版本；不得覆盖用户改动。
- [x] 使用 task.py start 显式开始；现在任务保持 planning，不自动运行产品实施。

## 实施步骤

- [x] 采用 T02 记录的 SDK session/plugin 事件语义并绑定工具请求
- [x] 共享 bridge 身份/消息/恢复实现，验证多 session 同目录隔离接口
- [x] 映射 wake/工具观察/生命周期增强，未知证据保守处理
- [x] 执行同目录 session/fork/history/doc 的无模型真实宿主 probe，并保存脱敏 evidence
- [ ] 执行完整 baseline、重复事件、乱序事件、断线恢复真宿主测试（仍待补齐模型/bridge 生命周期证据）

## 检查

- [ ] 11 项通过且和 Codex 用同一 conformance 口径
- [x] plugin 关闭/能力下降转相应 degraded 或降级
- [x] 模型不能指定 sender/owner
- [x] 不复制领域 Schema 或绕 REST 授权
- [x] 执行相关模块检查及协议/架构公共门槛，记录确切命令、退出状态与证据文件。
- [x] 执行 `python tools/docs/validate_docs.py` 和本任务 `task.py validate`，更新规范与上下文。

## 结束与交接

- [ ] PRD逐项标记并附证据；没有产品实现前不得填写已通过。
- [ ] 在Trellis journal记录结果、限制、依赖影响与下一任务。
- [ ] 检查通过后完成/归档，更新任务依赖引用；发布、push、用户重大决定按已有授权处理。

## 2026-09-19 T23 补证

- `opencode-ai 1.18.31` 纯 headless 服务真实探针复跑成功；健康、项目端点、同目录 session 隔离、详情、fork、history 与 typed session API 均可观察。
- adapter 现在必须同时具备 installation ID 与脱敏 conversation digest 才接受 capability evidence；剩余 10 项真实 bridge baseline 继续 unknown。
