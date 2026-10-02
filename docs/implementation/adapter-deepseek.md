# DeepSeek Harness 适配器实施与诊断

此适配器面向 DeepSeek Harness 产品，不面向 DeepSeek 模型 API。2026-09-18 的无模型诊断使用 `@deepseek-ai/dsh 0.1.5-rc.2`；2026-10-01 的实测使用桌面版 `@deepseek-ai/dsh-desktop-runtime 0.2.0-rc.2`，当前证据与待核对项见[验收报告](../acceptance/deepseek-harness-11-baseline-2026-10-01.md)。

Harness 是 profile/plugin 宿主，stock `@deepseek-ai/dsh-mcp-client` 的 `tools/call` 不带逐调用会话身份；本项目已有身份 provider 从本次执行上下文的 `exec.agent.session.id` 取得真实身份并添加 metadata。2026-10-02 的 Desktop 接入使用实际 Desktop profile 中无凭据的共享 provider，每个真实聊天分别选择自己的私有路由。

正常 Desktop 入口是已安装 CLI 的 `agent prepare --adapter deepseek`，随后由原聊天调用宿主本地 `tsunagou_connect` 和 MCP `context__project_read`。prepare 仅配置插件；connect 使用宿主内的真实会话和目录调用固定安装 CLI，不经 shell 工具的受限进程启动路径。helper 的 `host_ready:false` 表示原聊天尚待自行读取验证，**不是**唤醒状态；DeepSeek 不启用 Codex 专属 wake。首次优先热重载，必要时一次完整重启；无需每个聊天携带临时 overlay。

身份不明、私有路由缺失或不匹配时拒绝调用；不能回退到别人的凭据。旧 stock overlay 的借用反例和已撤回命令行守卫只作历史，不能证明新 Desktop 入口。低层 headless overlay 兼容路径保留。注销仅删除指定会话或项目的私有路由，保留共享 provider、其他配置、原生会话与项目历史。

安装由用户选择具体 Harness 版本和 profile；静态配置只有可信程序和私有路由位置。token 只由 bridge 私有内存或用户私有文件提供，不写 prompt、工具参数、静态 MCP 配置或环境。以下无模型 Web 探针继续使用临时 `DSH_HOME` 与 `DSH_AGENTS_HOME`；用户明确授权的 Desktop 原聊天验收则核对指定聊天的新调用，不能用另起 web/headless 结果替代，也不导出原始凭据或完整聊天。

官方 Web 流程是：`dsh web --no-open` 打印带 token 的本机根 URL；首次 GET 只用于交换一次 token，服务返回绑定 Host 的 HttpOnly、SameSite cookie 并重定向到无 token 的 `/`；之后对 `/api` 发送 `client-request` envelope，`method` 必须与路径末段一致，Remote 参数放在 `payload.args`。session-controller 的业务 endpoint 包括 `session/list`、`session/create`、`session/fork`、`session/page` 和 `session/follow`。探针只使用 `session/create` 与 `session/list`，不执行模型 prompt、fork 或持久用户会话操作。

## 可复现的临时探针步骤

以下步骤是实现规范，不代表当前仓库已经替用户安装 Harness。每次探针都必须使用新的临时家目录；不要省略两个环境变量，也不要把打印出的 token 写入仓库或长期 shell 配置。

```powershell
$probeHome = Join-Path $env:TEMP "tsunagou-dsh-home"
$probeAgents = Join-Path $env:TEMP "tsunagou-dsh-agents"
$env:DSH_HOME = $probeHome
$env:DSH_AGENTS_HOME = $probeAgents
$env:DSH_TELEMETRY_DISABLED = "1"
npx --yes @deepseek-ai/dsh@0.1.5-rc.2 web --no-open --host 127.0.0.1 --port 0
```

在同一临时服务仍运行时，从启动输出中把 token 放入当前进程的 `DSH_WEB_TOKEN` 环境变量，再运行：

```powershell
$env:DSH_WEB_TOKEN = "<token-from-the-temporary-launch-url>"
uv run python tools/conformance/probes/deepseek/probe.py `
  --base-url http://127.0.0.1:<port> `
  --directory (Get-Location) `
  --output docs/research/evidence/deepseek-<date>.json
```

探针只会写 keyed identity digest、检查名和 `unknown`/`supported` 状态；完成后先停止 `dsh web`，再删除 `$probeHome` 与 `$probeAgents`。若无法证明服务使用临时家目录，应丢弃结果，不得覆盖已有 evidence。

`DeepSeekAdapter` 要求 Harness 发出的持久 conversation digest（即宿主持久会话 id）；事件重放由 bridge command_id/去重层处理，适配器不复制任务或消息状态机。

2026-10-02 用户已授权并实施普通 Desktop 接入修复，真实入口、回归和剩余场景统一记录在验收报告。共享协议、发布门禁与 Codex/OpenCode 配置未改；本轮不扩展共享契约、黑板或自动唤醒功能。

当前诊断入口为 `tools/conformance/probes/deepseek/probe.py`，使用既有 `common.py`。历史实测脚本已与其审查依赖一起归档，位置见[验收报告](../acceptance/deepseek-harness-11-baseline-2026-10-01.md)。官方参考：[deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)、[browser authentication](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/connection/src/browser-auth.ts)、[session controller](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/api/session-controller/src/index.ts)。验证入口：`corepack pnpm --filter @tsunagou/adapter-deepseek run check`、`corepack pnpm exec vitest run packages/adapter-deepseek/tests`、`python tools/docs/validate_docs.py`。
