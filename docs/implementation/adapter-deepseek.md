# DeepSeek Harness 适配器实施与诊断

此适配器面向 DeepSeek Harness 产品，不面向 DeepSeek 模型 API。2026-09-18 的无模型诊断使用 `@deepseek-ai/dsh 0.1.5-rc.2`；2026-10-01 的实测使用桌面版 `@deepseek-ai/dsh-desktop-runtime 0.2.0-rc.2`，当前证据与待核对项见[验收报告](../acceptance/deepseek-harness-11-baseline-2026-10-01.md)。

Harness 是 profile/plugin 宿主，外部 MCP 由 `@deepseek-ai/dsh-mcp-client` 提供。实测 MCP `tools/call` 不带逐调用会话身份；`DSH_SESSION_ID` 只到达 shell 工具子进程。`agent connect` 因此把 MCP 条目写到该会话 bridge 私有目录，以 `--patch <overlay>` 携带，避免写入共享 profile；旧的 profile 级条目停用为 `[]`。

**身份隔离仍有开放反例：另一会话复用 overlay 后会取得原身份。** 私有配置不等于运行时调用方证明；已撤回的命令行守卫不能作为支持依据。`dsh web` 多会话接入尚未通过验收。

安装由用户选择具体 Harness 版本和 profile；适配器只注册非秘密 bridge 入口。token 只由 bridge 私有内存或用户私有文件提供，不写 prompt、工具参数、静态 MCP 配置或环境。探针必须使用临时 `DSH_HOME` 与 `DSH_AGENTS_HOME`，不得读取或创建用户现有 Harness 会话。卸载撤销适配器注册并把 patch 还原成宿主可加载的空层 `[]`，保留 Harness 原生会话和项目历史。

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

当前尚未通过完整验收，发布门禁未升级。保留已有 bootstrap、注册/注销及相关回归修复；不自动开展身份插件、共享契约或黑板开发。

当前诊断入口为 `tools/conformance/probes/deepseek/probe.py`，使用既有 `common.py`。历史实测脚本已与其审查依赖一起归档，位置见[验收报告](../acceptance/deepseek-harness-11-baseline-2026-10-01.md)。官方参考：[deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)、[browser authentication](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/connection/src/browser-auth.ts)、[session controller](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/api/session-controller/src/index.ts)。验证入口：`corepack pnpm --filter @tsunagou/adapter-deepseek run check`、`corepack pnpm exec vitest run packages/adapter-deepseek/tests`、`python tools/docs/validate_docs.py`。
