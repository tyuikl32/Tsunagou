# Tsunagou

Tsunagou 是面向本机多个 Coding Agent 的协作后端。它让 Agent 共享任务事实、公开理解与假设、发现分歧、协商契约，并在暂停、断线和换人之后继续工作。

**当前状态（2026-09-20）：可启动的功能原型，尚非独立成品。** 已有102个Python测试、29个TS测试通过，但真实HTTP审计复现任务/契约重启丢失、幂等和主从任务边界等14项缺口，wheel独立安装还缺协议资源。当前优先完成[独立成品实施与调试](docs/standalone/README.md)，按实际业务闭环验收，不以宿主能力报告代替运行结果。T01–T17、T22的旧完成标记表示分项产物，不等于所有模块已接入运行时。

## 阅读入口

| 你希望了解什么 | 入口 |
|---|---|
| 当前进度、八模块缺口、独立运行的实施与调试 | [最小成品路径](docs/standalone/README.md) |
| 为什么做、解决什么问题、交付什么 | [项目说明](docs/overview/product.md) |
| 设计原则与 Agent 运行原则 | [两组原则](docs/overview/principles.md) |
| 八大模块如何配合 | [项目组成](docs/overview/architecture.md) |
| 用户和 Agent 实际怎么使用 | [运行流程](docs/overview/runtime-walkthrough.md) |
| 用户如何让子Agent加入、分工与恢复 | [子Agent指南](docs/overview/subagent-guide.md) |
| CLI与HTTP怎么用 | [简明说明书](docs/overview/cli-http-manual.md) |
| 技术、库与选型理由 | [技术说明](docs/overview/technology.md) |
| 怎样演示和判断是否成功 | [演示与验收](docs/overview/demo.md) |
| 开始实施 | [实施指导总入口](docs/implementation/README.md) |
| 按什么顺序搭建、文件放在哪里 | [搭建步骤](docs/implementation/build-guide.md)、[预期目录](docs/implementation/directory-layout.md) |
| 关键技术的官方资料 | [参考索引](docs/implementation/references.md) |
| 任务顺序、依赖与 Trellis 用法 | [实施路线图](docs/implementation/roadmap.md) |
| 本轮新增决策与历史依据 | [文档总目录](docs/README.md) |

Trellis 初始化记录的开发者：`tyuikl32`；平台：`codex`；初始化版本：`@mindfoldhq/trellis@0.6.17`。协同者先执行 `python .trellis/scripts/task.py list` 查看任务，再按路线图和任务依赖选择工作；任务记录中的负责人不应被当前操作者身份自动替换。

文档自检：`python tools/docs/validate_docs.py`。不会启动 Agent、修改项目业务数据或执行 Git 提交。
