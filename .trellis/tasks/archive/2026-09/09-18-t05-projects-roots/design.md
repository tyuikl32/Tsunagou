# T05 实施设计

## 规范来源

- [docs/implementation/modules/01-projects.md](../../../../../docs/implementation/modules/01-projects.md)
- [docs/implementation/architecture.md](../../../../../docs/implementation/architecture.md)
- [docs/implementation/lifecycle.md](../../../../../docs/implementation/lifecycle.md)

## 责任与接口

本任务交付：projects实体/仓储/public ports；项目中心目录与配置层；路径身份/交集/绑定测试。字段、枚举与状态来源于对应模块计划和 data-model；命令名字、URI、principal/Grant/capability 来源于 command-catalog。T03 将其落为机器 Schema，本任务复用生成类型，不另造同义接口。

## 具体处理顺序

1. 初始化已有Git协调仓库，创建project/lineage/replica和genesis计划，未commit可active。
2. 实现named roots/repositories、本机binding、physical identity、case/link规则。
3. 实现PathRule交并、user ceiling、config provenance和scoped conditions/blockers。
4. 实现项目注册/惰性加载与只读诊断，禁止全局目录成为唯一协作存储。

## 事务、外部效果与失败

领域变更经项目单 writer/UoW，一起写聚合、event、幂等结果和outbox/Job；跨模块仅public ports。不在事务内等待用户/Agent、Git、HTTP或文件物化。外部结果回写校验输入digest及revision，无法核实时保留unknown；此任务若仅研究/客户端则通过协议证明这些边界，不复制服务器实现。

## 权限与数据可见性

主体来自凭据，不接受模型自报actor。校验project/lineage/runtime、session/connection、authority/attempt epoch与关系。user-only不会下发给Agent；main不等于他人Attempt owner或私信超级读者。tokens/raw conversation IDs不进prompt、日志或共享checkpoint。

## 验证设计

- 多文件夹跨仓库可登记且共享文件不泄露绝对路径
- 别名/嵌套root/Windows junction不能扩大权限
- 单root故障不阻塞无关动作
- unanchored允许普通协作，init从第一步有持久化

## 允许的工程选择

可自行选择私有类/函数和测试夹具拆分，记录实际命令与版本。改变公开语义先同步Schema/规范/fixtures；若推翻已确认目标或固定用户边界，提供证据交还用户。实现后的design必须反映最终实现，不能保留已放弃方案作为执行步骤。

## 文档细化补充（2026-09-18）

- [docs/implementation/build-guide.md](../../../../../docs/implementation/build-guide.md)
- [docs/implementation/directory-layout.md](../../../../../docs/implementation/directory-layout.md)
- [docs/implementation/references.md](../../../../../docs/implementation/references.md)

目录中的源码路径是待建目标；搭建指南提供顺序，不覆盖本任务依赖。公开接口与权限仍以command-catalog/protocol为准。
