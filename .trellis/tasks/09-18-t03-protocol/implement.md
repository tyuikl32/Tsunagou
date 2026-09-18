# T03 执行步骤与交接

## 开始前

- [x] 检查依赖 T01 的完成证据，读取本任务 PRD/design/上下文与对应 Trellis spec。
- [x] 检查工作区现有改动，确认Schema/端口已有产物和版本；不得覆盖用户改动。
- [x] 使用 task.py start 显式开始；现在任务保持planning，不自动运行产品实施。

## 实施步骤

- [x] 逐项落实命令目录为完整输入输出Schema，展开user命令变体和查询，不保留模糊自由JSON
- [x] 实现UUIDv7/UTC/safe-int/PathRule/Scope/EntityRef/JCS公共profile及正反例
- [x] 登记每命令唯一principal/grant/capability/predicates/blocker action，bootstrap/system_job独立
- [x] 生成Pydantic、TS DTO和后续OpenAPI客户端入口；协商N/N-1与bundle digest

## 检查

- [x] Python/TS对fixtures接受拒绝一致，JCS哈希一致
- [x] 每命令都有Schema和policy，无未注册handler，user-only不暴露MCP
- [x] 同输入两次生成字节一致，提交生成物无时间戳
- [x] runtime_epoch是UUID，其他epoch是安全整数；null和省略语义明确
- [x] 执行相关模块检查及协议/架构公共门槛，记录确切命令、退出状态与证据文件。
- [x] 执行 python tools/docs/validate_docs.py 和本任务 task.py validate，更新规范与上下文。

## 结束与交接

- [x] PRD逐项标记并附证据；没有产品实现前不得填写已通过。
- [x] 在Trellis journal记录结果、限制、依赖影响与下一任务。
- [x] 检查通过后完成/归档，更新任务依赖引用；发布、push、用户重大决定按已有授权处理。

## 本轮补充验收

- [x] 手册请求示例替换明确占位值后通过生成Schema；header/body与Attempt上下文不产生第二种解释。
