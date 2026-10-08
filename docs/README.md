# 文档导航与规范优先级

本目录于 2026-09-18 整理。目标是让用户能够理解和演示项目，让后续实施 Agent 有唯一、可追溯的开发基线。

**2026-09-28 修复入口：**[实测修复方案](implementation/live-test-repair-plan.md)、[FX1–FX7 任务索引](implementation/live-test-repair-tasks.json)。用户已授权实施，进度和未通过验收见任务索引；四项 FX 决定明确资源占用、破坏兼容升级、原 Desktop 唤醒和本机接口边界。先读此方案，避免沿历史 M1/PT 说明重复建任务。

## 阅读约定（2026-10-07 补）

本目录里有两类文档，**对"过时"的处理方式不同**，引用前请先分清：

| 类别 | 有哪些 | 规则 |
|---|---|---|
| **历史快照** | `docs/acceptance/*.md`（带日期的验收记录）、`docs/history/`（原始记录）、`**/evidence/`（证据） | 里面的**绝对路径、计数、版本号都是当天的**，不随后续改动更新。这不是"过时"，它们本来就是记录 —— **不要改，也不要拿它的数字当现状**（`docs/history/2026-09-18-source/` 按项目约定明文禁止修改） |
| **规范性文档** | `docs/implementation/`、`docs/overview/`、`docs/decisions/`、`docs/standalone/`、根 `README.md`、`USER_MANUAL.md`、`AGENTS.md` | **应当反映当前状态**；发现与代码不符就该改 |

**当前实测值（2026-10-07，改文档时拿这一行核对）**：声明命令 **105** ／ 装配 handler **62** ／ bridge 工具 **50**（main 50、worker 28）
／ `protocol/schemas` **121** ／ `protocol_data` **142** 个文件 ／ pytest **1169** 条（其中 **20 条失败**）／ vitest **134** 条（7 个文件）。
命令数以 `protocol/registry/commands.json` 为准；数字变了请同时改这一行。

两个已知的文档工具边界：`tools/docs/validate_docs.py` 只判**文件是否存在**，**不校验 `#锚点`**（已发现 1 处死锚点，见 `docs/acceptance/deepseek-harness-11-baseline-2026-10-01.md`）；
它的扫描范围也不含 `.agents/`、`packages/`、`web/`、`USER_MANUAL.md`。

> ⚠️ **一处尚未修的代码退化**：`a329cc2`（FX1~FX6，2026-09-29）删掉了 daemon 重启时的任务回收
> （释放资源／orphan Attempt／把未完成 Task 放回 `open`），而文档仍按"会回收"写。详见 [status-and-gaps 顶部横幅](standalone/status-and-gaps.md)。
> **这是代码要修，不是文档要改。**

## 分类

| 目录 | 读者与用途 | 是否直接约束新实现 |
|---|---|---|
| [standalone](standalone/README.md) | 当前代码审计、八模块缺口、最小成品实施与调试 | 当前阶段的实施顺序和完成标准；明确区分现状与待实现接口 |
| [overview](overview/product.md) | 用户、演示者：目的、原则、组成、流程、技术、效果 | 描述产品意图；具体接口以实施规范为准 |
| [implementation](implementation/README.md) | 实施与审查 Agent：实体、状态、接口、事务、异常、验收、任务 | 是 |
| [decisions](decisions/2026-09-18-boundary-decisions.md) | 决策来源与消歧；区分用户已确认与工程推导 | 是 |
| [research](research/README.md) | 外部资料与需要实测的假设 | 证据，不自动构成产品承诺 |
| [acceptance](acceptance/first-live-acceptance.md) | 原多宿主验收模板与历史记录 | 不阻塞 M1；当前操作单在 standalone |
| [history](history/README.md) | 48 份原始访谈、研究和专题记录 | 历史追溯，不直接覆盖当前规范 |
| `.trellis/spec` | 开发工作流注入的精简工程规则 | 是，引用本目录详细规范 |
| `.trellis/tasks` | 分批实施的 PRD、设计、步骤、验收和上下文 | 是，不得悄悄更改公共协议 |

## 唯一基线

优先级为：用户当前明确指令 → 已确认决策（新的覆盖旧的）→ [工程消歧 E01–E30](decisions/engineering-resolutions.md) → 当前实施规范 → 历史专题 → 研究建议。当前规范与已确认决定冲突时，先修规范，不能按方便的版本实现。

本轮 Plan 的新增知识保存在 [D161–D182](decisions/2026-09-18-boundary-decisions.md)；2026-09-20新增[D183：独立成品优先](decisions/2026-09-20-standalone-priority.md)；2026-09-22新增[项目本地 Agent 约束与快速初始化](decisions/2026-09-22-project-local-agent-bootstrap.md)以及[A2A 要求恢复与当前缺口](decisions/2026-09-22-a2a-requirement-reinstated.md)。此前 D1–D160、逐题回答和引用保存在历史目录。只包含“A/B/C”的回答必须连同原题阅读，不能脱离原选项重构用户意图。

[决策追溯表](decisions/traceability.md) 将本轮每项决定映射到当前规范和具体实施任务。

2026-09-20 用户要求关闭旧 Trellis 任务，当时执行索引为 [M1 / R1–R6](implementation/roadmap.md)。27 个历史任务（含此前已归档的 bootstrap 与文档任务）已按 20 项完成、7 项放弃归档，见[迁移清单](standalone/trellis-transition-2026-09-20.json)。2026-09-27 新增 PT 持久化溯源计划，其[机器索引](implementation/persistence-traceability-tasks.json)已记录 PT1–PT7 completed，当前源码包含这些产物；这不表示本轮 Desktop 实测问题已解决。新问题按 FX 索引推进，不整体重开旧任务；原[PT 方案](implementation/persistence-traceability-plan.md)保留追溯。

文档以中文说明、英文标识符组成。一个概念只使用一个规范英文名；界面可以显示中文。术语、状态和跨模块字段见[数据模型](implementation/data-model.md)，命令名字、权限和 URI 见[命令目录](implementation/command-catalog.md)。同一命令不在适配器中另起名字或更改权限语义。

新读者可以从[Agent快速接入](overview/agent-quick-start.md)、[子Agent加入与协作](overview/subagent-guide.md)、[CLI/HTTP说明书](overview/cli-http-manual.md)理解使用方式；A2A wire 边界和 wake 证据见[A2A边界实现](implementation/a2a-boundary.md)。本机控制台（中间层 + 页面）的组成、数据流、怎么验收与当前边界见[本机控制台](implementation/console.md)，前端侧逐字段契约在 [web/method.md](../web/method.md)。从 GitHub 安装的入口和 skill 行为见[安装 skill](../.agents/skills/tsunagou-install/SKILL.md)。实施Agent可从[搭建步骤](implementation/build-guide.md)、[预期目录](implementation/directory-layout.md)、[三Agent事实轨迹](implementation/coordination-walkthrough.md)开始。关键官方知识统一在[参考索引](implementation/references.md)，不要自行用不同SDK年代的示例替换当前协议。

## 更新约定

故障查询、时间戳与可选 SDK 追踪见[失败时间线与技术追踪](overview/diagnostics-and-tracing.md)。

1. 公共语义改变：先补决策记录，再同步实施规范、Schema、fixtures、命令目录、关联任务。不得只改一个 adapter。
2. 已明确授权的普通工程选择由实施 Agent 决定并留证；不要再次询问已确认的问题。
3. 用户目标、重大设计、固定 user-only 权限边界改变才交还用户。宿主实测失败须如实报告，不把 diagnostic-only 写成正式兼容。
4. 历史原稿不修改；新解释写入当前文档。文件移动另记迁移清单，保留可验证来源。
5. 产品尚无实现时写“规范/计划/验收目标”；实现完成后凭测试、版本和运行记录更新为“已实现/已验证”。
