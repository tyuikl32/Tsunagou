# T23 实施设计

## 规范来源

- [docs/implementation/validation.md](../../../../../docs/implementation/validation.md)
- [docs/implementation/lifecycle.md](../../../../../docs/implementation/lifecycle.md)
- [docs/implementation/modules/07-durability.md](../../../../../docs/implementation/modules/07-durability.md)

## 责任与接口

本任务交付：tests/integration与fault_injection；Windows CI/本机发布检查；端到端操作证据与缺陷清单。字段、枚举与状态来源于对应模块计划和 data-model；命令名字、URI、principal/Grant/capability 来源于 command-catalog。T03 将其落为机器 Schema，本任务复用生成类型，不另造同义接口。

## 具体处理顺序

1. 实现validation列出的12类最低故障，真实SQLite/Git/loopback。
2. 覆盖认知闭环、长期用户等待、继任、未知外部结果、完成物化失败、reset。
3. 校验全部命令权限矩阵、双语言fixtures、import边界与生成物。
4. 记录Windows基准/补丁和macOS/Linux实际支持范围。

## 事务、外部效果与失败

领域变更经项目单 writer/UoW，一起写聚合、event、幂等结果和outbox/Job；跨模块仅public ports。不在事务内等待用户/Agent、Git、HTTP或文件物化。外部结果回写校验输入digest及revision，无法核实时保留unknown；此任务若仅研究/客户端则通过协议证明这些边界，不复制服务器实现。

## 权限与数据可见性

主体来自凭据，不接受模型自报actor。校验project/lineage/runtime、session/connection、authority/attempt epoch与关系。user-only不会下发给Agent；main不等于他人Attempt owner或私信超级读者。tokens/raw conversation IDs不进prompt、日志或共享checkpoint。

## 验证设计

- 无消息丢失/双owner/旧epoch授权复活
- 崩溃恢复不伪造成功和不盲重不可验证动作
- 所有工程阻断项通过，失败有最小复现
- mock adapter通过不冒称真宿主已完成

## 允许的工程选择

可自行选择私有类/函数和测试夹具拆分，记录实际命令与版本。改变公开语义先同步Schema/规范/fixtures；若推翻已确认目标或固定用户边界，提供证据交还用户。实现后的design必须反映最终实现，不能保留已放弃方案作为执行步骤。

## 文档细化补充（2026-09-18）

- [docs/implementation/build-guide.md](../../../../../docs/implementation/build-guide.md)
- [docs/implementation/directory-layout.md](../../../../../docs/implementation/directory-layout.md)
- [docs/implementation/references.md](../../../../../docs/implementation/references.md)
- [docs/implementation/coordination-walkthrough.md](../../../../../docs/implementation/coordination-walkthrough.md)
- [docs/overview/cli-http-manual.md](../../../../../docs/overview/cli-http-manual.md)
- [.trellis/spec/backend/entrypoint-contracts.md](../../../../../.trellis/spec/backend/entrypoint-contracts.md)

目录中的源码路径是待建目标；搭建指南提供顺序，不覆盖本任务依赖。公开接口与权限仍以command-catalog/protocol为准。
