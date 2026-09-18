# T03 实施设计

## 规范来源

- [docs/implementation/protocol.md](../../../docs/implementation/protocol.md)
- [docs/implementation/data-model.md](../../../docs/implementation/data-model.md)
- [docs/implementation/command-catalog.md](../../../docs/implementation/command-catalog.md)

## 责任与接口

本任务交付：protocol/schemas/与fixtures/；Python/TS生成器和确定性产物；CommandPolicy/错误/版本注册表。字段、枚举与状态来源于对应模块计划和 data-model；命令名字、URI、principal/Grant/capability 来源于 command-catalog。T03 将其落为机器 Schema，本任务复用生成类型，不另造同义接口。

## 具体处理顺序

1. 逐项落实命令目录为完整输入输出Schema，展开user命令变体和查询，不保留模糊自由JSON。
2. 实现UUIDv7/UTC/safe-int/PathRule/Scope/EntityRef/JCS公共profile及正反例。
3. 登记每命令唯一principal/grant/capability/predicates/blocker action，bootstrap/system_job独立。
4. 生成Pydantic、TS DTO和后续OpenAPI客户端入口；协商N/N-1与bundle digest。

## 事务、外部效果与失败

领域变更经项目单 writer/UoW，一起写聚合、event、幂等结果和outbox/Job；跨模块仅public ports。不在事务内等待用户/Agent、Git、HTTP或文件物化。外部结果回写校验输入digest及revision，无法核实时保留unknown；此任务若仅研究/客户端则通过协议证明这些边界，不复制服务器实现。

## 权限与数据可见性

主体来自凭据，不接受模型自报actor。校验project/lineage/runtime、session/connection、authority/attempt epoch与关系。user-only不会下发给Agent；main不等于他人Attempt owner或私信超级读者。tokens/raw conversation IDs不进prompt、日志或共享checkpoint。

## 验证设计

- Python/TS对fixtures接受拒绝一致，JCS哈希一致
- 每命令都有Schema和policy，无未注册handler，user-only不暴露MCP
- 同输入两次生成字节一致，提交生成物无时间戳
- runtime_epoch是UUID，其他epoch是安全整数；null和省略语义明确

## 允许的工程选择

可自行选择私有类/函数和测试夹具拆分，记录实际命令与版本。改变公开语义先同步Schema/规范/fixtures；若推翻已确认目标或固定用户边界，提供证据交还用户。实现后的design必须反映最终实现，不能保留已放弃方案作为执行步骤。
