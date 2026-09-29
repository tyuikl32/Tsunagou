# Codex 适配器实施与诊断

## 2026-09-28 FX3 实施进展

新增 `codex_desktop_app` provider，经宿主继承的本机 app-tools 管道调用原 Desktop 线程。独立 Python 发送及发送方回合结束后的后台自唤醒均已真实通过，见 [空闲调用者记录](../../.trellis/tasks/09-28-fx3-desktop-wake/research/desktop-idle-caller.json)。这是传输实测，尚不能替代完整接入、持久 inbox 和双 Worker 验收。

`NativeAppToolsClient` 使用应用插件的长度前缀 JSON-RPC；保留真实 caller thread，使用插件自身的 `mcp-turn-*`/`mcp-call-*` 请求关联回退，不假冒模型活跃回合。私有绑定持有 thread/endpoint；对外只返回 digest。普通唤醒不改变 model、approval 或 sandbox。旧 `desktop_attach` 的独立 listener 只保留旧实验路径，不作为本轮原会话唤醒方案。

初次绑定仍经 U 控制入口。`session.reconnect` 的可选私有 `host_binding_refresh` 只能刷新当前已绑定 Agent 的连接及代次，不能改目标 thread；在凭据事务提交后写 private binding，私有请求 journal 重试可补全。同代次没有变化时无需反复重连。FX4 已接通 prepare/request-file/connect，正常共享 MCP 配置只需 TSUNAGOU_ROUTING_DIR；每次调用从宿主 `_meta.threadId` 选择私有路由，不用进程全局 session。原会话完整产品验收仍待收口。

消息创建与 `host_wake` outbox 同事务；普通 command/MCP 与 A2A 共用投递。空闲启动、忙时排队合并；失去响应先检查带 wake 关联引用的原回合；daemon 重启继续观察原会话，不复制身份或覆盖失败。宿主接受、turn 开始与 inbox 呈现分开记录。

以下 T02/阶段 A/B 说明保留版本历史；其中无需唤醒的降级与旧 Desktop 限制已由 FX-D03/04 覆盖，不能作为本轮完成标准。

此适配器的职责是把 Codex CLI/App Server 的会话生命周期翻译为 bridge-sdk 的 host-neutral 端口。它不创建任务状态机、不决定权限、不把 Codex 的 Full Access 设置扩大为 Tsunagou 的强制能力。

## 版本和接入面

T02 的历史证据包含 `codex-cli 0.154.0-alpha.6.2`；本轮阶段 A 在 Windows `codex-cli 0.155.0-alpha.16` 上取得 managed app-server stdio、thread lifecycle、turn lifecycle 和 typed MCP presentation 证据。目标接入面是 app-server stdio、thread lifecycle 和 MCP；官方 CLI 入口与版本变化必须以运行时 probe 为准。相关官方入口：[Codex CLI features](https://developers.openai.com/codex/cli/features/)、[Codex CLI reference](https://developers.openai.com/codex/cli/reference/)。

## 安装与卸载边界

安装由用户或调度中心选择目标 Codex profile 后执行，适配器只能写入该 profile 的非秘密 bridge 命令和版本信息。token 保留在 bridge 的当前用户私有存储或进程内存，不写入 prompt、模型工具参数、静态 MCP 配置或子进程环境。

卸载应删除适配器生成的 profile 引用和 bridge 注册，不删除项目持久化、Codex 原生会话或用户文件。安装、卸载都必须能重复执行；若无法定位 profile，应返回 diagnostic 并保留原配置。

## 诊断输出

`CodexAdapter.getIdentity` 只接受 probe 已产生的 `host_conversation_id_digest`。缺少可靠 digest 返回 `undefined`，不能使用 PID、cwd、显示名或模型自报身份。`probeCapabilities` 对 11 项基线逐项返回 `supported`、`unsupported` 或 `unknown`；`evaluateConformance` 只有在全部有证据且为 `supported` 时才返回 `ready=true`。

当前 T02 证据：`identity.session_isolation` 有双 thread digest；resume/fork 是空 thread 的失败前置条件，compact/clear/profile identity 仍 unknown；任务、认知、契约、inbox、响应、重连和去重需要 bridge 真机测试。阶段 A 的 managed app-server 已取得当前 Windows Codex 版本的真实 initialize、thread/start、turn/start、`turn/completed` 和 disposable A2A context/inbox presentation 证据，并已验证 daemon restart 将未决 attempt 标为 `unknown`、同语义消息可重试完成、loopback callback 和旧 epoch 拒绝，见 [managed app-server probe](../research/evidence/codex-app-server-managed-2026-09-23.json)；method catalogue 仍保持 unknown。阶段 B 已实现显式 `desktop_attach` provider、Unix socket proxy、thread/read probe、CLI/HTTP 登记、bridge 配置随 `thread/resume` 与 `turn/start` 传递，以及无隐式 thread/start 约束；官方公开 Unix endpoint 已真实恢复 Desktop-originated thread 并由 A2A 观察到 `thread_resumed`/`turn_started`。运行中的 Desktop stdio 进程仍没有自动可发现 endpoint，不能把 B 写成无需用户提供 endpoint 的任意新对话自动唤醒能力。

2026-09-19 对本机 `codex-cli 0.155.0-alpha.9.2` 的复测结果与十项后续操作见 [Codex 单宿主试验](../acceptance/codex-pilot-2026-09-19.md)；新版本仍只证明原生会话隔离，真实 `agent enroll` 停在 `ticket_required`。

生命周期事件只保留 `resume`、`compact`、`new`、`clear`、`fork`、`stop` 等统一语义，并携带来源 `codex_app_server` 或 `codex_cli`；适配器不把事件直接改写为领域状态。Codex 的 `HostWakeAdapter` 只有注入真实 App Server probe evidence 后才返回 `wake=supported`；默认是 `unsupported`，wake prompt 只携带 `wake_id/task_id/assignment_id` 和 inbox/`worker.ready` 指令，不携带任务正文或凭据。没有可验证的 native hook、wake、tool gate、presented evidence 或 managed stop 时，这些增强保持 unknown。

## 验证命令

```text
corepack pnpm --filter @tsunagou/adapter-codex run check
corepack pnpm exec vitest run packages/adapter-codex/tests
python tools/docs/validate_docs.py
```

测试中的 evidence fixture 只能验证 unknown/ready 判定和字段边界；它不能替代安装指定 Codex 版本后的真实 app-server 双会话、恢复、故障和工具调用证据。真实证据写入 `docs/research/evidence/` 时必须去除原始会话 ID、token、transcript 和私有路径。
