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

## Session 10: 独立运行审计与最小成品实施方案

**Date**: 2026-09-20
**Source**: main@f9ea7b4，初始工作区干净。

用户要求依据可运行代码评估八模块，立即落盘实现与详细调试方案，不以宿主能力证据代替交付。新增docs/standalone，记录完整缺口、M1范围、R1–R6实现包、真实调试命令及成品完成标准；D183记录本轮优先级。现状入口与T23说明同步纠正，原任务状态作为历史保留。

新增tools/dev/audit_standalone.py：临时Git项目、真实uvicorn/HTTP、进程重启、CLI独立进程，结果16项中2通过14未满足。复现worker block/resume接管主任务、重复创建、失败start后running、任务/契约重启丢失和CLI票据不同步等。wheel构建成功但安装到临时site离开源码后因protocol registry缺失启动失败。

本轮Python测试102通过、TS测试29通过；审计脚本Ruff与mypy通过。未改产品运行逻辑，M1修复尚未开始，不声明独立成品完成；后续从R1协议/打包与R2统一runtime/SQLite开始。

## Session 11: 旧任务关闭归档与 M1 实施任务重建

**Date**: 2026-09-20
**Request**: 将独立成品实施包整理为 Trellis 任务，此前任务全部视为完成或放弃。

本次归档旧活动目录中的 25 项：T01-T17/T22 共 18 项保留 completed 与原完成时间；T18-T21/T23-T24 及 V1 总任务共 7 项标记 cancelled，meta.closure.disposition=abandoned。此前已归档的两个完成任务保持不变。归档不删除原代码、设计与测试记录，不声称未通过的验收已经完成。

新建 09-20-tsunagou-m1 总任务及 R1-R6 六个子任务，均为 planning，负责人 tyuikl32。每项包含 PRD/design/implement、明确验收和双 JSONL 上下文，依赖为 R1 → R2 → R3 → R4 → R5 → R6。使用 --no-start 创建，当前没有实施中任务。docs/implementation/task-plan.json 与 roadmap.md 切换到新计划，旧机器计划/路线图保留 legacy 文件，逐项迁移见 docs/standalone/trellis-transition-2026-09-20.json。

同步 AGENTS、文档导航、旧验收模板、搭建指南和归档相对链接；文档校验从机器计划读取 parent_task，不再固定旧 V1 目录。

验证：7 个新任务 context validate 全通过；docs 校验通过（48 份历史源未变、693 本地链接、6 实施任务、881 上下文条目、依赖无环）；闭档状态与原日期核对通过；校验脚本 Ruff 与 git diff --check 通过。未改产品逻辑，未执行新任务验收，未提交或发布。下一步从 R1 开始。

## Session 12: M1 首轮公开入口、双 bridge 与任务收口

**Date**: 2026-09-21
**Request**: 在旧任务已归档、新 M1/R1-R6 任务已建立的基础上推进可独立运行成品，并持续保存证据。

完成的产品与文档工作：

- bridge-server 构建时复制 protocol registry，运行时优先读取自身包内资源；npm pack 解包、安装 production 依赖后可从源码树外启动。
- CLI `project complete` 用户入口、bridge daemon state endpoint 发现和持久 `ProjectDatabase.runtime_epoch` 查询已接通，daemon 随机端口重启后 bridge 不再固化旧 URL。
- 双 bridge MCP smoke 覆盖独立票据、main/worker、任务发布/领取、foreign submit 拒绝、资源 lease、workspace、认知分歧、契约、消息回应义务、真实 Node 测试、用户文件 baseline conflict、review 和 takeover 拒绝。
- `tools/dev/smoke_standalone.py` 从临时 Git 项目执行 CLI/HTTP/MCP 全流程，包含旧 execution grant 重启后拒绝、用户决定、项目完成、checkpoint、HTTP task query 与 recovery。
- checkpoint 物化失败保留 completed 用户结论并创建可查询 failed Operation/error_code；新增公开命令级集成测试。
- 文档证据新增 `docs/standalone/bridge-two-session-smoke-2026-09-21.json`、`m1-public-smoke-2026-09-21.json`、`package-smoke-2026-09-21.json` 与 `checkpoint-failure-2026-09-21.json`；R1-R6 implement 记录同步更新。

验证：104 pytest、29 Vitest、全 workspace TypeScript check、Ruff、docs validator、16/16 standalone backend audit、Python wheel 源码树外安装和完整 `tools/dev/smoke_standalone.py` 均通过。当前 107 个声明命令中 40 个已装配；commit/物化窗口故障注入、后台 lease expiry/job、完整八模块查询矩阵和真实宿主接入仍未关闭。七个新 Trellis 任务继续保持 planning，未提交或发布。

## Session 13: 多根项目边界入口补齐

**Date**: 2026-09-21
**Request**: 在任务重整后继续推进 M1，补齐项目多文件夹/多仓库的公开边界入口。

为主 Agent 的 `main_authority` Grant 增加 `root.manage`，接入 `root.register`、`root.bind`、`repository.register` handler；root bind 要求显式 `root_id` 并校验 `expected_physical_identity`。HTTP 增加脱敏的 `/api/v1/projects/{id}/roots` 与 `/repositories` 查询，协议目录、生成 Schema/TypeScript、wheel 内资源和 bridge registry 已同步。新增多根登记、仓库登记、查询集成测试。

验证：104 pytest、29 Vitest、workspace TypeScript check、Ruff、协议校验、文档校验、16/16 standalone audit、`uv run --extra dev python tools/dev/smoke_standalone.py` 全部通过。命令装配从 40/107 提升为 43/107；UserCeiling、scope 统一授权、完整 project 生命周期、其余 64 个命令和故障注入仍未关闭。未提交或发布。

## Session 14: 任务恢复动作与认知协商入口补齐

**Date**: 2026-09-21
**Request**: 继续推进当前 M1，减少公开协议已声明但运行时没有 handler 的缺口，并及时落盘证据。

接入任务公开动作：`task.update_plan`、`task.edge.add/remove`、`task.cancel_request/ack`、`task.fail`、`task.recover`、`task.scope.request/resolve`、`task.self_accept`。scope 请求现在校验 task/scope revision；recover 会释放旧 attempt Lease 并撤销旧执行 Grant。新增公开集成测试覆盖计划、依赖、scope 拒绝、blocked reopen 和取消确认。

接入认知与契约动作：`discrepancy.create/advance/resolve`、`contract.accept_proxy/reject/withdraw`。worker 只有 `cognition.discuss`，主 Agent通过 `cognition.resolve` 解决分歧；契约拒绝必须匹配参与者和 digest，撤回必须是提出者。bridge MCP 工具目录、运行时字段和主 Agent Grant 已同步；证据写入 `docs/standalone/cognition-contract-actions-2026-09-21.json`。

验证：105 pytest、29 Vitest、workspace TypeScript check、Ruff、协议校验、文档校验、16/16 独立审计、`uv run --extra dev python tools/dev/smoke_standalone.py` 和 bridge-server 构建全部通过；运行装配从 43/107 提升为 60/107，剩余 47 个声明动作主要是完整 project lifecycle、risk、workspace integration 和 host recovery。checkpoint 失败已有 `durability.reconcile` 主 Agent入口和 `checkpoint retry` 用户CLI入口。未提交或发布。

## Session 15: R3 执行编排、Lease 维护与提交窗口验收

**Date**: 2026-09-21
**Request**: 在 M1 任务树下继续补齐真实执行边界和可恢复运行证据。

`TaskExecutionWorkflow` 已接入 dispatcher handler，统一 preflight/start 的 owner、attempt、Lease、workspace、契约和输入 digest 检查；持久 `tasks.PreflightResult` 保存各 revision、evidence 和 blockers。新增陈旧契约 start 的公开拒绝测试；`Task.block` 记录 `SuspensionSnapshot` 并随 SQLite 快照恢复。新增 `RuntimeMaintenance`，随 FastAPI daemon 生命周期后台处理 Lease 到期、Attempt/Task orphan、执行 Grant 撤销和 SQLite 事件。

`ProjectDatabase` 增加一次性测试故障注入点，覆盖提交完成但响应丢失时的同 command_id 重放；新增 `docs/standalone/commit-window-2026-09-21.json` 和 `lease-maintenance-2026-09-21.json`。同步更新 R3/R4/R6 implement、M1 status/gaps、README、roadmap 和机器计划；R3 记录为当前 in_progress，R1/R2/R4/R5/R6 仍按剩余门禁保留规划状态。

验证：109 pytest、29 Vitest、workspace TypeScript check、Ruff、协议校验、文档校验、16/16 standalone audit、wheel 构建、bridge 构建和 `tools/dev/smoke_standalone.py` 全部通过。仍未宣称 M1 完成：真实 OS kill 矩阵、完整审查/恢复矩阵、scope/physical alias、完整协议覆盖和真实宿主验收仍由 R3-R6 追踪。未提交或发布。

## Session 16: M1 重启事实查询与审查回退撤权

**Date**: 2026-09-21
**Request**: 继续推进可独立运行成品，确保公开 smoke 在重启后验证完整事实，并修复审查退回后的旧执行权。

`tools/dev/smoke_standalone.py` 现在在 daemon 重启后通过公开 HTTP 查询并断言 tasks、agents、cognition/contracts、messages、workspaces、decisions 和脱敏 audit 均保留了本轮事实；结果仍只来自 CLI/HTTP/MCP，不实例化领域 Service。证据文件 `docs/standalone/m1-public-smoke-2026-09-21.json` 已同步这些查询项。

修复 `task.review.request_changes`：旧 Attempt 进入 `orphaned` 且 Task 清除 current attempt 时，关联 Lease 一并释放、旧 execution Grant 一并撤销，下一轮必须重新 claim/preflight/start。新增 `test_review_changes_requested_closes_execution_lease_and_grant`。

新增 `tools/dev/commit_window_process_smoke.py`，通过真实 daemon 子进程分别覆盖 commit 前退出和 commit 后响应丢失；两种场景都在重启后用同一 `command_id` 重放成功，证据见 `docs/standalone/commit-window-process-2026-09-21.json`。默认运行不设置测试退出开关。

为 M1 的 scope 标准补上最小结构约束：`task.create.execution_scope` 可声明带 digest 的 path/named 资源；resource intent 只能使用同 mode 的允许 path 前缀或精确 named 资源，越界返回 `task_scope_denied`。scope 批准会增加 `scope_revision` 并撤销旧 execution Grant；双 bridge smoke 现在实际携带 project root scope。

验证：110 pytest、29 Vitest、workspace TypeScript check、Ruff、协议校验、文档校验、16/16 standalone audit、双 bridge smoke 和真实 daemon 提交窗口 smoke 全部通过。M1 仍保持未关闭，Job/物化中断、scope/physical alias、完整审查/恢复矩阵、协议覆盖和真实宿主接入继续由 R3-R6 追踪。未提交或发布。
### Session 17 — 2026-09-21

- 按用户要求维持 Trellis 重组：旧 T01–T17/T22 与文档任务归档 completed，T18–T21/T23–T24/旧 V1 归档 cancelled；当前任务树为 M1 与 R1–R6。
- 为独立运行 M1 补充常驻维护的过期 Job lease recovery、`GET /api/v1/projects/{project_id}/jobs` 公共查询、单元回归及 standalone smoke 的重启查询断言。
- 修正一次真实 smoke 暴露的 jobs 查询列名错误；完整 Python/TS/协议/文档检查、双 bridge standalone smoke、真实 daemon commit-window smoke 和 16/16 audit 均通过。
- 将 checkpoint 失败/HTTP 查询/CLI retry 纳入真实 daemon smoke；新增 `tools/dev/package_smoke.ps1`，本次在源码树外临时 venv 与 npm 解包目录均启动成功。
- M1 十二条最小产品标准已通过并写入 `docs/standalone/m1-acceptance-2026-09-21.json`；主动 Job runner/物化中断扩展、完整 workflow/风险与断线矩阵、真实宿主基线和完整公共协议仍作为 R1-R6 follow-on。
