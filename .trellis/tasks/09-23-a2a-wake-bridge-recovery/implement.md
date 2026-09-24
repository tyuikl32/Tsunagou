# 实施计划

1. 更新 bridge server 的 session recovery closure，确保启动、首次 tool call、旧 epoch 三个入口共享 ticket/session 读取和一次性恢复锁。
2. 为 A2A gateway 增加标准 push config 解析、短超时 HTTP notifier、失败降级和脱敏响应 metadata。
3. 扩展 A2A message/send schema 与 unit fixtures，加入成功 callback、失败保留 pull delivery、secret 不落盘的回归测试。
4. 同步 `a2a-boundary.md`、standalone gaps、实现任务计划和本任务上下文，明确 host wake 证据边界。
5. 执行 Python A2A/消息/协议测试、bridge `pnpm build`、文档校验；记录命令和实际结果。
