# DeepSeek Harness 0.2.0-rc.2 宿主接口实测记录

记录时间：2026-10-01（本机实测）。所有结论来自实际安装产物的 CLI、profile 组合器和 MCP 桥接源码，不引用旧文档结论。

## 1. 实际安装与版本

| 项目 | 实际值 | 来源 |
| --- | --- | --- |
| 产品 | DeepSeek Harness 桌面版 | `D:\dsh桌面版\DeepSeek Harness.exe` |
| 运行时包版本 | `@deepseek-ai/dsh-desktop-runtime@0.2.0-rc.2` | `app.asar/dsh/package.json` |
| 主包版本 | `@deepseek-ai/dsh@0.2.0-rc.2` | 同上 dependencies |
| CLI 版本 | `0.2.0-rc.2` | `dsh --version` |
| CLI 入口 | `D:\dsh桌面版\resources\runtime\cli\bin\dsh.cmd` | 启动器脚本内容 |
| 内置 Node | `v24.20.0`（`D:\deepseek harness\node.exe`） | `node --version` |
| 打包 Node/pnpm | `24.18.1` / `11.7.0` | `resources/runtime/versions.json` |

历史文档与旧证据里的 `@deepseek-ai/dsh 0.1.5-rc.2` **不是**当前安装版本，本轮全部结论按 0.2.0-rc.2 重测。

## 2. profile 与 patch 组合方式（官方 CLI 行为）

- `dsh [--profile] <name> [options] [app-args...]`；profile 位于 `$DSH_HOME/profiles/<name>`。
- 组合顺序：每个 bundle 层 → `cordis.patch.yml` → `--patch` 覆盖层。
- `--patch <path>` 可重复，是**启动器**选项，可叠加任意条目，不需要改动 profile 本体。
- patch 列表元素形状（读自 `@deepseek-ai/dsh-app-boot` 的 `applyEntryPatches`）：
  - `{ id, ...overrides }`：按 id 覆盖已有条目；**不是**深合并，整段 config 被替换；匹配不到会告警并跳过。
  - `{ insert: [entry, ...] }`：无 `id` 时追加到根条目列表；有 `id` 时插入到该 group 的 `config` 列表。
  - `{ id, insert: [...] }`：向指定 group 追加子条目。
- 一级条目直接写成 `- id: ... / name: ...`（不带 `insert`）会被当作覆盖，实测报
  `patch: entry "mcp-tsunagou" not found`。**必须使用 `insert`。**

## 3. MCP 接入面（`@deepseek-ai/dsh-mcp-client` 0.2.0-rc.2）

- 已随宿主发布但**默认未挂载**；`dsh-base` 只挂 `dsh-mcp-resources`。
- 每个 server 一条配置：
  ```yaml
  - id: mcp-tsunagou
    name: '@deepseek-ai/dsh-mcp-client'
    config:
      serverName: tsunagou
      transport: stdio
      command: node
      args: ['<bridge server.js>']
      env: { TSUNAGOU_*: '<path>' }
  ```
- 工具对模型暴露名为 `mcp__<serverName>__<rawName>`，因此 Tsunagou 的
  `context__project_read` 在 Harness 里是 `mcp__tsunagou__context__project_read`。
- stdio 子进程环境由 `scrubbedParentEnv()` 构造：丢弃匹配
  `/KEY|PASSWORD|SECRET|TOKEN/i` 的环境名与全部 `DSH_*`，再把配置里的 `env` 合并上去。
  → **宿主自身的 `DSH_SESSION_ID` 不会传进 MCP 子进程**；标识必须由配置显式给出，
  或由每次启动进程的外部环境提供。
- `tools/call` 只发送 `{ name, arguments }`，**不带** `_meta` 会话元数据
  （读自 `syncTools` 的 `client.callTool` 调用点）。因此 OpenCode 那套
  `_meta["ai.opencode/sessionID"]` 路由在 Harness 上**不成立**；Harness 每个会话需要
  自己的 bridge 进程与私有凭据文件，即每个会话一份 bridge 配置。

## 4. 会话、恢复与生命周期操作（实测）

| 操作 | Harness 实际命令 | 语义 |
| --- | --- | --- |
| 新建会话 | `dsh --profile headless "<task>"` | 新建 session，`--json` 首行给出 `sessionId` |
| 恢复会话 | `dsh --profile headless --session-id session-… "<task>"` | 恢复同一持久会话，turn 递增 |
| 机器可读事件 | `--json` | NDJSON：`session` / `status` / `thinking` / `text` / `tool_call` / `tool_result` / `final` |
| 会话持久化 | `$DSH_HOME/sessions/<encoded-cwd>/` | 按工作目录分目录 |
| compact | `@deepseek-ai/dsh-command-compact` + `dsh-compaction*` 插件 | 见能力二执行记录 |
| fork | web 会话控制器 `session/fork` | 见能力二执行记录 |

实测证据：隔离 home 中新建会话得到真实 `sessionId`，恢复同一会话后 turn 从 1 变为 2，
模型在恢复后的会话里真实调用了 `mcp__tsunagou__context__project_read`。

## 5. 对 Tsunagou 接入的含义

1. 身份来自宿主真实持久会话 id（`--json` 的 `session` 事件），不是 profile 名、PID、目录或模型自报。
2. 每个会话需要**独立**的 bridge 配置（`TSUNAGOU_TICKET_FILE` / `TSUNAGOU_SESSION_FILE` /
   `TSUNAGOU_STATE_DIR`），因为同一个 MCP 子进程不能靠调用元数据区分调用方。
3. 注册动作在 Harness 侧就是写 profile 的 `cordis.patch.yml`（或 `--patch` 覆盖层）里的
   `insert` 条目；本仓库 elysia 分支**尚未实现**这条注册路径（见 design 缺口表）。
4. `project bootstrap --host deepseek` 目前被 `unsupported_skill_host` 拒绝，也是缺口。

## 6. 未验证、不得写成 supported 的部分

- Harness 桌面应用「一个进程内多个会话共享同一个静态 MCP 条目」场景下如何做会话级身份：
  本轮只在「每个会话由自己的 Harness 进程/配置启动」的形态下取得真实证据。
- Harness 的 push/唤醒入口（`wake.push` 属增强项，不属本轮 11 项）。
