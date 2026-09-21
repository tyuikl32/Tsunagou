# T18 实施设计

## 规范来源

- [docs/implementation/adapters.md](../../../../../docs/implementation/adapters.md)
- [docs/implementation/runtime-prompts.md](../../../../../docs/implementation/runtime-prompts.md)

## 责任与接口

本任务交付：packages/adapter-codex；Codex安装/卸载/诊断指南；真实版本窗与conformance证据。字段、枚举与状态来源于对应模块计划和 data-model；命令名字、URI、principal/Grant/capability 来源于 command-catalog。T03 将其落为机器 Schema，本任务复用生成类型，不另造同义接口。

## 具体处理顺序

1. 采用T02已验证的Codex官方会话/工具接口，绑定installation和conversation。
2. 连接共享SDK，处理resume/compact/new/clear/fork事件与工具调用上下文。
3. 映射实际可用hook/wake/gate，不修改用户全局Full Access设定。
4. 执行11项baseline与跨同目录会话、重启、故障真宿主验收。

## 事务、外部效果与失败

领域变更经项目单 writer/UoW，一起写聚合、event、幂等结果和outbox/Job；跨模块仅public ports。不在事务内等待用户/Agent、Git、HTTP或文件物化。外部结果回写校验输入digest及revision，无法核实时保留unknown；此任务若仅研究/客户端则通过协议证明这些边界，不复制服务器实现。

## 权限与数据可见性

主体来自凭据，不接受模型自报actor。校验project/lineage/runtime、session/connection、authority/attempt epoch与关系。user-only不会下发给Agent；main不等于他人Attempt owner或私信超级读者。tokens/raw conversation IDs不进prompt、日志或共享checkpoint。

## 验证设计

- 11项全部通过才ready/正式支持
- 无可靠ID就diagnostic，不用猜测
- 增强矩阵与实际启用配置一致
- 安装可逆且不把token写prompt/env/MCP args

## 允许的工程选择

可自行选择私有类/函数和测试夹具拆分，记录实际命令与版本。改变公开语义先同步Schema/规范/fixtures；若推翻已确认目标或固定用户边界，提供证据交还用户。实现后的design必须反映最终实现，不能保留已放弃方案作为执行步骤。

## 文档细化补充（2026-09-18）

- [docs/implementation/build-guide.md](../../../../../docs/implementation/build-guide.md)
- [docs/implementation/directory-layout.md](../../../../../docs/implementation/directory-layout.md)
- [docs/implementation/references.md](../../../../../docs/implementation/references.md)
- [docs/overview/subagent-guide.md](../../../../../docs/overview/subagent-guide.md)

目录中的源码路径是待建目标；搭建指南提供顺序，不覆盖本任务依赖。公开接口与权限仍以command-catalog/protocol为准。
