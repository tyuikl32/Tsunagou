# DeepSeek Harness 适配器实施与诊断

此适配器面向 T02 指定的 DeepSeek Harness 产品，不面向 DeepSeek 模型 API。2026-09-18 已用官方 `@deepseek-ai/dsh 0.1.5-rc.2` 做临时家目录的真实无模型 probe；这只证明 Web 启动、一次性 token 交换、HttpOnly cookie 认证、同目录创建独立 session 和 session 列表，不能生成完整共同基线证据。

安装由用户选择具体 Harness 版本和 profile；适配器只注册非秘密 bridge 入口。token 只由 bridge 私有内存或用户私有文件提供，不写 prompt、工具参数、静态 MCP 配置或环境。探针必须使用临时 `DSH_HOME` 与 `DSH_AGENTS_HOME`，不得读取或创建用户现有 Harness 会话。卸载撤销适配器注册，保留 Harness 原生会话和项目历史。

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

`DeepSeekAdapter` 要求 Harness 发出的持久 conversation digest；事件重放由 bridge command_id/去重层处理，适配器不复制任务或消息状态机。缺少 session event、分支/恢复证据或真实工具入口时，11 项全部保持 unknown，不能宣称正式支持。

真实验收要锁定 Harness 版本，运行并行 session、恢复、重复事件、MCP/typed tools 和故障测试，再提交脱敏 evidence。当前证据文件为 `docs/research/evidence/deepseek-2026-09-18.json`，`identity.session_isolation` 为 supported，其余 10 项仍 unknown，因此 release gate 继续失败。官方参考：[deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)、[browser authentication](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/connection/src/browser-auth.ts)、[session controller](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/api/session-controller/src/index.ts)。验证：`corepack pnpm --filter @tsunagou/adapter-deepseek run check`、`corepack pnpm exec vitest run packages/adapter-deepseek/tests`、`python tools/docs/validate_docs.py`。
