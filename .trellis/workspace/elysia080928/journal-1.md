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

## 2026-09-19 - T23 真实宿主补证与 bridge 修复

- 正式转交核验：T23 `assignee` 仍为 `tyuikl32`，未伪造转交；本轮按 `elysia080928` 的明确授权在 `elysia` 分支执行。
- 真机：OpenCode 1.18.31 与 DeepSeek Harness 0.1.5-rc.2 隔离探针均成功；Codex 0.155.0-alpha.9 探针修复 Windows ACL/编码后成功。三个宿主都仅把真实观察到的 session isolation 标为 supported。
- 产品修复：bridge 增加 canonical command fingerprint、并发去重与冲突拒绝、受控重试、epoch 重连幂等；inbox 分离 claim/fetch/presented/ACK；三 adapter 只接受绑定安装实例与脱敏 conversation digest 的 evidence，并只保留脱敏生命周期观察。
- 质量：全量 Vitest 28/28、6 workspace TypeScript check、完整 pytest（1 skipped）、Ruff、mypy（41 files）、106 policies / 111 schemas 与文档校验通过。
- 发布门禁：`release_check.py` 仍预期退出 1；Codex、OpenCode、DeepSeek 各缺 session isolation 以外的 10 项真实 baseline。未运行 T24，未发布或推送。
