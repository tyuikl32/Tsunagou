# T02 实施设计

## 规范来源

- [docs/implementation/adapters.md](../../../../../docs/implementation/adapters.md)
- [docs/implementation/protocol.md](../../../../../docs/implementation/protocol.md)

## 责任与接口

本任务交付：docs/research/host-matrix.md；tools/conformance/probes/<host>/；脱敏身份生命周期与MCP验证记录。字段、枚举与状态来源于对应模块计划和 data-model；命令名字、URI、principal/Grant/capability 来源于 command-catalog。T03 将其落为机器 Schema，本任务复用生成类型，不另造同义接口。

## 具体处理顺序

1. 核对四宿主官方资料、已安装或可获取版本，确认目标Harness而非模型API。
2. 逐宿主验证同目录双session、resume、compact、new、clear、fork和安装profile标识。
3. 验证typed tools、共享项目MCP鉴权、stdio转发、token私有交付；锁定Python/TS官方SDK兼容API。
4. 记录wake/gate/presented/launch/stop增强实测值，给出正式支持版本窗或明确阻断原因。

## 事务、外部效果与失败

领域变更经项目单 writer/UoW，一起写聚合、event、幂等结果和outbox/Job；跨模块仅public ports。不在事务内等待用户/Agent、Git、HTTP或文件物化。外部结果回写校验输入digest及revision，无法核实时保留unknown；此任务若仅研究/客户端则通过协议证明这些边界，不复制服务器实现。

## 权限与数据可见性

主体来自凭据，不接受模型自报actor。校验project/lineage/runtime、session/connection、authority/attempt epoch与关系。user-only不会下发给Agent；main不等于他人Attempt owner或私信超级读者。tokens/raw conversation IDs不进prompt、日志或共享checkpoint。

## 验证设计

- 11项共同基线逐项有证据状态，未知不填supported
- 身份连续性无法证明则不ready，不用cwd/PID/LLM自报替代
- 两个宿主连接共享服务但不能共享principal
- 所有probe日志无token/raw conversation ID/私有transcript；失败不被隐藏

## 允许的工程选择

可自行选择私有类/函数和测试夹具拆分，记录实际命令与版本。改变公开语义先同步Schema/规范/fixtures；若推翻已确认目标或固定用户边界，提供证据交还用户。实现后的design必须反映最终实现，不能保留已放弃方案作为执行步骤。

## 文档细化补充（2026-09-18）

- [docs/implementation/build-guide.md](../../../../../docs/implementation/build-guide.md)
- [docs/implementation/directory-layout.md](../../../../../docs/implementation/directory-layout.md)
- [docs/implementation/references.md](../../../../../docs/implementation/references.md)
- [docs/overview/subagent-guide.md](../../../../../docs/overview/subagent-guide.md)

目录中的源码路径是待建目标；搭建指南提供顺序，不覆盖本任务依赖。公开接口与权限仍以command-catalog/protocol为准。
