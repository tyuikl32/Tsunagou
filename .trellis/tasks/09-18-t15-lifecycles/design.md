# T15 实施设计

## 规范来源

- [docs/implementation/lifecycle.md](../../../docs/implementation/lifecycle.md)
- [docs/implementation/modules/01-projects.md](../../../docs/implementation/modules/01-projects.md)
- [docs/implementation/modules/02-agents.md](../../../docs/implementation/modules/02-agents.md)
- [docs/implementation/modules/07-durability.md](../../../docs/implementation/modules/07-durability.md)

## 责任与接口

本任务交付：UserDecision/Completion/Archive/Reactivate workflows；AuthorityTransition/AgentSuccession；ReplicaActivate/LineageReset/OperationResolution。字段、枚举与状态来源于对应模块计划和 data-model；命令名字、URI、principal/Grant/capability 来源于 command-catalog。T03 将其落为机器 Schema，本任务复用生成类型，不另造同义接口。

## 具体处理顺序

1. 实现精确revision/digest用户控制决定，不从宿主对话伪造批准。
2. 实现completion当前Attempt收敛，completed立即事务生效，checkpoint异步屏障。
3. 实现handoff/succession冻结/收敛、义务替换、新契约与残余风险。
4. 实现新lineage unassigned/新runtime无旧授权、显式恢复任务；unknown追加Resolution。

## 事务、外部效果与失败

领域变更经项目单 writer/UoW，一起写聚合、event、幂等结果和outbox/Job；跨模块仅public ports。不在事务内等待用户/Agent、Git、HTTP或文件物化。外部结果回写校验输入digest及revision，无法核实时保留unknown；此任务若仅研究/客户端则通过协议证明这些边界，不复制服务器实现。

## 权限与数据可见性

主体来自凭据，不接受模型自报actor。校验project/lineage/runtime、session/connection、authority/attempt epoch与关系。user-only不会下发给Agent；main不等于他人Attempt owner或私信超级读者。tokens/raw conversation IDs不进prompt、日志或共享checkpoint。

## 验证设计

- 用户沉默无限持久不拒绝/失败
- checkpoint失败保留completed，归档受阻但repair可用
- 旧owner/session/grant在继任和reset后不能复活
- 用户ceiling/项目完成等固定边界不能被main风险接受绕过

## 允许的工程选择

可自行选择私有类/函数和测试夹具拆分，记录实际命令与版本。改变公开语义先同步Schema/规范/fixtures；若推翻已确认目标或固定用户边界，提供证据交还用户。实现后的design必须反映最终实现，不能保留已放弃方案作为执行步骤。

## 文档细化补充（2026-09-18）

- [docs/implementation/build-guide.md](../../../docs/implementation/build-guide.md)
- [docs/implementation/directory-layout.md](../../../docs/implementation/directory-layout.md)
- [docs/implementation/references.md](../../../docs/implementation/references.md)
- [docs/implementation/coordination-walkthrough.md](../../../docs/implementation/coordination-walkthrough.md)

目录中的源码路径是待建目标；搭建指南提供顺序，不覆盖本任务依赖。公开接口与权限仍以command-catalog/protocol为准。
