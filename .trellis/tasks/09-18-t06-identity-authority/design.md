# T06 实施设计

## 规范来源

- [docs/implementation/modules/02-agents.md](../../../docs/implementation/modules/02-agents.md)
- [docs/implementation/modules/01-projects.md](../../../docs/implementation/modules/01-projects.md)
- [docs/implementation/adapters.md](../../../docs/implementation/adapters.md)

## 责任与接口

本任务交付：agents接入/认证/public ports；五类Grant与CommandPolicy执行器；最小control/session私有凭据存储。字段、枚举与状态来源于对应模块计划和 data-model；命令名字、URI、principal/Grant/capability 来源于 command-catalog。T03 将其落为机器 Schema，本任务复用生成类型，不另造同义接口。

## 具体处理顺序

1. 实现installation+conversation keyed digest、ticket原子兑换、degraded/ready与probe快照。
2. 实现32字节opaque token哈希存储、私有交付、rebind和secret脱敏。
3. 实现Connection nonce CAS及commit前epoch fencing、单Agent单非终态Session。
4. 实现user-only任命撤销、main-authority、五Grant typed scope与权限矩阵。

## 事务、外部效果与失败

领域变更经项目单 writer/UoW，一起写聚合、event、幂等结果和outbox/Job；跨模块仅public ports。不在事务内等待用户/Agent、Git、HTTP或文件物化。外部结果回写校验输入digest及revision，无法核实时保留unknown；此任务若仅研究/客户端则通过协议证明这些边界，不复制服务器实现。

## 权限与数据可见性

主体来自凭据，不接受模型自报actor。校验project/lineage/runtime、session/connection、authority/attempt epoch与关系。user-only不会下发给Agent；main不等于他人Attempt owner或私信超级读者。tokens/raw conversation IDs不进prompt、日志或共享checkpoint。

## 验证设计

- 子Agent不能任命主Agent或操作其他Attempt
- 并发兑换/重连无重复身份，token交付丢失走rebind
- baseline缺失仅diagnostic，raw ID/token不进共享历史或模型
- 无OAuth/keyring/refresh体系；Full Access防护范围如实说明

## 允许的工程选择

可自行选择私有类/函数和测试夹具拆分，记录实际命令与版本。改变公开语义先同步Schema/规范/fixtures；若推翻已确认目标或固定用户边界，提供证据交还用户。实现后的design必须反映最终实现，不能保留已放弃方案作为执行步骤。
