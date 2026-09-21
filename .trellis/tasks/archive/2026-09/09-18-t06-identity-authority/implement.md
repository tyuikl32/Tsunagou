# T06 执行步骤与交接

## 开始前

- [x] 检查依赖 T05, T02 的完成证据，读取本任务 PRD/design/上下文与对应 Trellis spec。
- [x] 检查工作区现有改动，确认Schema/端口已有产物和版本；不得覆盖用户改动。
- [x] 使用 task.py start 显式开始；现在任务保持planning，不自动运行产品实施。

## 实施步骤

- [x] 实现installation+conversation keyed digest、ticket原子兑换、degraded/ready与probe快照
- [x] 实现32字节opaque token哈希存储、私有交付、rebind和secret脱敏
- [x] 实现Connection nonce CAS及commit前epoch fencing、单Agent单非终态Session
- [x] 实现user-only任命撤销、main-authority、五Grant typed scope与权限矩阵

## 检查

- [x] 子Agent不能任命主Agent或操作其他Attempt
- [x] 并发兑换/重连无重复身份，token交付丢失走rebind
- [x] baseline缺失仅diagnostic，raw ID/token不进共享历史或模型
- [x] 无OAuth/keyring/refresh体系；Full Access防护范围如实说明
- [x] 执行相关模块检查及协议/架构公共门槛，记录确切命令、退出状态与证据文件。
- [x] 执行 python tools/docs/validate_docs.py 和本任务 task.py validate，更新规范与上下文。

## 结束与交接

- [x] PRD逐项标记并附证据；没有产品实现前不得填写已通过。
- [x] 在Trellis journal记录结果、限制、依赖影响与下一任务。
- [x] 检查通过后完成/归档，更新任务依赖引用；发布、push、用户重大决定按已有授权处理。

## 本轮补充验收

- [x] 用户attach两个会话产生独立worker身份；宿主内置subagent不自动视为正式成员；接入不授任务执行权。
