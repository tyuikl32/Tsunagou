# T21 实施设计

## 规范来源

- [docs/implementation/adapters.md](../../../docs/implementation/adapters.md)
- [docs/implementation/runtime-prompts.md](../../../docs/implementation/runtime-prompts.md)

## 责任与接口

本任务交付：packages/adapter-deepseek；Harness具体版本与接入runbook；真宿主conformance证据。字段、枚举与状态来源于对应模块计划和 data-model；命令名字、URI、principal/Grant/capability 来源于 command-catalog。T03 将其落为机器 Schema，本任务复用生成类型，不另造同义接口。

## 具体处理顺序

1. 确认T02指定Harness产品/版本及session事件对象，不以模型API替代。
2. 绑定持久conversation和新分支、处理重复事件/重启。
3. 接共享SDK工具/消息/黑板，声明可用enhancement。
4. 执行11项baseline与恢复/去重/并行会话真实验收。

## 事务、外部效果与失败

领域变更经项目单 writer/UoW，一起写聚合、event、幂等结果和outbox/Job；跨模块仅public ports。不在事务内等待用户/Agent、Git、HTTP或文件物化。外部结果回写校验输入digest及revision，无法核实时保留unknown；此任务若仅研究/客户端则通过协议证明这些边界，不复制服务器实现。

## 权限与数据可见性

主体来自凭据，不接受模型自报actor。校验project/lineage/runtime、session/connection、authority/attempt epoch与关系。user-only不会下发给Agent；main不等于他人Attempt owner或私信超级读者。tokens/raw conversation IDs不进prompt、日志或共享checkpoint。

## 验证设计

- 11项通过才正式支持，资料或软件不可用明确阻断
- 模型API调用成功不能当作Harness集成成功
- 事件回放不重复业务动作
- 与其他三adapter协议和身份语义一致

## 允许的工程选择

可自行选择私有类/函数和测试夹具拆分，记录实际命令与版本。改变公开语义先同步Schema/规范/fixtures；若推翻已确认目标或固定用户边界，提供证据交还用户。实现后的design必须反映最终实现，不能保留已放弃方案作为执行步骤。

## 文档细化补充（2026-09-18）

- [docs/implementation/build-guide.md](../../../docs/implementation/build-guide.md)
- [docs/implementation/directory-layout.md](../../../docs/implementation/directory-layout.md)
- [docs/implementation/references.md](../../../docs/implementation/references.md)
- [docs/overview/subagent-guide.md](../../../docs/overview/subagent-guide.md)

目录中的源码路径是待建目标；搭建指南提供顺序，不覆盖本任务依赖。公开接口与权限仍以command-catalog/protocol为准。
