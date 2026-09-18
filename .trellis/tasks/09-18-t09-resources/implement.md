# T09 执行步骤与交接

## 开始前

- [x] 检查依赖 T08 的完成证据，读取本任务 PRD/design/上下文与对应 Trellis spec。
- [x] 检查工作区现有改动，确认Schema/端口已有产物和版本；不得覆盖用户改动。
- [x] 使用 task.py start 显式开始；现在任务保持planning，不自动运行产品实施。

## 实施步骤

- [x] 实现规范path/named资源key及physical alias归一
- [x] 实现read/consistent_read/exclusive_write/exclusive_use冲突矩阵与all-or-none获取
- [x] 实现TTL120/renew30、FIFO+aging、无抢占，claimed预留
- [x] 到期/离开running时同UoW撤许可并释放，外部观察仅证据

## 检查

- [x] 交叠prefix冲突正确，普通read不假装快照
- [x] 旧session/execution epoch不能续租
- [x] blocked无execution Lease，wait不自动start
- [x] 物理Agent仍跑时保留残余风险，不声明强制停止
- [x] 执行相关模块检查及协议/架构公共门槛，记录确切命令、退出状态与证据文件。
- [x] 执行 python tools/docs/validate_docs.py 和本任务 task.py validate，更新规范与上下文。

## 结束与交接

- [x] PRD逐项标记并附证据；没有产品实现前不得填写已通过。
- [x] 在Trellis journal记录结果、限制、依赖影响与下一任务。
- [x] 检查通过后完成/归档，更新任务依赖引用；发布、push、用户重大决定按已有授权处理。
