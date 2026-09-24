# Agent 快速接入 Tsunagou

这是一份给用户和 Agent 一起使用的快速接入单。Agent 负责解释状态、调用自己的 bridge 工具和指导下一步；用户负责执行控制 CLI。用户不需要把 token、ticket 或宿主私密配置粘贴给 Agent。

如果还没有安装 Tsunagou，直接告诉正在目标业务项目中工作的 Agent：“在这个项目里从 GitHub 安装 Tsunagou”。安装 skill 会先保存当前 Git 项目根，再把仓库克隆到独立目录，安装 Python/Node 依赖，构建 bridge，并把接入 skill 安装到可发现的宿主 skill 目录；显式项目根会让 installer 自动完成一次 `project init`（缺失时）和 `project bootstrap`。如果用户只说“安装 Tsunagou”而没有选定业务项目，则保持 source/skill-only 安装。

如果项目已经通过 `project init` 初始化，也可以在安装时显式传入 `--project-root` 和 `--host`，让 installer 跳过重复初始化并调用一次 `project bootstrap`；这仍不会启动 daemon 或接入 Agent。

## 先判断依赖关系

Tsunagou 的接入由四层组成：

| 层 | 作用 | 是否必需 |
|---|---|---|
| Host adapter | 识别 Codex、OpenCode、DeepSeek Harness 等宿主，并提供宿主侧配置 | 是 |
| stdio MCP bridge | 用一次性 ticket 建立 Agent/session，之后通过 loopback HTTP 调 daemon | 是 |
| daemon | 执行认证、授权、scope、owner、revision、epoch、幂等和 SQLite 持久化 | 是 |
| Agent skill | 让 Agent 按固定顺序指导用户、识别 ready/degraded、使用 typed tools | 推荐；它不替代 bridge |
| Host hook | 自动注入上下文或提醒 | 可选；不能建立身份或权限 |

因此，正常接入不是单靠 skill，也不是 skill 和 hook 必须同时存在。安全边界在 daemon 和 bridge；skill 是 Agent 的操作向导；hook 只是宿主便利功能。当前项目内置的向导 skill 是 `.agents/skills/tsunagou-agent-onboarding/SKILL.md`。

## 用户执行的最小流程

以下命令在 PowerShell 中执行。路径和会话标识必须替换为真实值。

### 1. 建立协调项目

```powershell
$coordinationRoot = 'D:\Work\TsunagouControl'
New-Item -ItemType Directory -Force -Path $coordinationRoot | Out-Null
git init --quiet $coordinationRoot

$env:TSUNAGOU_PROJECT_ROOT = (Resolve-Path $coordinationRoot).Path
$env:TSUNAGOU_STATE_DIR = Join-Path $env:TSUNAGOU_PROJECT_ROOT '.tsunagou\local'

uv run python -m tsunagou project init `
  --coordination-root $env:TSUNAGOU_PROJECT_ROOT `
  --name '我的协作项目' `
  --objective '让主 Agent 和子 Agent 在同一契约下协作'
```

如果 `tsunagou` 已安装到 PATH，可以把 `uv run python -m tsunagou` 替换为 `tsunagou`。

### 2. 生成项目本地 Agent 入口

安装 checkout 不会自动修改业务项目。明确选择 Tsunagou checkout 后，在同一个协调根运行：

```powershell
uv run python -m tsunagou project bootstrap `
  --coordination-root $env:TSUNAGOU_PROJECT_ROOT `
  --source-root 'D:\Tools\Tsunagou' `
  --host codex
```

这一步会创建 `.tsunagou/project-integration.json`、`.tsunagou/agent-context.md`、`.agents/skills/tsunagou-project/SKILL.md` 和 `AGENTS.md` 的受管区块；不会创建 Agent、任命 main、发布任务，也不会写入 token。已有用户内容会保留，受管内容变化需要 `--refresh`。

### 3. 启动 daemon

```powershell
uv run python -m tsunagou daemon start --coordination-root $env:TSUNAGOU_PROJECT_ROOT --port 0
uv run python -m tsunagou daemon status --coordination-root $env:TSUNAGOU_PROJECT_ROOT
uv run python -m tsunagou doctor
```

成功标志是 `daemon status` 返回 running，且 `.tsunagou/local/endpoint.json`、`control.token` 和 `state.sqlite3` 已生成。控制 token 只保存在本机，不能放进对话。

### 4. 用一个命令接入当前宿主会话

正常接入不再要求用户查找 `conversation_id`、读取 `agent_id` 或手动复制 bridge JSON。每个主 Agent 或子 Agent 使用不同的 `--profile`，命令会创建独立的私有身份目录：

```powershell
# 如果当前目录不是 Tsunagou checkout，把 `uv run python` 改成
# `uv run --project <Tsunagou checkout> python`。
uv run python -m tsunagou agent connect `
  --adapter codex `
  --profile main `
  --role main
```

子 Agent 使用同一命令，把 profile 和角色改为自己的值：

```powershell
uv run python -m tsunagou agent connect `
  --adapter codex `
  --profile worker-01 `
  --role worker
```

命令由用户控制凭据执行，自动生成（或复用）该 profile 的会话绑定，签发一次性 ticket，写入 `.tsunagou\bridges\<adapter>-<profile>`，并在可用时执行 `codex mcp add` 注册逐会话 bridge。一个宿主对话只能使用一个 profile；新对话或 subagent 必须换 profile。`--role main` 是用户明确选择，daemon 只会在 bridge 兑换并达到 ready 后任命；Agent 不能通过 bridge 请求主权限。输出 `ticket_issued` 仍表示待宿主加载，Codex 通常需要重启或重新加载 MCP 配置。

命令不会把 ticket secret、session token 或 nonce 打印到 stdout。低层 `agent enroll` 仅用于恢复和诊断；普通流程不要求用户再执行 `agent appoint`。

如果输出中的 `host_registration` 是 `registered:<name>`，说明用户控制端已经
写入 Codex MCP 配置；已经运行的 Codex Desktop 进程可能仍持有旧的 MCP inventory。
新 profile 必须让宿主重新加载 MCP 后再调用 `context__project_read`，否则会误调用
旧 profile 的 bridge。若输出为 `codex_not_found`，不要继续用旧 ticket；确认
`CODEX_CLI_PATH` 或 Windows 的 Codex Desktop 安装路径可见后重新执行同一个 profile
的 `agent connect`。daemon 应在独立终端/进程中运行，避免重启宿主时连带结束 daemon。

### 5. 验证 Agent 已加入

让宿主启动 bridge，然后让当前 Agent 调用 `context__project_read`。必须看到自己的 `agent_id`、`session_id`、项目上下文和非 degraded 状态，才能继续工作。仅有宿主窗口、配置文件或 `ticket_issued` 都不算加入。

如果上下文显示 `ready_main`，说明 `--role main` 的用户请求已经由 daemon 应用。worker 不应执行任命，也不能通过 Full Access、另一个 HTTP 路径或修改 payload 获得主 Agent 权限。若恢复旧版本生成的 ticket，才使用低层 `agent appoint`，并且 ID 必须来自已兑换 bridge 的上下文。

## 接入成功后的第一轮工作

主 Agent 首次接入后先读取项目上下文，向用户报告：项目 ID、自己的 Agent/session 身份、当前角色、已有任务和未决决定。之后：

1. 主 Agent 使用 typed tools 创建并发布任务，明确 worker、验收者、scope、workspace 和资源意图。
2. worker 读取黑板并 claim 自己的任务；claim 还不是执行许可。
3. worker 提交理解、假设、不确定性和契约接受；分歧由主 Agent 组织处理。
4. preflight 通过后才 start，获得当前 Attempt 的执行 Grant 和资源 Lease。
5. 主 Agent 负责 Git 写操作、整合和审查；worker 只提交自己的结果和证据。
6. 用户只在重大设计、权限范围、冲突无法协调或项目完成时执行控制 CLI。

### 消息与唤醒

`message__send` 成功后，daemon 会把消息和 delivery 持久化。主 Agent 在下一次读取上下文或调用 `inbox__claim` 时可以看到它。当前通用 stdio bridge 是 pull-first：daemon 不会凭借一条消息自动创建新的 Codex 回合，也不会假装拥有宿主级 wake API。若宿主没有已验证的 wake 能力，空闲主 Agent 需要用户重新打开/触发对话；消息不会因此丢失，未 ACK 的 delivery 仍可恢复。

普通 task 完成不等于项目完成。用户确认项目完成时使用当前手册中的 `project complete` 命令；checkpoint 失败时查询 Operation，再使用 `checkpoint retry`。

## 断线和恢复

先执行：

```powershell
uv run python -m tsunagou daemon status --coordination-root $env:TSUNAGOU_PROJECT_ROOT
uv run python -m tsunagou doctor
uv run python -m tsunagou recover
```

如果 daemon 正常，重新启动同一个 bridge，让它使用自己的 `bridge-session.json` reconnect。不要将旧 session token 手工放入新配置。若 session 已撤销、epoch 过期或私有 session 文件丢失，用户重新执行 `agent enroll` 或受支持的 rebind 流程；不要创建第二个身份来冒充原 Agent。

## 什么时候需要 hook

hook 可以在 Codex 等宿主启动或提交 prompt 时注入项目上下文，例如提醒 Agent 读取本 skill 和当前任务。它不是跨宿主机制，不能保证 OpenCode 或 DeepSeek Harness 也执行相同逻辑。除非需要自动注入上下文，否则保持 hook 关闭也不影响 bridge 的认证和协作。

更完整的 CLI、HTTP 路由、错误码和安全要求见 [CLI/HTTP 使用说明书](cli-http-manual.md)；主 Agent、子 Agent 和用户的责任划分见 [子 Agent 接入指南](subagent-guide.md)。
