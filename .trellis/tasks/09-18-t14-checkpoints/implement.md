# T14 执行步骤与交接

## 开始前

- [ ] 检查依赖 T12, T05 的完成证据，读取本任务 PRD/design/上下文与对应 Trellis spec。
- [ ] 检查工作区现有改动，确认Schema/端口已有产物和版本；不得覆盖用户改动。
- [ ] 使用 task.py start 显式开始；现在任务保持planning，不自动运行产品实施。

## 实施步骤

- [ ] 实现排序NDJSON/manifest/parent digest、staging/flush/replace与watermark
- [ ] 实现heads/tags可达commit字节核验，排除remote/reflog/unreachable
- [ ] 实现各模块共享白名单导出，不含token/Grant/Lease/job claim/私信
- [ ] 实现同lineage三方消歧、未来format只读、备份与迁移核验

## 检查

- [ ] Windows rename/崩溃各窗口可恢复且hash稳定
- [ ] SQLite事实不被物化失败回滚
- [ ] 同实体冲突不自动合并，sealed不混合
- [ ] 本机anchor和main_reported远端证据明确不同
- [ ] 执行相关模块检查及协议/架构公共门槛，记录确切命令、退出状态与证据文件。
- [ ] 执行 python tools/docs/validate_docs.py 和本任务 task.py validate，更新规范与上下文。

## 结束与交接

- [ ] PRD逐项标记并附证据；没有产品实现前不得填写已通过。
- [ ] 在Trellis journal记录结果、限制、依赖影响与下一任务。
- [ ] 检查通过后完成/归档，更新任务依赖引用；发布、push、用户重大决定按已有授权处理。
