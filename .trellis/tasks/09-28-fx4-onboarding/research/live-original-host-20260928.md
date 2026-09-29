# 原 Desktop 接入与恢复实测

本节记录截至 2026-09-28T13:17:06.000Z 的观测；后续结果追加，不能用恢复成功覆盖首次失败。

- 安装目录 D:\Tsunagou，业务协调目录 D:\Tsunagou-fx-live-20260928。安装重用源码，业务目录未复制源码。实际安装起止 12:57:52.468Z–12:57:57.275Z，4.807 秒；这是安装流程经过时间。
- 三个原会话分别产生 main `1a20b513-3efd-48c6-81c9-479335f7572a`、worker `cb2f1ff6-87de-4625-9afe-00b44ef5c182`、worker `e5a866e0-3c1c-4ab5-8d11-5becd613cc48`，项目 `450286e4-8d1b-4220-840c-e540fe696913`。用户没有填写身份 ID。用于测试的原会话映射保存在私有接入材料中，不在共享报告展开。
- Worker e5a 的原 MCP 工具调用 `exec-a7fcb339-88df-418a-a71e-52092496a34b`：server=tsunagou、tool=context__project_read、completed、43ms；随后原会话报告 ready_worker。应用 read_thread 返回工具执行标记而不包含工具结果正文，因此证据强度是实际调用完成 + 会话报告；后续收件箱回执仍须验证。
- Worker cb2f 当时的已加载会话看不到新服务；main 也暂不可见。首次 setup 提示由开发会话应用工具发送，明确属于 developer_followup，不能算 daemon 自动唤醒。
- 后续 main 新工具已可见，但首次 context 返回 bridge_request_failed。13:10:49Z 检查 daemon status=stopped，原 PID93468 已不存在，日志末尾13:01:57Z，未记录退出原因。不能据此断言谁关闭了进程。13:12:43.740Z 恢复同库，PID103604；main 原 MCP 随后返回原 agent_id、main、ready、epoch1 和原绑定。身份没有新增。
- 用户报告设置里能看到 tsunagou，但没有刷新按钮。不能继续要求用户点不存在的按钮；官方其他界面的 Restart 文案不证明当前 Desktop 版本有该按钮。
- 第一次真实 daemon 消息：command_id `46cc85d8-4fa1-40a8-a09b-138d3c2fcc21`，message_id `b69f6a30-01be-40b9-b55a-382bb3a935d1`，目标 worker e5a。13:14:10.238Z wake_requested，13:14:10.251Z desktop_connection_lost，原会话仍未加载；消息未丢弃。此场景判失败，不能用手工跟进改写。
- 13:17:06Z 比对：当前实际宿主管道与三份 enrollment 请求中原管道均不同。配置缺少 `env_vars = ["CODEX_APP_TOOLS_PIPE_PATH"]`；因此重载的 bridge 使用私有 route 中旧 endpoint。正在修配置生成和恢复；原会话完整唤醒尚未验收。

## 其他实测偏差

- 旧私有文件锁把路径压缩到 TCP 端口，与 MSI.TerminalServer 26822 撞端口。Windows 改完整哈希命名管道，Linux 改 abstract socket；两者由内核在退出时释放。macOS 仍保留 fail-busy TCP，不宣称已验证。Windows Python/Node 双向争用、强制终止释放与旧端口占用回归见 lock-installer-validation.md。
- 第一次实装 uv sync 移除了额外开发依赖，同时进行中的 pytest 在插件退出时失败。已恢复 dev 环境；安装器改 --inexact 和后续 --no-sync。该次失败不能记作通过。后续独立 Python 接入/多项目/锁/CLI/安装器15项通过；新的互斥/安装器测试另见研究记录。依赖同步与测试以后串行。

## 来源

- [官方 MCP 环境变量转发](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)：env_vars 允许转发动态本地环境变量。
- [官方 App Server](https://learn.chatgpt.com/docs/app-server)：有 config/mcpServer/reload；当前应用工具没有暴露访问原 Desktop 该方法的入口，不能启动第二个 app-server 冒充刷新原宿主。
- 本机 codex-app-tools 0.1.5 的 `.mcp.json` 同样以 env_vars 转发管道，未改动该插件。
- [Node IPC](https://nodejs.org/api/net.html)、[Windows CreateNamedPipe](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-createnamedpipea)：互斥实现依据。

## 恢复及完整消息复测 — 2026-09-28T13:47:40.000Z

共享 bridge 转发动态宿主管道，启动和成功调用后恢复已 enrollment 的同身份绑定；该服务恢复不调用 Worker 的 inbox/task，不冒充 LLM 已工作。恢复后两个旧原会话都由 daemon 唤醒，并调用自己的 MCP 完成 present/ACK。

首次 ACK 后未回信，进一步定位 handlers._message_view 在 inbox.fetch 中也只返回 summary，漏掉完整 payload。已改为 claim 摘要、fetch 完整内容及回复关联；只有原收件人能 fetch，其他身份被拒绝。该遗漏确实影响本次回执指令，不能归咎于模型。

13:41:07.822Z 显式 stop/start 同库、使用新 daemon 启动实现，PID96116；三名 Agent 身份保留。13:41:33Z 同时向两原 Worker 发新的完整回执请求，daemon 唤醒，Worker 分别读取完整 payload 并发送指定回复。main 已实际 fetch/present/ACK 两条回信，未通过应用工具向 Worker 补发跟进。

- worker e5a：请求 5a848966-47cf-4bb0-af30-d77bb91599ef，回复 44095079-cd01-4578-b470-fd4841ac9371；原回合 118806ms。
- worker cb2f：请求 f62c5f86-2e42-498b-9953-58b7562c12ba，回复 1b407829-5c28-48c7-989c-10fe5b09747e；原回合 127702ms。
- 这些是协调回合经过时间，不是业务编码时间；代码任务尚未运行。结构化原 MCP 调用证据在 ../../09-28-fx3-desktop-wake/research/real-message-loop-20260928.json。

仍有一项被实测暴露：provider 只认 userMessage，而真实 Desktop 使用特定 functionCallOutput 注入通知，导致宿主已结束、持久化仍 starting。正在修 poll 的精确来源解析；不能用 LLM 回答里包含 marker 判成功。FX3/FX4 整体保持未完成。

## 用户迟到回复后的复核 — 2026-09-28T16:31:12.000Z 留档

用户再次确认设置可见 tsunagou、没有刷新按钮。当前主会话实际调用共享 MCP `context__project_read` 成功，仍为原 main Agent，session ready、epoch 2、host binding ready。早期刷新请求对本主会话已经过时；无需重新 enrollment 或退出 Codex。该结论只由当前主会话实际工具结果支撑，不将主会话成功外推为任意旧会话成功，也不当作 daemon 重启证明。脱敏事实见 [main-mcp-ready.json](../../../../docs/acceptance/evidence/live-repair-20260928T150917Z/evidence/main-mcp-ready.json)。
