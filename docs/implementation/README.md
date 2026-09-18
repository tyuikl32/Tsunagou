# 实施指导总入口

本组文件是首发实现的规范基线。现在只有规划和 Trellis 配置，没有产品代码；文中源代码路径是待建立的目录。接口/行为设计已足够开始工程工作，宿主 SDK 与精确依赖版本仍须通过 T01/T02 的可执行核验。

## 必读顺序

1. [设计与运行原则](../overview/principles.md)、[D161–D181](../decisions/2026-09-18-boundary-decisions.md)、[工程消歧](../decisions/engineering-resolutions.md)。
2. [架构与事务](architecture.md)、[术语与数据模型](data-model.md)、[协议](protocol.md)、[命令目录](command-catalog.md)。
3. 所属模块的详细方案，以及[跨模块生命周期](lifecycle.md)。桥接工作还须读[四宿主适配](adapters.md)和[运行提示与黑板](runtime-prompts.md)。
4. [验证与交付](validation.md)、[路线图与 Trellis 任务](roadmap.md)，再读取当前任务的 PRD/design/implement 和上下文 JSONL。

## 八大模块

| 编号与源码名 | 实施规范 | 主要交付 |
|---|---|---|
| 01 `projects` | [项目与权限](modules/01-projects.md) | 项目/根/仓库/授权/用户决定 |
| 02 `agents` | [接入与消息](modules/02-agents.md) | 身份/会话/主权限/收件箱 |
| 03 `tasks` | [任务调度](modules/03-tasks.md) | 单 owner、Attempt、阻塞、验收、委派 |
| 04 `cognition` | [认知协商](modules/04-cognition.md) | 报告/分歧/契约/风险 |
| 05 `resources` | [资源协调](modules/05-resources.md) | 意图/冲突/等待/Lease |
| 06 `workspaces` | [工作空间](modules/06-workspaces.md) | 隔离/基线/结果/整合/清理 |
| 07 `durability` | [持久化与恢复](modules/07-durability.md) | UoW/事件/Operation/Job/checkpoint/附件 |
| 08 `evaluation` | [观测与评估](modules/08-evaluation.md) | 审计/指标/实验/故障验证 |

## 如何处理剩余细节

实现者可以决定函数拆分、私有类名、索引实现与测试夹具写法；不得自行改变公开 DTO、命令权限、状态转换或用户边界。Schema 任务必须把本文的字段表落实为完整机器契约和正反例；新增字段要说明默认、可空、权限和兼容影响。

宿主私有 API、凭据安全交付、能力探测必须用实测证据落地。T02 若证明任何宿主无法达到正式共同基线，先记录失败并暂停该 adapter 的“正式支持”验收，向用户提出有证据的范围调整。不要以轮询代替可靠会话身份，也不要承诺动态修改 IDE 机械权限。

公开表格中的 `?` 表示可省略；`nullable` 才表示允许 JSON null。除明确标注外，输入对象禁止未知字段；不可变记录禁止 update。所有表自动携带项目/lineage 边界，详见数据模型。
