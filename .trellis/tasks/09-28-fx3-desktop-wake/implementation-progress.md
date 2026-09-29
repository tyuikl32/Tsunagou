# FX3 实施进展

2026-09-28；分支 codex/live-test-repair。用户已通过“完成所有任务”授权实施，FX3 保持 in_progress，不宣称最终验收通过。

已实现：Python 本机管道 client/provider；原 thread 固定绑定、连接刷新；宿主接受/开始区分；忙时队列与合并；未知结果先核对；dispatcher 不跨 RPC 持有全局锁；失败落盘、历史重试保留；普通 message.send 与 A2A 共用持久 outbox；服务启动恢复；bridge 私有重连字段、Schema/registry/生成物。

真实证据：research/desktop-send-first.json、desktop-send-observed.json 记录原手动对话收到 FX3_DESKTOP_WAKE_OK。research/desktop-idle-caller.json 记录原调用者于 10:18:42.287Z idle，后台于 10:18:42.557Z 接受自唤醒，10:18:48.658Z 观察到新回合完成及 FX3_IDLE_CALLER_WAKE_OK。未修改 Codex 二进制/锁，没有使用开发对话的应用发送工具代替 Python IPC。

已过：50 项相关 Python 测试（hostwake、原会话 provider、callback fence、真实 SQLite/outbox/reconnect 集成、A2A HTTP、M1 现有流程、audit schema）；17 项 Node credential-handoff 测试；全部 workspace TypeScript check；新文件 mypy；架构和 Schema 检查。一次测试发现 query 生成物 digest 过期，已运行 generate_audit/generate_openapi 修复。

剩余：完整独立安装下的原 Agent inbox 处理、实际 Desktop/bridge 重启后的自动重新登记、真实忙时批量消息和 managed 路径最终回归；最终由 FX4/FX6 串联验证。FX1 为无依赖任务，可以先推进。FX3 尚不关闭；后续依赖的是已实现 provider 接口，最终关闭条件不降低。

实现时发现原代码只有 A2A HTTP 会直接调用 wake，MCP message.send 不会。已在 ServiceStateRuntime.persist 对新建 message 写统一 outbox，通过 HostDeliveryWorker 在事务外调用同一 dispatcher，并有两个传输的集成回归。此修复属于原定 FX3 消息投递范围。

2026-09-28T15:35Z 更新：两名原手动 Desktop Worker 已在独立安装下由 daemon 唤醒、读取完整 inbox、回信并完成实际代码工作；A2 可按这些事实通过。实测另发现忙时已 ACK 的 queued 消息可能触发空回合，已修并通过自动化回归；最后一批修改尚未加载到实际 daemon，同库重启因命令策略拒绝未发生，仍须补现场回归，FX3 不关闭。

2026-09-29T05:10Z 复核：前段落保留为当时记录。当前独立安装 daemon 已于 2026-09-28T18:11:09.514Z 以同库重启（PID 103048，runtime 432243a5-9041-4979-89f9-83c20ddc9cf0），三名原 Agent 的 agent_id 保留。两名原 Desktop Worker 均由 daemon 实际唤醒，在自己的会话读取 inbox、回复和完成工作；原调用者 idle 后触发新回合的独立传输证据在 `research/desktop-idle-caller.json`，完整业务回合在 `research/real-message-loop-20260928.json`。重启后的 owner 恢复与旧 Attempt 拒绝详见 `docs/acceptance/evidence/live-repair-20260928T150917Z/evidence/a4-restart-recovery-20260928T1951Z.json`、`a4-stale-submit-20260929.json`。用户决定答复后的主会话通知已在活跃回合 ACK，后续空通知被记录为 `messages_already_acked`，没有伪称新 turn；相关 Worker 在原会话新回合完成任务，详见同一 evidence 目录下 `a6-decision-resume-20260929.json`。

W1/W2 的原会话、idle 和业务收件箱事实已覆盖；W3 的去重/排队有自动化回归，并有重启后 `messages_already_acked` 现场例子；W4 同库 daemon 重启与原身份恢复已有现场记录；W5/W6 有权限边界和诊断查询的源码测试及现场记录。W7 仍待新版共享投递逻辑下的 disposable managed app-server 真实 `message/send -> inbox -> presentation -> reply/turn completion` 复测。2026-09-23 的 managed 真实闭环是历史基线，不能替代 FX3 修改后的回归。FX3 保持 `in_progress`，不提前关闭。
