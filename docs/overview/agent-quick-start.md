# Agent 快速接入 Tsunagou

这是一份给用户和 Agent 一起使用的快速接入单。Agent 负责解释状态、调用自己的 bridge 工具和指导下一步；用户负责执行控制 CLI。用户不需要把 token、ticket 或宿主私密配置粘贴给 Agent。

如果还没有安装 Tsunagou，直接告诉 Agent：“从 GitHub 安装 Tsunagou”。可用的安装 skill 会把仓库克隆到用户选择的目录，安装 Python/Node 依赖，构建 bridge，并把接入 skill 安装到项目和可发现的宿主 skill 目录。安装完成后才进入下面的项目初始化流程。

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

### 2. 启动 daemon

```powershell
uv run python -m tsunagou daemon start --coordination-root $env:TSUNAGOU_PROJECT_ROOT --port 0
uv run python -m tsunagou daemon status --coordination-root $env:TSUNAGOU_PROJECT_ROOT
uv run python -m tsunagou doctor
```

成功标志是 `daemon status` 返回 running，且 `.tsunagou/local/endpoint.json`、`control.token` 和 `state.sqlite3` 已生成。控制 token 只保存在本机，不能放进对话。

### 3. 为当前宿主会话申请 bridge 配置

每个主 Agent 或子 Agent 会话都要有自己的 `installation_id`、`conversation_id` 和输出目录：

```powershell
$bridgeDir = Join-Path $env:TSUNAGOU_PROJECT_ROOT '.tsunagou\bridges\current'
uv run python -m tsunagou agent enroll `
  --adapter codex `
  --mode attach `
  --installation-id codex-current `
  --conversation-id '<当前宿主的真实会话标识>' `
  --output-dir $bridgeDir
```

输出 `ticket_issued` 只表示票据签发。把输出目录中的 adapter JSON 加载到宿主的 MCP 配置入口；不要打开或复制 `ticket.json` 的秘密内容。bridge 成功兑换后会保存当前 conversation 专属的 session 文件并删除一次性 ticket。同一 IDE 的另一对话或 subagent 必须重新 enroll，不能复用该文件。

### 4. 验证 Agent 已加入

让宿主启动 bridge，然后让当前 Agent 调用 `context__project_read`。必须看到自己的 `agent_id`、`session_id`、项目上下文和非 degraded 状态，才能继续工作。仅有宿主窗口、配置文件或 `ticket_issued` 都不算加入。

如果当前 Agent 要成为主 Agent，用户从返回上下文取得真实 `agent_id` 后执行：

```powershell
uv run python -m tsunagou agent appoint AGENT_ID
```

worker 不应执行任命，也不能通过 Full Access、另一个 HTTP 路径或修改 payload 获得主 Agent 权限。

## 接入成功后的第一轮工作

主 Agent 首次接入后先读取项目上下文，向用户报告：项目 ID、自己的 Agent/session 身份、当前角色、已有任务和未决决定。之后：

1. 主 Agent 使用 typed tools 创建并发布任务，明确 worker、验收者、scope、workspace 和资源意图。
2. worker 读取黑板并 claim 自己的任务；claim 还不是执行许可。
3. worker 提交理解、假设、不确定性和契约接受；分歧由主 Agent 组织处理。
4. preflight 通过后才 start，获得当前 Attempt 的执行 Grant 和资源 Lease。
5. 主 Agent 负责 Git 写操作、整合和审查；worker 只提交自己的结果和证据。
6. 用户只在重大设计、权限范围、冲突无法协调或项目完成时执行控制 CLI。

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
