# T09 实施设计

## 规范来源

- [docs/implementation/modules/05-resources.md](../../../docs/implementation/modules/05-resources.md)
- [docs/implementation/modules/01-projects.md](../../../docs/implementation/modules/01-projects.md)

## 责任与接口

本任务交付：ResourceIntent/LeaseSet/WaitQueue；Lease时钟/续租/到期流程；scope和冲突属性测试。字段、枚举与状态来源于对应模块计划和 data-model；命令名字、URI、principal/Grant/capability 来源于 command-catalog。T03 将其落为机器 Schema，本任务复用生成类型，不另造同义接口。

## 具体处理顺序

1. 实现规范path/named资源key及physical alias归一。
2. 实现read/consistent_read/exclusive_write/exclusive_use冲突矩阵与all-or-none获取。
3. 实现TTL120/renew30、FIFO+aging、无抢占，claimed预留。
4. 到期/离开running时同UoW撤许可并释放，外部观察仅证据。

## 事务、外部效果与失败

领域变更经项目单 writer/UoW，一起写聚合、event、幂等结果和outbox/Job；跨模块仅public ports。不在事务内等待用户/Agent、Git、HTTP或文件物化。外部结果回写校验输入digest及revision，无法核实时保留unknown；此任务若仅研究/客户端则通过协议证明这些边界，不复制服务器实现。

## 权限与数据可见性

主体来自凭据，不接受模型自报actor。校验project/lineage/runtime、session/connection、authority/attempt epoch与关系。user-only不会下发给Agent；main不等于他人Attempt owner或私信超级读者。tokens/raw conversation IDs不进prompt、日志或共享checkpoint。

## 验证设计

- 交叠prefix冲突正确，普通read不假装快照
- 旧session/execution epoch不能续租
- blocked无execution Lease，wait不自动start
- 物理Agent仍跑时保留残余风险，不声明强制停止

## 允许的工程选择

可自行选择私有类/函数和测试夹具拆分，记录实际命令与版本。改变公开语义先同步Schema/规范/fixtures；若推翻已确认目标或固定用户边界，提供证据交还用户。实现后的design必须反映最终实现，不能保留已放弃方案作为执行步骤。
