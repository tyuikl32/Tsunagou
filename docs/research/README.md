# 研究证据与后续实测

研究用于支撑设计，不把外部软件文档当作当前宿主已经可用的证明。下列原稿保留原始日期、引文和当时结论；当前采用边界由 implementation/decisions 决定。

| 主题 | 已保存材料 |
|---|---|
| 原题全文、附录与跨网站研究 | [Agent-to-Agent 深度研究](../history/2026-09-18-source/agent_to_agent_deep_research.md) |
| 四宿主与会话能力 | [adapter 调研](../history/2026-09-18-source/adapter_research.md)、[能力协商](../history/2026-09-18-source/adapter_capability_negotiation.md) |
| 协议与消息传输 | [传输研究](../history/2026-09-18-source/protocol_transport_research.md)、[消息协议](../history/2026-09-18-source/messaging_protocol.md) |
| 技术与版本窗口 | [技术栈研究](../history/2026-09-18-source/technology_stack_research.md)、[Python依赖窗口](../history/2026-09-18-source/python_dependency_window.md)、[CLI选型](../history/2026-09-18-source/cli_framework_research.md) |
| 持久恢复 | [Operation研究](../history/2026-09-18-source/durable_operations_research.md)、[Git范围](../history/2026-09-18-source/git_durability_scope.md) |

原题：[Agent-to-Agent](https://join.geek-tech.club/problems2/agent-to-agent)。原题研究已经归档，本轮主要做规范整理与实施准备，没有声称重新完成所有外部站点核验。

## 本轮核验：Trellis

2026-09-18 通过 npm 元数据与官方仓库 README 核验 `@mindfoldhq/trellis` stable 为 `0.6.17`，并实际执行 `npx --yes @mindfoldhq/trellis@0.6.17 init --codex --user tyuikl32 --yes --no-monorepo`。来源：[官方仓库](https://github.com/mindfold-ai/trellis)、[npm包](https://www.npmjs.com/package/@mindfoldhq/trellis)。

使用 `--no-monorepo` 是因为当前只有文档，没有可供初始化器识别的产品 packages；它不改变已定 Python+pnpm monorepo 结构。T01 建包后补 Trellis package 配置。已安装 Codex skills/agents/hooks，并读取初始化器和 task CLI 的实际接口。

hooks 文件存在不代表 Codex 已启用或信任。初始化器提示需要宿主启用 hooks 功能并在 UI 批准一次；本轮未修改全局配置或代替用户完成宿主信任。没有 hooks 仍可使用任务脚本和显式读取 JSONL/PRD/spec，不影响规划材料完整性。

## 实施前要消除的可行性不确定

- T01：真实注册表与 Windows 环境是否满足选定版本窗口；精确版本和 peer dependencies 由锁文件证明。
- T02：四宿主的 conversation identity、会话隔离、MCP传输和secret交付；官方 Python/TS MCP SDK 的具体版本与ASGI/stdio接口。
- T18–T21：每个正式版本的11项共同基线真宿主测试；增强能力逐项注明证据。
- T24：对照实验是否达到效果门槛。当前没有数据，不能提前宣传提效百分比。

核验失败要保存URL/版本/命令/脱敏输出、失败条件、替代方案与范围影响；具体安装限制只阻塞相关任务，不重开全部产品访谈。
