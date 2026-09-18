# T03 统一Schema、DTO与命令策略目录

状态：已规划，未实施。负责人：tyuikl32；开发平台：Codex。

## 目标与交付

- protocol/schemas/与fixtures/
- Python/TS生成器和确定性产物
- CommandPolicy/错误/版本注册表

## 前置依赖

T01。父任务只分组；meta.depends_on 是项目约定，Trellis 不自动调度。开始前检查依赖产物与验收证据。

## 范围

- 逐项落实命令目录为完整输入输出Schema，展开user命令变体和查询，不保留模糊自由JSON
- 实现UUIDv7/UTC/safe-int/PathRule/Scope/EntityRef/JCS公共profile及正反例
- 登记每命令唯一principal/grant/capability/predicates/blocker action，bootstrap/system_job独立
- 生成Pydantic、TS DTO和后续OpenAPI客户端入口；协商N/N-1与bundle digest

## 验收标准

- [ ] Python/TS对fixtures接受拒绝一致，JCS哈希一致
- [ ] 每命令都有Schema和policy，无未注册handler，user-only不暴露MCP
- [ ] 同输入两次生成字节一致，提交生成物无时间戳
- [ ] runtime_epoch是UUID，其他epoch是安全整数；null和省略语义明确

## 不包含

不增加 Web UI、远程认证、隐含认知推断或 daemon Git 写操作；不改变用户已确认权限边界。其他模块只能经 public ports 接入。涉及宿主的真实能力不以模拟通过代替。

## 本轮补充验收

- [ ] 手册请求示例替换明确占位值后通过生成Schema；header/body与Attempt上下文不产生第二种解释。
