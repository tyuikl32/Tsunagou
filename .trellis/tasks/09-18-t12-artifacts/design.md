# T12 实施设计

## 规范来源

- [docs/implementation/modules/07-durability.md](../../../docs/implementation/modules/07-durability.md)
- [docs/implementation/protocol.md](../../../docs/implementation/protocol.md)

## 责任与接口

本任务交付：upload intent/bytes/finalize与blob目录；各模块ArtifactRef授权接口；promote与共享导出规则。字段、枚举与状态来源于对应模块计划和 data-model；命令名字、URI、principal/Grant/capability 来源于 command-catalog。T03 将其落为机器 Schema，本任务复用生成类型，不另造同义接口。

## 具体处理顺序

1. 实现大小受限流式上传、临时文件与SHA256/length finalize。
2. 引用归领域拥有，read始终检查domain ref和recipient。
3. 实现默认local及main/user显式project_shared promote。
4. 实现临时上传清理，禁止已final blob自动GC，错误路径脱敏。

## 事务、外部效果与失败

领域变更经项目单 writer/UoW，一起写聚合、event、幂等结果和outbox/Job；跨模块仅public ports。不在事务内等待用户/Agent、Git、HTTP或文件物化。外部结果回写校验输入digest及revision，无法核实时保留unknown；此任务若仅研究/客户端则通过协议证明这些边界，不复制服务器实现。

## 权限与数据可见性

主体来自凭据，不接受模型自报actor。校验project/lineage/runtime、session/connection、authority/attempt epoch与关系。user-only不会下发给Agent；main不等于他人Attempt owner或私信超级读者。tokens/raw conversation IDs不进prompt、日志或共享checkpoint。

## 验证设计

- 仅知hash不能读取，私信附件不因main身份自动提升
- 截断/篡改/重复上传结果正确
- no-auto-GC和checkpoint export白名单可验证
- 文件I/O不在SQLite写事务中

## 允许的工程选择

可自行选择私有类/函数和测试夹具拆分，记录实际命令与版本。改变公开语义先同步Schema/规范/fixtures；若推翻已确认目标或固定用户边界，提供证据交还用户。实现后的design必须反映最终实现，不能保留已放弃方案作为执行步骤。
