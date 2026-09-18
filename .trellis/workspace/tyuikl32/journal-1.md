# Journal - tyuikl32 (Part 1)

> AI development session journal
> Started: 2026-09-18

---



## Session 1: 规划知识归档、双层文档与Trellis实施任务初始化
<!-- trellis-session: v=2 fp=eaebc042ff0764d1 -->

**Date**: 2026-09-18
**Task**: 规划知识归档、双层文档与Trellis实施任务初始化
**Branch**: `main`

### Summary

保存本轮D161-D181及工程消歧，原样归档48份原稿，完成用户说明和八模块实施规范，初始化Codex/tyuikl32并建立总任务与24实施子任务。

### Main Changes

- 统一术语、状态、命令权限、REST/MCP、事务与失败恢复语义；保留用户确认与main自治边界。
- 每个实施任务具有PRD/design/implement、implement/check JSONL和明确前置依赖；产品任务保持planning。
- 填充10份项目专用Trellis specs，移除7份不适用frontend模板，关闭会话自动提交。

### Git Commits

(No commits - planning session)

### Testing

- [OK] python tools/docs/validate_docs.py通过：48份原稿hash一致，264个本地链接，24项依赖无环，378个context条目；D161-D181齐全。
- [OK] Trellis task.py validate对26个当时活动任务均通过；初始化任务已归档。产品代码/宿主兼容测试尚未运行。

### Status

[OK] **Completed**

### Next Steps

- 先执行T01工具链与T02四宿主可行性探针，按roadmap依赖推进；无需重开已确认产品边界问答。
- Codex hooks文件已生成，自动注入仍取决于宿主开关与UI信任；未修改全局设置。


## Session 2: 细化实施搭建、子Agent接入与CLI/HTTP手册
<!-- trellis-session: v=2 fp=5560e1d76fd426a5 -->

**Date**: 2026-09-18
**Task**: 细化实施搭建、子Agent接入与CLI/HTTP手册
**Branch**: `main`

### Summary

补全可执行搭建顺序、预期目录、官方参考、三Agent协作轨迹、子Agent加入流程及CLI/HTTP契约，并同步24个实施任务上下文。

### Main Changes

- 新增搭建指南、目录方案、协作轨迹、参考资料和入口契约。
- 增强overview中的子Agent角色、加入与运行流程，并提供CLI/HTTP简明手册。
- 将project.completion.confirm映射为U-only project confirm-completion CLI，不新增领域权限。

### Git Commits

(No commits - planning session)

### Testing

- [OK] python tools/docs/validate_docs.py：177份Markdown、434个本地链接、24个实施任务、620条上下文通过。
- [OK] 26个活动Trellis任务context validate全部通过；git diff --check通过。

### Status

[OK] **Completed**

### Next Steps

- 从T01工程骨架与T02宿主探针开始首发实施。


## Session 3: T01-T04 foundation implementation and acceptance
<!-- trellis-session: v=2 fp=af8f3aeef44fd606 -->

**Date**: 2026-09-18
**Task**: T01-T04 foundation implementation and acceptance
**Branch**: `main`

### Summary

完成工程骨架、宿主探针、统一协议生成与SQLite持久运行时基础底座。

### Main Changes

- T01: Python/TS可复现工具链、应用骨架和架构检查。
- T02: 四宿主探针、脱敏证据与Codex真实app-server记录。
- T03: 106条命令策略、111个Schema、Python/TS生成物和确定性bundle digest。
- T04: SQLite事务、OS lock、WAL/FULL/FK、幂等、event/outbox、Job lease、重试/unknown与epoch fence。

### Git Commits

(No commits - planning session)

### Testing

- [OK] uv run pytest（18 passed）
- [OK] uv run ruff check src tools tests；uv run mypy src
- [OK] uv run python tools/dev/check_architecture.py；uv run python tools/codegen/validate_protocol.py
- [OK] corepack pnpm -r run check；python tools/docs/validate_docs.py

### Status

[OK] **Completed**

### Next Steps

- 继续 T05 及后续模块专项实现；跨进程 crash 注入、迁移备份和双 writer 压测按台账作为专项验收。


## Session 4: T05-T12 domain modules and acceptance
<!-- trellis-session: v=2 fp=fabc7119243d9e8e -->

**Date**: 2026-09-18
**Task**: T05-T12 domain modules and acceptance
**Branch**: `main`

### Summary

完成项目、身份、消息、任务、资源、认知、工作空间和附件八个领域任务，并通过统一质量门槛。

### Main Changes

- 新增八个 Python 领域模块及 8 组单元验收。
- 补充 T05-T12 PRD/implement/task 状态、上下文和验收台账。
- 补充 connection nonce/epoch fencing、资源等待 aging 与主 Agent Git 请求边界。

### Git Commits

(No commits - planning session)

### Testing

- [OK] uv run pytest（44 passed）
- [OK] uv run ruff check src tools tests；uv run mypy src
- [OK] uv run python tools/dev/check_architecture.py；uv run python tools/codegen/validate_protocol.py
- [OK] corepack pnpm -r run check；python tools/docs/validate_docs.py

### Status

[OK] **Completed**

### Next Steps

- 继续 T13-T24：任务编排、checkpoint/lifecycle、HTTP/MCP/CLI、bridge/adapters、observability 与集成发布门槛。


## Session 5: T05-T12 audit closure
<!-- trellis-session: v=2 fp=0253bdd0a627086e -->

**Date**: 2026-09-18
**Task**: T05-T12 audit closure
**Branch**: `main`

### Summary

补齐接入 nonce/epoch fencing、资源等待 aging 与全部实现检查项，重新完成文档校验。

### Main Changes

- Authority rebind 使用 reconnect nonce，authorize 校验 runtime/authority/execution epoch。
- ResourceService 提供 deterministic waiting aging；T05-T12 implement checks 全部勾选。

### Git Commits

(No commits - planning session)

### Testing

- [OK] python tools/docs/validate_docs.py（181 Markdown / 655 contexts）

### Status

[OK] **Completed**

### Next Steps

- 按依赖继续 T13-T24。


## Session 6: T17 bridge SDK implementation
<!-- trellis-session: v=2 fp=0a944ca4c46f5cc8 -->

**Date**: 2026-09-18
**Task**: T17 bridge SDK implementation
**Branch**: `main`

### Summary

Completed the host-neutral bridge SDK and conformance harness.

### Main Changes

- Added session-scoped credentials, command retry/deduplication, epoch recovery, inbox ACK, Lease renewal, context rendering, MCP/stdio forwarding, and ticket boundary types.

### Git Commits

(No commits - planning session)

### Testing

- [OK] corepack pnpm --filter @tsunagou/bridge-sdk run check
- [OK] corepack pnpm --filter @tsunagou/bridge-sdk test

### Status

[OK] **Completed**

### Next Steps

- Start T18 Codex adapter with real-host evidence gating.


## Session 7: T18-T24 implementation and live gates
<!-- trellis-session: v=2 fp=dc4b9a90773bc1c4 -->

**Date**: 2026-09-18
**Task**: T18-T24 implementation and live gates
**Branch**: `main`

### Summary

Implemented adapter boundaries, evaluation, integration gates, and demo/experiment artifacts; live host and research gates remain explicit blockers.

### Main Changes

- Added four host-neutral adapter implementations and diagnostics with shared baseline conformance and secret-free installation plans.
- Added evaluation ledger, release gate tooling, integration recovery tests, experiment plan generator, demo runbook and release checklist.

### Git Commits

(No commits - planning session)

### Testing

- [OK] corepack pnpm -r run check
- [OK] corepack pnpm exec vitest run packages/adapter-codex/tests packages/adapter-opencode/tests packages/adapter-zcode/tests packages/adapter-deepseek/tests
- [OK] uv run pytest tests/unit/test_evaluation.py tests/integration -q
- [OK] python tools/docs/validate_docs.py
- [OK] uv run python tools/dev/release_check.py (expected nonzero: four live_baseline_missing)

### Status

[OK] **Completed**

### Next Steps

- Obtain and run real host probes for OpenCode, ZCode, DeepSeek Harness and complete Codex 11-item evidence; then rerun T23/T24 gates.


## Session 8: CLI contract alignment and final regression
<!-- trellis-session: v=2 fp=29f025a3b8aa479f -->

**Date**: 2026-09-18
**Task**: CLI contract alignment and final regression
**Branch**: `main`

### Summary

Aligned CLI examples with implemented flags and reran the full local quality suite.

### Main Changes

- project init now uses --coordination-root; decision resolve accepts choice, expected revision, digest and reason.

### Git Commits

(No commits - planning session)

### Testing

- [OK] uv run tsunagou --json doctor
- [OK] uv run tsunagou agent enroll --adapter codex --mode attach
- [OK] uv run tsunagou decision resolve decision-1 --choice approve --expected-revision 3 --digest sha256:test --reason ok
- [OK] 59 pytest, 19 Vitest, Ruff, mypy src, architecture, protocol and docs validation passed

### Status

[OK] **Completed**

### Next Steps

- Install/activate target hosts and collect real baseline evidence before closing T18-T21 and T23-T24.


## Session 9: OpenCode 与 DeepSeek 真宿主探针及证据脱敏
<!-- trellis-session: v=2 fp=deepseek-opencode-live-20260918 -->

**Date**: 2026-09-18
**Task**: T19/T21 live probe progress
**Branch**: `main`

### Summary

完成 OpenCode 1.18.31 与官方 DeepSeek Harness 0.1.5-rc.2 的无模型真实探针补充。DeepSeek 探针强制只接受外部服务 URL 与 token，证据使用 keyed identity digest；临时 `DSH_HOME`/`DSH_AGENTS_HOME` 已清理，不触碰用户持久会话。

### Main Changes

- `tools/conformance/probes/opencode/probe.py` 与 `docs/research/evidence/opencode-2026-09-18.json` 保留 session/fork/history 的部分证据。
- `tools/conformance/probes/deepseek/probe.py` 与 `docs/research/evidence/deepseek-2026-09-18.json` 记录官方 Web token-cookie、session/create 和 session/list 的部分证据。
- `tools/conformance/probes/zcode/probe.py` 与 `docs/research/evidence/zcode-2026-09-18.json` 显式记录官方宿主不可用时的 11 项 unknown；没有用非官方 npm 客户端替代。
- T19/T21 文档明确真实版本、认证边界和剩余 unknown；四宿主 release gate 仍不会误报 ready。
- T21 DeepSeek 文档补充了临时 `DSH_HOME`/`DSH_AGENTS_HOME` 的可复现步骤和清理要求，避免后续探针误触用户持久会话。
- 收尾审计发现早期手工试验曾在用户 `.dsh` 创建临时 web profile 与两个空 session；已按创建时间和精确路径清理，其他已有 profile、凭据和会话未改动。
- T23 发布检查增加 `missing_capabilities` 诊断，逐宿主列出具体缺失 baseline；严格四宿主 gate 和退出码保持不变。

### Testing

- [OK] OpenCode 1.18.31 disposable headless probe
- [OK] DeepSeek Harness 0.1.5-rc.2 temporary-home probe
- [OK] DeepSeek/OpenCode probe unit tests

### Status

[OK] **Partial evidence recorded; full 11-item baseline remains open**

### Next Steps

- Rerun full pytest, pnpm, Ruff, mypy, architecture, protocol, docs and task validation; keep T18-T21/T23-T24 in progress until all real gates are satisfied.
