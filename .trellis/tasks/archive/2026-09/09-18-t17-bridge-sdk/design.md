# T17 实施设计

## 规范来源

- [docs/implementation/adapters.md](../../../../../docs/implementation/adapters.md)
- [docs/implementation/protocol.md](../../../../../docs/implementation/protocol.md)
- [docs/implementation/runtime-prompts.md](../../../../../docs/implementation/runtime-prompts.md)

## 责任与接口

本任务交付：packages/bridge-sdk；host-neutral Adapter接口和simulator；统一conformance harness。字段、枚举与状态来源于对应模块计划和 data-model；命令名字、URI、principal/Grant/capability 来源于 command-catalog。T03 将其落为机器 Schema，本任务复用生成类型，不另造同义接口。

## 具体处理顺序

1. 实现身份/私有凭据/connection、typed client和重试去重。
2. 实现共享MCP和逐session stdio转发，模型看不到token。
3. 实现inbox调度/提示裁剪/后台Lease renew与诊断。
4. 实现全部baseline与增强降级的统一mock-host验收。

## 事务、外部效果与失败

领域变更经项目单 writer/UoW，一起写聚合、event、幂等结果和outbox/Job；跨模块仅public ports。不在事务内等待用户/Agent、Git、HTTP或文件物化。外部结果回写校验输入digest及revision，无法核实时保留unknown；此任务若仅研究/客户端则通过协议证明这些边界，不复制服务器实现。

## 权限与数据可见性

主体来自凭据，不接受模型自报actor。校验project/lineage/runtime、session/connection、authority/attempt epoch与关系。user-only不会下发给Agent；main不等于他人Attempt owner或私信超级读者。tokens/raw conversation IDs不进prompt、日志或共享checkpoint。

## 验证设计

- 两个session无凭据/上下文串用
- 断线/重传/旧epoch同协议预期
- 未知呈现/停止证据不虚报
- 四adapter仅做宿主翻译，不复制协议/任务状态机

## 允许的工程选择

可自行选择私有类/函数和测试夹具拆分，记录实际命令与版本。改变公开语义先同步Schema/规范/fixtures；若推翻已确认目标或固定用户边界，提供证据交还用户。实现后的design必须反映最终实现，不能保留已放弃方案作为执行步骤。

## 文档细化补充（2026-09-18）

- [docs/implementation/build-guide.md](../../../../../docs/implementation/build-guide.md)
- [docs/implementation/directory-layout.md](../../../../../docs/implementation/directory-layout.md)
- [docs/implementation/references.md](../../../../../docs/implementation/references.md)
- [docs/implementation/cli-contract.md](../../../../../docs/implementation/cli-contract.md)
- [docs/implementation/coordination-walkthrough.md](../../../../../docs/implementation/coordination-walkthrough.md)
- [docs/overview/subagent-guide.md](../../../../../docs/overview/subagent-guide.md)
- [.trellis/spec/backend/entrypoint-contracts.md](../../../../../.trellis/spec/backend/entrypoint-contracts.md)

目录中的源码路径是待建目标；搭建指南提供顺序，不覆盖本任务依赖。公开接口与权限仍以command-catalog/protocol为准。
