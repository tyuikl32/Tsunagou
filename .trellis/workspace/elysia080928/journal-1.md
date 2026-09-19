# Journal - elysia080928 (Part 1)

> AI development session journal
> Started: 2026-09-18

---

## 2026-09-19 - T23 首次真实验收

- 身份/分支：`elysia080928`，`elysia`（base `main`）；T23 保持 `in_progress`。
- 修复：`pnpm-workspace.yaml` 只批准 esbuild 构建脚本；根 Node check 改为遍历全部 workspace；移除无根 project references 的共享 `composite`；新增工具链策略回归测试。
- 通过：pytest 66 passed / 1 skipped、Ruff、mypy、106 command policies / 111 schemas、pnpm frozen install、6 workspace TypeScript checks、Vitest 19/19、文档校验、T23 context 校验、生成物零差异。
- 入口：CLI 0.1.0、doctor、三个 `ticket_required` enroll 外壳、临时 Git 协调项目初始化、loopback HTTP health 均通过。
- 真机证据：Codex CLI 0.155.0-alpha.9 可初始化且同目录双 thread 隔离；空 thread resume/fork 为 JSON-RPC -32600，完整 baseline 仍 unknown。OpenCode npm 获取/启动超时，未写支持结论。
- 阻断：`release_check.py` 预期退出 1；Codex 缺 11 项、OpenCode/DeepSeek 各缺 10 项真实 baseline。未运行 T24、未发布、未提交或推送。

