# 实施指导总入口

本组文件是首发实现的规范基线。T01–T17、T22 已有产品代码和测试；T18–T21 为 diagnostic adapter，T23–T24 为集成/演示与实验准备。文中仍标为“待实测”的宿主能力必须由真实证据补齐，不能由 simulator 通过替代。

## 必读顺序

1. [设计与运行原则](../overview/principles.md)、[D161–D181](../decisions/2026-09-18-boundary-decisions.md)、[工程消歧](../decisions/engineering-resolutions.md)。
2. [架构与事务](architecture.md)、[术语与数据模型](data-model.md)、[协议](protocol.md)、[命令目录](command-catalog.md)。
3. 所属模块的详细方案，以及[跨模块生命周期](lifecycle.md)。桥接工作还须读[四宿主适配](adapters.md)和[运行提示与黑板](runtime-prompts.md)。
4. [验证与交付](validation.md)、[路线图与 Trellis 任务](roadmap.md)，再读取当前任务的 PRD/design/implement 和上下文 JSONL。

## 从文档走到代码

| 需要解决的问题 | 详细指导 |
|---|---|
| 具体先建什么、如何逐阶段验证 | [从空工程到首发的搭建步骤](build-guide.md) |
| 文件放在哪里、谁拥有、哪些是生成物 | [预期目录与文件责任](directory-layout.md) |
| 三个Agent实际怎样接入、协商、挂起与恢复 | [逐步协作事实轨迹](coordination-walkthrough.md) |
| CLI参数如何映射已有权限和HTTP | [CLI外壳契约](cli-contract.md) |
| 哪些官方资料支持我们的实现选择 | [外部知识索引](references.md) |
| Codex 适配器如何安装、诊断和验收 | [Codex 适配器实施与诊断](adapter-codex.md) |
| OpenCode 适配器如何安装、诊断和验收 | [OpenCode 适配器实施与诊断](adapter-opencode.md) |
| ZCode 适配器如何安装、诊断和验收 | [ZCode 适配器实施与诊断](adapter-zcode.md) |
| DeepSeek Harness 适配器如何安装、诊断和验收 | [DeepSeek Harness 适配器实施与诊断](adapter-deepseek.md) |
| 观测、实验和报告如何固定口径 | [评估模块运行约定](evaluation-runbook.md) |
| 集成测试和发布门禁如何判定 | [集成与发布门禁](release-gates.md) |
| 首发前逐项检查什么 | [首发交付清单](release-checklist.md) |
| 向用户解释如何操作 | [CLI/HTTP简明手册](../overview/cli-http-manual.md)、[子Agent指南](../overview/subagent-guide.md) |

上述指南的新增文件名/CLI外壳参数是工程细化，不新增领域动作或用户权限；目录树明确区分待建源码与当前已有文档。示例中的身份别名、版本占位值不能直接作为生产请求。

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
