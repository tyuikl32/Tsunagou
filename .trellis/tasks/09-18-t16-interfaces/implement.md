# T16 执行步骤与交接

## 开始前

- [ ] 检查依赖 T15, T07 的完成证据，读取本任务 PRD/design/上下文与对应 Trellis spec。
- [ ] 检查工作区现有改动，确认Schema/端口已有产物和版本；不得覆盖用户改动。
- [ ] 使用 task.py start 显式开始；现在任务保持planning，不自动运行产品实施。

## 实施步骤

- [ ] 逐条暴露同一CommandPolicy/handler，落实REST headers/ETag/problem和MCP工具投影
- [ ] 实现user CLI控制入口与--json/退出码、config provenance/doctor
- [ ] 实现黑板single read snapshot、bounded sections、敏感过滤和详情入口
- [ ] 实现核心prompt fragments/version/digest与attach/resume/task边界最小注入

## 检查

- [ ] REST/MCP相同命令hash、权限和错误，user-only不出现在Agent tools
- [ ] CLI可以初始化、接入、任命、查看/解决决定、恢复与查询Operation
- [ ] 黑板不引入业务表，截断不漏身份/权限/阻塞
- [ ] 生成OpenAPI零diff，命令目录覆盖率100%
- [ ] 执行相关模块检查及协议/架构公共门槛，记录确切命令、退出状态与证据文件。
- [ ] 执行 python tools/docs/validate_docs.py 和本任务 task.py validate，更新规范与上下文。

## 结束与交接

- [ ] PRD逐项标记并附证据；没有产品实现前不得填写已通过。
- [ ] 在Trellis journal记录结果、限制、依赖影响与下一任务。
- [ ] 检查通过后完成/归档，更新任务依赖引用；发布、push、用户重大决定按已有授权处理。
