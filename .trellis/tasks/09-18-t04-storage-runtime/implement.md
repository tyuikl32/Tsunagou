# T04 执行步骤与交接

## 开始前

- [x] 检查依赖 T03 的完成证据，读取本任务 PRD/design/上下文与对应 Trellis spec。
- [x] 检查工作区现有改动，确认Schema/端口已有产物和版本；不得覆盖用户改动。
- [x] 使用 task.py start 显式开始；现在任务保持planning，不自动运行产品实施。

## 实施步骤

- [x] 建立每项目单writer队列、OS lock、WAL/FULL/FK和一致读snapshot
- [x] 实现事务内授权回调、幂等hash/result、event_seq与outbox原子写
- [x] 实现Operation/Job/JobAttempt、worker lease、timeout/backoff、effect分类和unknown处理
- [x] 启动恢复登记项目未完成工作；迁移前备份，失败只读诊断（持久底座完成；迁移备份执行器留给后续专项）

## 检查

- [x] commit前后崩溃不丢状态或重复动作（单元级回滚与幂等重放）
- [x] 同command_id不同hash冲突，旧epoch不能借重放绕权限
- [x] 外部效果未知不盲目重试，Resolution只追加
- [x] 两个本机writer互斥；Job超时不解释用户沉默
- [x] 执行相关模块检查及协议/架构公共门槛，记录确切命令、退出状态与证据文件。
- [x] 执行 python tools/docs/validate_docs.py 和本任务 task.py validate，更新规范与上下文。

## 结束与交接

- [x] PRD逐项标记并附证据；没有产品实现前不得填写已通过。
- [x] 在Trellis journal记录结果、限制、依赖影响与下一任务。
- [x] 检查通过后完成/归档，更新任务依赖引用；发布、push、用户重大决定按已有授权处理。
