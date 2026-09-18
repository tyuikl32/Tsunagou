# T20 实施设计

## 规范来源

- [docs/implementation/adapters.md](../../../docs/implementation/adapters.md)
- [docs/implementation/runtime-prompts.md](../../../docs/implementation/runtime-prompts.md)

## 责任与接口

本任务交付：packages/adapter-zcode；ZCode Hook/MCP安装与诊断；版本/能力/生命周期实测记录。字段、枚举与状态来源于对应模块计划和 data-model；命令名字、URI、principal/Grant/capability 来源于 command-catalog。T03 将其落为机器 Schema，本任务复用生成类型，不另造同义接口。

## 具体处理顺序

1. 采用T02确认的SessionStart/session_id和工具入口。
2. 验证hook实际启用、clear/fork与resume语义，不仅检测配置文件存在。
3. 接共享SDK和最小提示，对gate/wake准确声明强度。
4. 执行baseline与hook缺失/重复通知/重启真宿主测试。

## 事务、外部效果与失败

领域变更经项目单 writer/UoW，一起写聚合、event、幂等结果和outbox/Job；跨模块仅public ports。不在事务内等待用户/Agent、Git、HTTP或文件物化。外部结果回写校验输入digest及revision，无法核实时保留unknown；此任务若仅研究/客户端则通过协议证明这些边界，不复制服务器实现。

## 权限与数据可见性

主体来自凭据，不接受模型自报actor。校验project/lineage/runtime、session/connection、authority/attempt epoch与关系。user-only不会下发给Agent；main不等于他人Attempt owner或私信超级读者。tokens/raw conversation IDs不进prompt、日志或共享checkpoint。

## 验证设计

- 11项通过且ID连续性有证据
- hook缺失不能假ready/enforced
- Full Access仍遵守API角色边界
- 安装/卸载可复现，敏感输出脱敏

## 允许的工程选择

可自行选择私有类/函数和测试夹具拆分，记录实际命令与版本。改变公开语义先同步Schema/规范/fixtures；若推翻已确认目标或固定用户边界，提供证据交还用户。实现后的design必须反映最终实现，不能保留已放弃方案作为执行步骤。
