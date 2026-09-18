# T01 实施设计

## 规范来源

- [docs/implementation/architecture.md](../../../docs/implementation/architecture.md)
- [docs/overview/technology.md](../../../docs/overview/technology.md)

## 责任与接口

本任务交付：pyproject.toml、uv.lock、src/tsunagou骨架；package.json、pnpm-workspace.yaml、pnpm-lock.yaml；Windows开发引导与静态检查脚本。字段、枚举与状态来源于对应模块计划和 data-model；命令名字、URI、principal/Grant/capability 来源于 command-catalog。T03 将其落为机器 Schema，本任务复用生成类型，不另造同义接口。

## 具体处理顺序

1. 核验Python/Node/pnpm/TS版本窗口和注册表可用性，保存实际输出；冲突记录兼容矩阵。
2. 建立单Python distribution和六TS工作区包，生成目录标只读。
3. 安装并锁定FastAPI/数据库/CLI/Schema/测试依赖，MCP SDK精确版本接T02结论。
4. 加入Ruff/mypy/pytest/Vitest和import边界检查入口，制定源码运行命令。

## 事务、外部效果与失败

领域变更经项目单 writer/UoW，一起写聚合、event、幂等结果和outbox/Job；跨模块仅public ports。不在事务内等待用户/Agent、Git、HTTP或文件物化。外部结果回写校验输入digest及revision，无法核实时保留unknown；此任务若仅研究/客户端则通过协议证明这些边界，不复制服务器实现。

## 权限与数据可见性

主体来自凭据，不接受模型自报actor。校验project/lineage/runtime、session/connection、authority/attempt epoch与关系。user-only不会下发给Agent；main不等于他人Attempt owner或私信超级读者。tokens/raw conversation IDs不进prompt、日志或共享checkpoint。

## 验证设计

- Windows干净环境可按锁文件安装和导入空应用
- Python域层不依赖框架，TS内部包使用workspace:*和strict/NodeNext
- 重装不改变锁文件；不把未实现产品演示写成已可运行
- 版本冲突有证据，无静默扩大已定窗口

## 允许的工程选择

可自行选择私有类/函数和测试夹具拆分，记录实际命令与版本。改变公开语义先同步Schema/规范/fixtures；若推翻已确认目标或固定用户边界，提供证据交还用户。实现后的design必须反映最终实现，不能保留已放弃方案作为执行步骤。

## 文档细化补充（2026-09-18）

- [docs/implementation/build-guide.md](../../../docs/implementation/build-guide.md)
- [docs/implementation/directory-layout.md](../../../docs/implementation/directory-layout.md)
- [docs/implementation/references.md](../../../docs/implementation/references.md)

目录中的源码路径是待建目标；搭建指南提供顺序，不覆盖本任务依赖。公开接口与权限仍以command-catalog/protocol为准。
