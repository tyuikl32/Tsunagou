# 跨机器协作第 0 步实测：远程 OpenCode Agent（2026-10-02）

**目的**：在真实跨机器拓扑上跑通一次完整接入，把"到底有多少手工动作、哪一步会崩"数清楚，
为"是否值得做一键化"（第 1 步）提供依据。本文只记录**实测**结果，不把未验证项写成已兼容。

**一句话结论**：全链路可达（远端 OpenCode 里的 Agent 成功登记进主机 daemon，身份
`af049246-4fae-4367-8bdf-500bf56958af`），但**一次接入需要 9 个手工动作、3 次跨机器往返**；
其中"模型 provider 必须自带"、"票只有 10 分钟寿命"、"宿主重启后首轮拿不到 MCP 工具"
三处是只有真跑才会撞到的门槛。

## 1. 拓扑与版本

| 角色 | 机器 | 关键事实 |
|---|---|---|
| 项目 + daemon + 控制台 | 主机（Windows，本机） | daemon 绑 `192.168.32.1:8765`；coordination root `E:\Tsunagou\projects\step0` |
| Agent 宿主 | VM（host-only **+ NAT** 两块网卡） | OpenCode v2.0.21、Node 24.19.0；项目副本 `C:\work\step0`；桥与状态 `C:\tsunagou-bridge\` |

- project_id：`65f031c4-0741-4cab-8561-d35cef387bfd`
- 网络边界：daemon **只绑 host-only 地址**；NAT 网卡只为 VM 取模型而加，daemon 不因它对外暴露。
- 形状：D188 Shape A（主机承载项目、daemon、控制台；只有 Agent 在远端），远端不需要 Python/CLI/daemon。
- 实测取值：`opencode run --session ses_step0-vm --model deepseek/deepseek-flash --auto "<提示词>"`。

## 2. 结果

| 验收项 | 结果 |
|---|---|
| 远端模型轮次驱动工具调用，经 stdio MCP bridge 到达主机 daemon | ✅ 通过 |
| Agent 在主机侧登记 | ✅ `role=worker`、`session_status=ready`、`connection_epoch=1` |
| 会话身份与票绑定一致（`_meta["ai.opencode/sessionID"]`） | ✅ 会话 id `ses_step0-vm` 与票的 `conversation_id` 相等 |
| 远端机器重启后**不需要重新签票**、身份不变 | ✅ 重启前后 `agent_id`、`session_id` 完全一致，凭据只来自本地 `bridge-session.json` |
| 断线重连被计入能力（`recovery.idempotent_reconnect`） | ⚠️ **未验证**：主机侧会话从未失效，桥是"续用"而非"重连"；`connection_epoch` 保持 1，该项仍留在 `missing_operational` |
| 主机侧主动丢失会话后的重连 | ⏳ 未做（需重启 daemon 制造真实断线） |

## 3. 手工动作清单（9 项、3 次跨机器往返）

| # | 动作 | 执行者 | 备注 |
|---|---|---|---|
| 1 | 远端装 OpenCode + Node | 人 | 前置条件 |
| 2 | 拷贝 bridge 打包 + 项目副本到远端 | 人 | 依赖树必须是真实目录；pnpm 的软链在远端跑不起来 |
| 3 | 在远端给宿主配一个**可用模型** | 人 | 默认 Zen 免费层在 CLI 里被拒（见 §4.2） |
| 4 | `opencode mcp add <name> --env … -- node …/dist/server.js` | 人 | 必须在**项目根目录**执行（cwd 敏感） |
| 5 | `opencode reload` | 人 | 配置有缓存 |
| 6 | 主机 `agent enroll --adapter opencode --conversation-id ses_…` | 人 | 会话 id 需要 `ses` 前缀 |
| 7 | 把 `ticket.json` 拷到远端约定路径 | 人 | 票只有 10 分钟寿命（见 §4.3） |
| 8 | `opencode run --session … --model … --auto "<提示词>"` | 人 | `run` 不吃 `--prompt`（见 §4.5） |
| 9 | 主机 `agent list` 核对 | 人 | 权威侧确认 |

往返次数：远端→主机（报会话 id/取票）→远端，共 3 次。

## 4. 实测发现

### 4.1 会话 id 可以由接入方指定（推翻先前假设）

`opencode run --session ses_step0-vm` 真的建出了 `id = ses_step0-vm` 的会话
（`opencode session list --format json` 可查，`directory` 为项目副本）。
客户端只校验 `ses` 前缀，后缀可用 `_`、`-`。因此 OpenCode 与 Codex 一样可以
"**先签票后连接**"，不需要"先建会话读 id 再签票"。

### 4.2 默认模型不可用（装机≠可用）

默认模型 `fledge-alpha-free` 属 OpenCode 官方免费层，从 CLI 调用直接失败：

```
Error: Error from provider (Console): OpenCode's free tier can only be used from within OpenCode
```

必须自带 provider（本次为 DeepSeek API）并显式给出 `--model deepseek/deepseek-flash`
（`provider/model` 形式，前缀不能省）。

### 4.3 票的 10 分钟寿命逼出"来回跑"的节奏

`agent enroll` 签发的票 TTL 600 秒。远端取票、配置宿主、发起会话这三步必须挤在 10 分钟内完成，
否则整轮作废、重新签票。这是本次最频繁中断测试节奏的一处。

### 4.4 宿主重启后**首轮**拿不到 MCP 工具

VM 重启后第一次 `opencode run` 时，模型报告工具目录里只剩宿主自己的工具、
`tsunagou` 的工具不见了。逐项排查：

- 项目 `opencode.json` 里的条目仍在；
- `opencode mcp list` 显示 `✓ tsunagou  connected`；
- 主机侧用相同环境变量（且**故意让票文件不存在**）直接启动 bridge：正常起来，
  `tools/list` 正常返回 `context__project_read`。

→ 判定为**冷启动时序**：服务与 MCP 握手未完成就发了第一轮；服务热了以后重试即恢复，
工具调用成功。不涉及配置丢失或凭据问题。

### 4.5 其它落地细节

- `opencode run` **没有 `--prompt`**：提示词是位置参数；`--prompt` 只属于顶层 `opencode`。
- `opencode mcp add` 写的是**当前目录**的 `opencode.json`，不是"最近的 git 仓库"。
- 没有 `mcp remove`；改配置后需要 `opencode reload`。
- 远端重启后**无需**重新注册或 reload，条目与本地会话文件都在，直接可用。

### 4.6 纠错：项目配置不要求 git 仓库

本文件同批更新了 [OpenCode 适配器实施](../implementation/adapter-opencode.md) 里
"项目配置只在 git 仓库里生效"的旧表述：本次实测的远端项目副本**没有 `.git`**
（`Test-Path .\.git` = `False`），但项目级 `opencode.json` 照常生效（MCP 连接成功、工具可调用）。
该约束在本版本上无法复现，按实测结果作废。

## 5. 未验证与后续

- **断线重连**：要让主机侧主动丢掉那条会话（重启 daemon 或等会话过期）后才能验证
  `recovery.idempotent_reconnect`、`connection_epoch` 递增。本次未做。
- **手工动作削减**：9 项里第 3–8 项（配模型、注册、reload、签票、传票、发起会话）是"一键化"
  的候选目标，属于第 1 步的范围。
- 本次未涉及 main/worker 角色分离、任务认领与交付，只验证到"Agent 到达并保持身份"。

## 6. 复现命令

主机侧（daemon + 签票）：

```powershell
tsunagou daemon start --coordination-root <项目根> --host <host-only 地址> --port 8765 --name "<名>" --host-wake disabled
tsunagou agent enroll --adapter opencode --installation-id opencode:<远端名> --conversation-id ses_<自选名> --output-dir <项目根>\.tsunagou\enroll-<远端名>
```

远端侧（注册 + 会话）：

```powershell
cd <项目副本>
opencode mcp add tsunagou --env TSUNAGOU_HTTP_URL=http://<主机 host-only 地址>:8765 `
  --env TSUNAGOU_PROJECT_ROOT=<项目副本> --env TSUNAGOU_TICKET_FILE=<票路径> `
  --env TSUNAGOU_SESSION_FILE=<会话文件路径> --env TSUNAGOU_STATE_DIR=<状态目录> `
  --env TSUNAGOU_DAEMON_STATE_DIR=<daemon 状态目录> `
  --env TSUNAGOU_HOST_META_KEY=ai.opencode/sessionID -- node <桥路径>\dist\server.js
opencode reload
opencode run --session ses_<自选名> --model deepseek/deepseek-flash --auto "call the context__project_read tool and print its JSON result verbatim"
```

## 7. 证据

- 主机 `agent list --json`：`agent_id af049246-4fae-4367-8bdf-500bf56958af`，
  `conversation_digest sha256:7069affc60ea4ba3c4c5775ae6e9662aea6c6b7cf0b8b657e9a9c06bf1e29b64`，
  `created_at 2026-10-02T05:44:59.338Z`。
- 远端工具返回：`project_id 65f031c4-0741-4cab-8561-d35cef387bfd`、`role worker`、
  `session.session_id a09cc686-6b29-4f49-836b-c95fb3f0bbe8`。
- 重启复测后主机侧 `last_activity_at` 刷新到 `2026-10-02T05:53:47.949Z`，`agent_id`、`session_id` 不变。

相关：[OpenCode 适配器实施](../implementation/adapter-opencode.md)、[宿主矩阵](../research/host-matrix.md)。
