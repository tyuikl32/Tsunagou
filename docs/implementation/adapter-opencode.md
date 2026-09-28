# OpenCode 适配器实施与诊断

OpenCode 适配器翻译官方 Sessions、plugin 事件和 MCP 工具入口到 bridge-sdk。**2026-09-28 已在真实 OpenCode v2.0.18 宿主上完成 11 项共同基线实测**：两个真实会话由模型轮次驱动，经 stdio MCP bridge 与真实 daemon 交互；结果与脱敏证据见 [验收记录](../acceptance/opencode-11-baseline-live-2026-09-28.md)及[结构化 evidence](../research/evidence/opencode-2026-09-28-live.json)。旧 `opencode-ai 1.18.31` 无模型探针仅保留为历史部分证据。

三条宿主事实驱动适配器设计（v2.0.18 实测）：

- OpenCode **不向 local MCP server 传递会话 id 环境变量**；会话身份通过每次工具调用的 `_meta["ai.opencode/sessionID"]` 到达。bridge 以该字段的 `conversation_id:` digest 作为宿主会话身份，并与 ticket 绑定路径统一，保证同一会话跨调用、跨 bridge 重启身份一致。
- MCP 配置是项目级共享的，一个 stdio bridge 可能服务同一项目的多个会话。bridge 为每个会话分配独立私有 session 文件（`<stateDir>/sessions/bridge-session-<digest>.json`）；单会话宿主继续使用 `TSUNAGOU_SESSION_FILE`。
- `agent connect` 与 `agent enroll` 的 bridge 配置由同一生成器（`_bridge_environment`）产出，对 OpenCode 统一声明 `TSUNAGOU_HOST_META_KEY=ai.opencode/sessionID`（修复前 `agent enroll` 路径缺少该声明）。bridge 据此进入严格模式：**每一次**调用的 `_meta` 会话 id 缺失、空串或类型错误都立即拒绝（`conversation_metadata_required`），首次调用也不例外，绝不回落到启动时已恢复的其他会话凭据；未声明的宿主（环境变量身份或显式 session 文件）保持原有合法接入方式。

安装时只在用户选定 profile 写入非秘密 bridge 命令和适配器版本。token 由 bridge 私有存储注入，不出现在 prompt、tool args、静态 MCP 配置或环境变量。`agent connect` 目前不为 OpenCode 自动注册 MCP，需要把生成的 bridge_config 映射到 OpenCode 项目的 `mcp` 配置（`type: "local"`、`command`、`environment`）。

旧配置刷新与重载：重新运行 `agent connect --adapter opencode --profile <name>`（或 `agent enroll --adapter opencode --output-dir <dir>`）生成含声明的 bridge 配置；把生成配置的 `env`（至少新增的 `TSUNAGOU_HOST_META_KEY`）同步进 OpenCode 项目 `mcp.<name>.environment`，再执行 `opencode reload`（或重启宿主进程）使新配置生效。未刷新前 bridge 以兼容模式运行（不启用首调用硬校验）；刷新后首次工具调用即受严格检查约束，宿主在真实轮次中无需改动调用方式。卸载删除适配器生成的 profile 引用，保留 OpenCode 原生 session 与项目持久化。

`OpenCodeAdapter.getIdentity` 需要 host-issued `host_conversation_id_digest`；`probeCapabilities` 返回完整 11 项并保留每项 evidence。plugin 关闭、事件乱序、重复通知和恢复失败都应产生 degraded/unknown 诊断，不能假 ready。

自动唤醒（`wake.push`）仍为增强缺口：stdio bridge 没有宿主反向唤醒通道，bridge 报告 `unsupported`，不计入 11 项共同基线。

验证：

- `corepack pnpm --filter @tsunagou/adapter-opencode run check`
- `corepack pnpm exec vitest run packages/adapter-opencode/tests`
- `corepack pnpm --filter @tsunagou/bridge-server run build`（`tsc` 退出码 0）
- `python tools/docs/validate_docs.py`
