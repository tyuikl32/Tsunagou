# T24 实施设计

## 规范来源

- [docs/overview/demo.md](../../../docs/overview/demo.md)
- [docs/implementation/modules/08-evaluation.md](../../../docs/implementation/modules/08-evaluation.md)
- [docs/implementation/validation.md](../../../docs/implementation/validation.md)

## 责任与接口

本任务交付：用户使用与十分钟演示runbook；A/B/C/D实验报告和脱敏原始结果；首发支持矩阵、升级恢复指南、交付清单。字段、枚举与状态来源于对应模块计划和 data-model；命令名字、URI、principal/Grant/capability 来源于 command-catalog。T03 将其落为机器 Schema，本任务复用生成类型，不另造同义接口。

## 具体处理顺序

1. 按统一任务预算随机运行A/B/C/D各至少5次，正式多Agent至少3个。
2. 另一个宿主复验，统计正确性、检出误报、干预/返工/耗时/token。
3. 执行四宿主安装到完成/恢复演示，确认用户控制入口清晰。
4. 同步overview的实际状态与限制，准备源码发布材料而不擅自发布。

## 事务、外部效果与失败

领域变更经项目单 writer/UoW，一起写聚合、event、幂等结果和outbox/Job；跨模块仅public ports。不在事务内等待用户/Agent、Git、HTTP或文件物化。外部结果回写校验输入digest及revision，无法核实时保留unknown；此任务若仅研究/客户端则通过协议证明这些边界，不复制服务器实现。

## 权限与数据可见性

主体来自凭据，不接受模型自报actor。校验project/lineage/runtime、session/connection、authority/attempt epoch与关系。user-only不会下发给Agent；main不等于他人Attempt owner或私信超级读者。tokens/raw conversation IDs不进prompt、日志或共享checkpoint。

## 验证设计

- 工程发布门槛全过，四宿主各自有真实baseline证据
- 研究指标如实判定，未达目标不宣称达成
- 用户能按指南理解并演示认知闭环、身份边界和恢复
- 锁文件/Schema/OpenAPI/迁移/报告齐全，发布另按授权执行

## 允许的工程选择

可自行选择私有类/函数和测试夹具拆分，记录实际命令与版本。改变公开语义先同步Schema/规范/fixtures；若推翻已确认目标或固定用户边界，提供证据交还用户。实现后的design必须反映最终实现，不能保留已放弃方案作为执行步骤。
