# T13 实施设计

## 规范来源

- [docs/implementation/lifecycle.md](../../../docs/implementation/lifecycle.md)
- [docs/implementation/modules/03-tasks.md](../../../docs/implementation/modules/03-tasks.md)
- [docs/implementation/modules/04-cognition.md](../../../docs/implementation/modules/04-cognition.md)

## 责任与接口

本任务交付：application/workflows/task_execution；scope/report/contract/resource/workspace组合preflight；首个模拟多Agent认知协作场景。字段、枚举与状态来源于对应模块计划和 data-model；命令名字、URI、principal/Grant/capability 来源于 command-catalog。T03 将其落为机器 Schema，本任务复用生成类型，不另造同义接口。

## 具体处理顺序

1. 将所有模块证据组成带revisions/digest的PreflightResult。
2. 实现claimed/start原子核验及Grant签发、submit撤权/Lease和review。
3. 实现block保存快照、resume重新准备，相关scope blocker与无关工作继续。
4. 完成两Agent显式分歧→契约→任务结果的持久端到端场景。

## 事务、外部效果与失败

领域变更经项目单 writer/UoW，一起写聚合、event、幂等结果和outbox/Job；跨模块仅public ports。不在事务内等待用户/Agent、Git、HTTP或文件物化。外部结果回写校验输入digest及revision，无法核实时保留unknown；此任务若仅研究/客户端则通过协议证明这些边界，不复制服务器实现。

## 权限与数据可见性

主体来自凭据，不接受模型自报actor。校验project/lineage/runtime、session/connection、authority/attempt epoch与关系。user-only不会下发给Agent；main不等于他人Attempt owner或私信超级读者。tokens/raw conversation IDs不进prompt、日志或共享checkpoint。

## 验证设计

- 任何输入变更使旧preflight失效，无半启动
- blocked仍可报告/协商但不能执行
- 用户无响应不timeout，resume不自动start
- 流程层无自有领域表且仅用public端口

## 允许的工程选择

可自行选择私有类/函数和测试夹具拆分，记录实际命令与版本。改变公开语义先同步Schema/规范/fixtures；若推翻已确认目标或固定用户边界，提供证据交还用户。实现后的design必须反映最终实现，不能保留已放弃方案作为执行步骤。
