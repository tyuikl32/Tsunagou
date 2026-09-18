# T16 实施设计

## 规范来源

- [docs/implementation/command-catalog.md](../../../docs/implementation/command-catalog.md)
- [docs/implementation/protocol.md](../../../docs/implementation/protocol.md)
- [docs/implementation/runtime-prompts.md](../../../docs/implementation/runtime-prompts.md)

## 责任与接口

本任务交付：FastAPI routers、共享MCP、Typer CLI；一致读Blackboard与版本化提示资产；OpenAPI artifact、用户操作runbook。字段、枚举与状态来源于对应模块计划和 data-model；命令名字、URI、principal/Grant/capability 来源于 command-catalog。T03 将其落为机器 Schema，本任务复用生成类型，不另造同义接口。

## 具体处理顺序

1. 逐条暴露同一CommandPolicy/handler，落实REST headers/ETag/problem和MCP工具投影。
2. 实现user CLI控制入口与--json/退出码、config provenance/doctor。
3. 实现黑板single read snapshot、bounded sections、敏感过滤和详情入口。
4. 实现核心prompt fragments/version/digest与attach/resume/task边界最小注入。

## 事务、外部效果与失败

领域变更经项目单 writer/UoW，一起写聚合、event、幂等结果和outbox/Job；跨模块仅public ports。不在事务内等待用户/Agent、Git、HTTP或文件物化。外部结果回写校验输入digest及revision，无法核实时保留unknown；此任务若仅研究/客户端则通过协议证明这些边界，不复制服务器实现。

## 权限与数据可见性

主体来自凭据，不接受模型自报actor。校验project/lineage/runtime、session/connection、authority/attempt epoch与关系。user-only不会下发给Agent；main不等于他人Attempt owner或私信超级读者。tokens/raw conversation IDs不进prompt、日志或共享checkpoint。

## 验证设计

- REST/MCP相同命令hash、权限和错误，user-only不出现在Agent tools
- CLI可以初始化、接入、任命、查看/解决决定、恢复与查询Operation
- 黑板不引入业务表，截断不漏身份/权限/阻塞
- 生成OpenAPI零diff，命令目录覆盖率100%

## 允许的工程选择

可自行选择私有类/函数和测试夹具拆分，记录实际命令与版本。改变公开语义先同步Schema/规范/fixtures；若推翻已确认目标或固定用户边界，提供证据交还用户。实现后的design必须反映最终实现，不能保留已放弃方案作为执行步骤。

## 文档细化补充（2026-09-18）

- [docs/implementation/build-guide.md](../../../docs/implementation/build-guide.md)
- [docs/implementation/directory-layout.md](../../../docs/implementation/directory-layout.md)
- [docs/implementation/references.md](../../../docs/implementation/references.md)
- [docs/implementation/cli-contract.md](../../../docs/implementation/cli-contract.md)
- [docs/overview/cli-http-manual.md](../../../docs/overview/cli-http-manual.md)
- [docs/overview/subagent-guide.md](../../../docs/overview/subagent-guide.md)
- [.trellis/spec/backend/entrypoint-contracts.md](../../../.trellis/spec/backend/entrypoint-contracts.md)

目录中的源码路径是待建目标；搭建指南提供顺序，不覆盖本任务依赖。公开接口与权限仍以command-catalog/protocol为准。
