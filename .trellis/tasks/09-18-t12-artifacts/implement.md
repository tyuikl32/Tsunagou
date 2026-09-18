# T12 执行步骤与交接

## 开始前

- [x] 检查依赖 T06, T04 的完成证据，读取本任务 PRD/design/上下文与对应 Trellis spec。
- [x] 检查工作区现有改动，确认Schema/端口已有产物和版本；不得覆盖用户改动。
- [x] 使用 task.py start 显式开始；现在任务保持planning，不自动运行产品实施。

## 实施步骤

- [x] 实现大小受限流式上传、临时文件与SHA256/length finalize
- [x] 引用归领域拥有，read始终检查domain ref和recipient
- [x] 实现默认local及main/user显式project_shared promote
- [x] 实现临时上传清理，禁止已final blob自动GC，错误路径脱敏

## 检查

- [x] 仅知hash不能读取，私信附件不因main身份自动提升
- [x] 截断/篡改/重复上传结果正确
- [x] no-auto-GC和checkpoint export白名单可验证
- [x] 文件I/O不在SQLite写事务中
- [x] 执行相关模块检查及协议/架构公共门槛，记录确切命令、退出状态与证据文件。
- [x] 执行 python tools/docs/validate_docs.py 和本任务 task.py validate，更新规范与上下文。

## 结束与交接

- [x] PRD逐项标记并附证据；没有产品实现前不得填写已通过。
- [x] 在Trellis journal记录结果、限制、依赖影响与下一任务。
- [x] 检查通过后完成/归档，更新任务依赖引用；发布、push、用户重大决定按已有授权处理。
