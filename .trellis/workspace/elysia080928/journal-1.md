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

## 2026-09-19 - T23 首轮验收续测（当前执行环境）

- 复核 `elysia` @ `402cd6b`，测试前工作区干净；未更改 T23 的 `tyuikl32` 指派。
- 工具环境：Python 3.14.7 超出项目范围；`uv`、OpenCode、`dsh` 未在 PATH；`pnpm` 11.19.0 不符合项目要求，corepack 缓存权限报 `EPERM`。未安装工具或访问包注册表。
- OpenCode/dsh 的 `npx --no-install ... --version` 离线查询均退出 1（`ENOTCACHED`）；未授权联网获取包，故未执行这两个宿主的新探针。
- Codex 一次性无模型探针退出 0，仅验证两个 thread 隔离；空 thread resume/fork 返回 `-32600`，`ready: false`。未把宿主 thread 当作已接入的 Tsunagou Agent。
- `release_check.py` 退出 1，三个首发宿主各缺 10 项共同基线；文档校验退出 0。pytest/Ruff/mypy 在当前 Python 中缺失，完整质量门禁未复跑。
- 没有真实双 Agent bridge/HostSession 协作证据；本轮未修改产品代码或既有 evidence，未提交、推送或发布。
- 接入缺口是跨层问题：CLI 的 enroll 外壳、HTTP 默认未装配的业务 handler、调用方请求头身份与 `AuthorityService` 之间未形成可信真实 bridge；仅凭当前环境不能安全验证或宣布 ready。
- 另记录两项源码/契约待核实风险：inbox ACK 的 fetched/presented 前置条件在模块规范与 adapter 规范之间不一致；BridgeClient 旧 epoch 操作进行中重连的并发情形尚缺回归测试。均未冒称已由真实宿主复现。
- 收尾：`git diff --check`、T23 上下文校验、文档校验均通过；未运行全量 Python/TypeScript 测试。

## 2026-09-19 - T23 首轮真实宿主取证复核

- 审查 cc 的三个临时探针 JSON，并把脱敏 JSON 内容保存为 `docs/research/evidence/*-2026-09-19T*.json`。Codex/OpenCode/DeepSeek 均只有 session isolation supported、其余 10 项 unknown、ready false；没有双 Agent 的 Tsunagou HostSession。
- cc 实测 CLI `ticket_required` 与 HTTP `handler_not_registered`；源码确认 enroll 外壳、默认 dispatcher 未装配 handler。真实认证与票据接入横跨多个模块，未擅自用调用方自报请求头补成假 ready。
- 独立复现 `uv run pytest -q` 的 `tools` 导入失败；在 `pyproject.toml` 配置 pytest 仓库根路径，新增策略回归测试。`uv run --no-sync pytest -q` 与带同盘缓存的文档原命令均退出 0（1 skipped）。backend 质量规范已记录此入口契约。
- T23 仍为 `in_progress`，原负责人不变；正式基线和 release gate 不伪造通过，未 push/发布。
- 提交前复核：Ruff、mypy、协议、TypeScript、Vitest 28/28、文档与 T23 校验通过；`release_check.py` 仍因三个宿主各缺 10 项正式共同基线退出 1，检查逻辑未改。

## 2026-09-19 - Codex 单宿主十项专项试验

- 用户决定先抢跑 Codex 单宿主验证；保留原定三宿主首发门禁，不宣布 Codex-only 正式发布。
- 当前工作区已有尚未提交的 bridge/身份安全改动：旧 epoch 在途请求不得污染新连接缓存，缺十项证据不得 ready/任命 main，票据仅存哈希，HTTP 不再信调用者自报身份；这些是代码层改动，不是 live baseline 证据。
- `codex-cli 0.155.0-alpha.9.2` 隔离无模型探针退出 0；只证实双 thread 原生隔离，空 thread resume/fork 为 `-32600`。保存脱敏 JSON 于 `docs/research/evidence/codex-2026-09-19T170100.json`，仓库副本与探针输出解析内容一致。
- `tsunagou agent enroll --adapter codex --mode attach` 退出 0 但返回 `ticket_required`。没有票据兑换、HostSession 或 Codex main/worker 协作；其余十项均是前置阻断，非实测失败。逐项复测指导见 `docs/acceptance/codex-pilot-2026-09-19.md`。
- Codex adapter + bridge Vitest 17/17、Python 全量 pytest（1 skipped）、Ruff、mypy、协议校验（106/111）、六 workspace TypeScript 检查退出 0。`release_check.py` 仍退出 1，三个首发宿主各缺十项；T18/T23 保持 in_progress，未 commit/push/发布。
