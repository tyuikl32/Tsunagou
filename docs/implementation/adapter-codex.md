# Codex 适配器实施与诊断

此适配器的职责是把 Codex CLI/App Server 的会话生命周期翻译为 bridge-sdk 的 host-neutral 端口。它不创建任务状态机、不决定权限、不把 Codex 的 Full Access 设置扩大为 Tsunagou 的强制能力。

## 版本和接入面

T02 当前唯一的本机证据是 `codex-cli 0.154.0-alpha.6.2` 的 disposable app-server stdio 探针。目标接入面是 app-server stdio、thread lifecycle 和 MCP；官方 CLI 入口与版本变化必须以运行时 probe 为准。相关官方入口：[Codex CLI features](https://developers.openai.com/codex/cli/features/)、[Codex CLI reference](https://developers.openai.com/codex/cli/reference/)。

## 安装与卸载边界

安装由用户或调度中心选择目标 Codex profile 后执行，适配器只能写入该 profile 的非秘密 bridge 命令和版本信息。token 保留在 bridge 的当前用户私有存储或进程内存，不写入 prompt、模型工具参数、静态 MCP 配置或子进程环境。

卸载应删除适配器生成的 profile 引用和 bridge 注册，不删除项目持久化、Codex 原生会话或用户文件。安装、卸载都必须能重复执行；若无法定位 profile，应返回 diagnostic 并保留原配置。

## 诊断输出

`CodexAdapter.getIdentity` 只接受 probe 已产生的 `host_conversation_id_digest`。缺少可靠 digest 返回 `undefined`，不能使用 PID、cwd、显示名或模型自报身份。`probeCapabilities` 对 11 项基线逐项返回 `supported`、`unsupported` 或 `unknown`；`evaluateConformance` 只有在全部有证据且为 `supported` 时才返回 `ready=true`。

当前 T02 证据：`identity.session_isolation` 有双 thread digest；resume/fork 是空 thread 的失败前置条件，compact/clear/profile identity 仍 unknown；任务、认知、契约、inbox、响应、重连和去重需要 bridge 真机测试。因此当前 Codex 适配器是 diagnostic-only，不能报告为正式共同基线支持。

生命周期事件只保留 `resume`、`compact`、`new`、`clear`、`fork`、`stop` 等统一语义，并携带来源 `codex_app_server` 或 `codex_cli`；适配器不把事件直接改写为领域状态。没有可验证的 native hook、wake、tool gate、presented evidence 或 managed stop 时，这些增强保持 unknown。

## 验证命令

```text
corepack pnpm --filter @tsunagou/adapter-codex run check
corepack pnpm exec vitest run packages/adapter-codex/tests
python tools/docs/validate_docs.py
```

测试中的 evidence fixture 只能验证 unknown/ready 判定和字段边界；它不能替代安装指定 Codex 版本后的真实 app-server 双会话、恢复、故障和工具调用证据。真实证据写入 `docs/research/evidence/` 时必须去除原始会话 ID、token、transcript 和私有路径。
