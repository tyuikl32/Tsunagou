# DeepSeek Harness 适配性验收

以 [共同基线](../../../docs/implementation/adapters.md#正式共同基线) 的 11 项要求核查真实宿主证据，不修改标准以使测试通过。

当前结论与逐项证据只维护在 [验收报告](../../../docs/acceptance/deepseek-harness-11-baseline-2026-10-01.md)。

2026-10-02 用户明确批准在此任务内实施 **DSH Desktop 原聊天接入修复**，覆盖此前仅验收、不自动修复的范围限制。在 `elysia` 工作，不 commit/push；保留已有改动。

目标：正常打开 Desktop，在项目原聊天中发起接入，由 Agent 完成安装/登记并在原聊天读回自己的项目、Agent 与 ready 状态；最多一次完整重启，不要求用户执行外部终端命令。

变更边界：现有 DeepSeek provider/注册、CLI 接入、会话私有路由及对应回归。仅必要的共享 bridge 路由适配；Codex 默认行为及 Codex/OpenCode 配置保持不变，协议不变。不新增服务、平行测试框架或验收文档。

先行门槛：真实 Desktop 插件上下文用 daemon 相同 Windows flags 启动立即退出子进程。失败保留具体错误并停止该方案，不去掉 flags、关闭 sandbox 或另建服务。确认必要的运行文件权限问题可在备份后局部修复，不扩大到仓库。

通过门槛后：实际 Desktop profile 加载已有 provider；增加固定用途的宿主本地 `tsunagou_connect`，身份/目录来自当前执行上下文；复用 CLI 和私有逐会话路由。已有身份/角色保持，新登记默认 worker，main 仍须用户明确指定。helper enrolled 不等于原聊天 ready。

验收：原聊天真实接入、重复接入同 Agent、新聊天/fork 隔离、压缩及重启恢复、最短消息和任务闭环、受影响 Python/bridge/Codex/OpenCode 回归与文档校验。复用共同 11 项骨架；不能以历史或 headless 结果替代本轮 Desktop 入口。

状态：2026-10-02 Desktop 接入修复与现场验收已完成，未提交改动保留待审阅；证据、回归环境限制与当前结论继续只维护在上述验收报告，不扩大为发布结论。
