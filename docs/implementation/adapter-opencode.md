# OpenCode 适配器实施与诊断

OpenCode 适配器翻译官方 Sessions、plugin 事件和 MCP 工具入口到 bridge-sdk。**2026-09-28 已在真实 OpenCode v2.0.18 宿主上完成 11 项共同基线实测**：两个真实会话由模型轮次驱动，经 stdio MCP bridge 与真实 daemon 交互；结果与脱敏证据见 [验收记录](../acceptance/opencode-11-baseline-live-2026-09-28.md)及[结构化 evidence](../research/evidence/opencode-2026-09-28-live.json)。旧 `opencode-ai 1.18.31` 无模型探针仅保留为历史部分证据。

三条宿主事实驱动适配器设计（v2.0.18 实测）：

- OpenCode **不向 local MCP server 传递会话 id 环境变量**；会话身份通过每次工具调用的 `_meta["ai.opencode/sessionID"]` 到达。bridge 以该字段的 `conversation_id:` digest 作为宿主会话身份，并与 ticket 绑定路径统一，保证同一会话跨调用、跨 bridge 重启身份一致。
- MCP 配置是项目级共享的，一个 stdio bridge 可能服务同一项目的多个会话。bridge 为每个会话分配独立私有 session 文件（`<stateDir>/sessions/bridge-session-<digest>.json`）；单会话宿主继续使用 `TSUNAGOU_SESSION_FILE`。
- `agent connect` 与 `agent enroll` 的 bridge 配置由同一生成器（`_bridge_environment`）产出，对 OpenCode 统一声明 `TSUNAGOU_HOST_META_KEY=ai.opencode/sessionID`（修复前 `agent enroll` 路径缺少该声明）。bridge 据此进入严格模式：**每一次**调用的 `_meta` 会话 id 缺失、空串或类型错误都立即拒绝（`conversation_metadata_required`），首次调用也不例外，绝不回落到启动时已恢复的其他会话凭据；未声明的宿主（环境变量身份或显式 session 文件）保持原有合法接入方式。

安装时只在用户选定 profile 写入非秘密 bridge 命令和适配器版本。token 由 bridge 私有存储注入，不出现在 prompt、tool args、静态 MCP 配置或环境变量。**2026-10-02 起，`agent connect` 与控制台的接入流程自己注册**：`opencode mcp add` 把 bridge 写进项目的 `opencode.json`（`type: "local"`、`command`、`environment`），**一条条目对一个会话**（一条条目只带一份票 + 一个会话文件，第二个会话要全新接入就得有自己的条目）。

从控制台接入时，会话名由**控制台先发**：票绑 `ses_<profile>`，页面的等待提示就是"用这个名字开会话"。这不是额外机制，而是把"先签票、后连接"用在需要它的地方——bridge 只认宿主每次调用报上来的 `_meta` 会话 id，控制台编一个别的 id 写进票，票会被当成"别人的"而丢掉（详见[控制台接入形态](../decisions/2026-10-02-console-enroll-modes.md)）。名字记在 bridge 目录的 `host-identity.json` 里，重试沿用同一个，不会一次换一个会话。

注册路径上实测出来的四个约束（OpenCode v2.0.21，都写进了 `platform/host_registration.py`）：

- `add` 写的是**当前目录**的 `opencode.json`（不是“最近的 git 仓库”），所以命令必须在**项目根目录**下执行；
- **没有 `mcp remove`**：注销只能改文件 —— 只删“命名符合我们的规则、且启动的确实是我们那座桥”的那一条；文件解析不出来就一个字都不改；
- 配置有**缓存**，改完要 `opencode reload`（或重启宿主）才生效；
- 想查它到底读没读到，用 `opencode debug config`；`opencode mcp list` 会真的去启动每个条目探活、又没有 `--json`，不适合当判据。

另外：早期记录的"项目配置只在 **git 仓库**里生效"**已按 2026-10-02 跨机器实测作废** —— 远端项目副本没有 `.git`（`Test-Path .\.git` = `False`），项目级 `opencode.json` 照常生效（`opencode mcp list` 报 `connected`、工具可调用）。见[跨机器第 0 步实测](../acceptance/cross-machine-step0-2026-10-02.md)。

会话身份的另一条实测：`--session` 的值可以由接入方**自己指定**（只要求 `ses` 前缀，后缀随意），宿主会以该 id 建会话，因此 OpenCode 也能"先签票、后连接"，与 Codex 的 routing-dir 方案效果等价。

旧配置刷新与重载：重新运行 `agent connect --adapter opencode --profile <name>`（或 `agent enroll --adapter opencode --output-dir <dir>`）生成含声明的 bridge 配置；把生成配置的 `env`（至少新增的 `TSUNAGOU_HOST_META_KEY`）同步进 OpenCode 项目 `mcp.<name>.environment`，再执行 `opencode reload`（或重启宿主进程）使新配置生效。未刷新前 bridge 以兼容模式运行（不启用首调用硬校验）；刷新后首次工具调用即受严格检查约束，宿主在真实轮次中无需改动调用方式。卸载删除适配器生成的 profile 引用，保留 OpenCode 原生 session 与项目持久化。

`OpenCodeAdapter.getIdentity` 需要 host-issued `host_conversation_id_digest`；`probeCapabilities` 返回完整 11 项并保留每项 evidence。plugin 关闭、事件乱序、重复通知和恢复失败都应产生 degraded/unknown 诊断，不能假 ready。

自动唤醒（`wake.push`）仍为增强缺口：stdio bridge 没有宿主反向唤醒通道，bridge 报告 `unsupported`，不计入 11 项共同基线。

验证：

- `corepack pnpm --filter @tsunagou/adapter-opencode run check`
- `corepack pnpm exec vitest run packages/adapter-opencode/tests`
- `corepack pnpm --filter @tsunagou/bridge-server run build`（`tsc` 退出码 0）
- `python tools/docs/validate_docs.py`
