# 实施步骤

1. 修改 `packages/bridge-server/src/server.ts`，将静态 ticket/session 检测改为 `attemptSessionRecovery()`。
2. 在 `CallTool` 入口调用 `ensureSession()`，加入 recovery promise 合并和旧 epoch 一次重试。
3. 保持所有凭据只在内存/私有文件中，boot diagnostic 只写 digest 和状态。
4. `pnpm --dir packages/bridge-server build`，再运行既有双 bridge smoke；增加晚到 ticket 的进程级复现时，确认不需要重启 bridge。
