# T05 执行步骤与交接

## 开始前

- [ ] 检查依赖 T04 的完成证据，读取本任务 PRD/design/上下文与对应 Trellis spec。
- [ ] 检查工作区现有改动，确认Schema/端口已有产物和版本；不得覆盖用户改动。
- [ ] 使用 task.py start 显式开始；现在任务保持planning，不自动运行产品实施。

## 实施步骤

- [ ] 初始化已有Git协调仓库，创建project/lineage/replica和genesis计划，未commit可active
- [ ] 实现named roots/repositories、本机binding、physical identity、case/link规则
- [ ] 实现PathRule交并、user ceiling、config provenance和scoped conditions/blockers
- [ ] 实现项目注册/惰性加载与只读诊断，禁止全局目录成为唯一协作存储

## 检查

- [ ] 多文件夹跨仓库可登记且共享文件不泄露绝对路径
- [ ] 别名/嵌套root/Windows junction不能扩大权限
- [ ] 单root故障不阻塞无关动作
- [ ] unanchored允许普通协作，init从第一步有持久化
- [ ] 执行相关模块检查及协议/架构公共门槛，记录确切命令、退出状态与证据文件。
- [ ] 执行 python tools/docs/validate_docs.py 和本任务 task.py validate，更新规范与上下文。

## 结束与交接

- [ ] PRD逐项标记并附证据；没有产品实现前不得填写已通过。
- [ ] 在Trellis journal记录结果、限制、依赖影响与下一任务。
- [ ] 检查通过后完成/归档，更新任务依赖引用；发布、push、用户重大决定按已有授权处理。
