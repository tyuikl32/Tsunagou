# FX3 实施和调试顺序

1. 阅读研究记录及本机插件 server.mjs 的实际调用 metadata 处理；记录当次应用、CLI、插件版本。不要把旧源码行号当版本无关协议。
2. 首先编写最小传输/client 测试和一次明确标识的接入实验：原会话接入、结束回合、由普通后台进程发送拉取提示。确认宿主权限流程、caller 生命周期及原 thread 的新回合。需要手动新建测试对话时，由 FX6 操作步骤指导用户；不使用开发对话的 send_message 工具冒充产品发送。
3. 实现 codex_desktop.py 和 provider registry，使用 PrivateBindingStore，接入 existing enrollment 的绑定意图；先只处理本地 Codex。
4. 修改 dispatcher：投递后触发、按 recipient 合并、忙时排队、失败/unknown 结果、重启先查询。一次 provider 调用不得长期持有整个 dispatcher 全局锁阻塞其他 Agent。
5. 在现有 bridge 启动/恢复入口实现 session.reconnect 的私有绑定刷新，实测 host_generation；同步该字段的 Schema/私有存储与生成物。FX4 复用此路径而不成为 FX3 前置。权限不足直接给实际原因，不自动关闭宿主校验。
6. 同步 docs/implementation/adapter-codex.md、a2a-boundary.md、command-catalog 中有关 host 接口和用户说明；删除独立 listener=Desktop 接管成功的结论，保留其原始实验为历史。

拟新增 tests/unit/test_codex_desktop.py、tests/integration/test_desktop_wake.py。单元覆盖 framing/断线/错配/合并/不改目标；集成覆盖 outbox、未知结果、重启、失败留痕；不能仅 mock 为 W1/W2 打勾。

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_codex_desktop.py tests/unit/test_hostwake.py tests/unit/test_wake_callback_fence.py tests/integration/test_desktop_wake.py -q
.\.venv\Scripts\python.exe -m ruff check src/tsunagou/hostwake tests/unit/test_codex_desktop.py
.\.venv\Scripts\python.exe tools/docs/validate_docs.py
~~~

真实验收保存 UTC 请求/宿主接受/开始/处理时间、Agent 与原 thread 的脱敏对应、message/wake/turn 关联及触发来源。必须由 product daemon 发起，明确结束开发者协助后仍能工作。测试失败不删除原消息或失败记录；FX3 未完成则总任务未完成。
