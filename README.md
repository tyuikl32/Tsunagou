# Tsunagou

Tsunagou 是面向本机多个 Coding Agent 的协作后端。它让 Agent 共享任务事实、公开理解与假设、发现分歧、协商契约，并在暂停、断线和换人之后继续工作。

**当前状态：设计基线和实施任务已建立，产品尚未实现。** 文档中的产品命令、接口和运行流程是待交付规范，不代表现在可执行。当前可使用的是 Trellis 项目管理和文档校验。

## 阅读入口

| 你希望了解什么 | 入口 |
|---|---|
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

Trellis 开发者：`tyuikl32`；平台：`codex`；初始化版本：`@mindfoldhq/trellis@0.6.17`。先执行 `python .trellis/scripts/task.py list` 查看任务，再按路线图选择依赖已完成的任务。首次工程任务是 T01，四宿主可行性核验 T02 可以同步推进研究。

文档自检：`python tools/docs/validate_docs.py`。不会启动 Agent、修改项目业务数据或执行 Git 提交。
