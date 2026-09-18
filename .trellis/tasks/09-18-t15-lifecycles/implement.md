# T15 执行步骤与交接

## 开始前

- [ ] 检查依赖 T13, T14 的完成证据，读取本任务 PRD/design/上下文与对应 Trellis spec。
- [ ] 检查工作区现有改动，确认Schema/端口已有产物和版本；不得覆盖用户改动。
- [ ] 使用 task.py start 显式开始；现在任务保持planning，不自动运行产品实施。

## 实施步骤

- [ ] 实现精确revision/digest用户控制决定，不从宿主对话伪造批准
- [ ] 实现completion当前Attempt收敛，completed立即事务生效，checkpoint异步屏障
- [ ] 实现handoff/succession冻结/收敛、义务替换、新契约与残余风险
- [ ] 实现新lineage unassigned/新runtime无旧授权、显式恢复任务；unknown追加Resolution

## 检查

- [ ] 用户沉默无限持久不拒绝/失败
- [ ] checkpoint失败保留completed，归档受阻但repair可用
- [ ] 旧owner/session/grant在继任和reset后不能复活
- [ ] 用户ceiling/项目完成等固定边界不能被main风险接受绕过
- [ ] 执行相关模块检查及协议/架构公共门槛，记录确切命令、退出状态与证据文件。
- [ ] 执行 python tools/docs/validate_docs.py 和本任务 task.py validate，更新规范与上下文。

## 结束与交接

- [ ] PRD逐项标记并附证据；没有产品实现前不得填写已通过。
- [ ] 在Trellis journal记录结果、限制、依赖影响与下一任务。
- [ ] 检查通过后完成/归档，更新任务依赖引用；发布、push、用户重大决定按已有授权处理。
