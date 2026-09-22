# 项目本地 Agent 约束与快速初始化实施计划

## 前置与依赖

1. 先完成 `project-local-contract`，冻结生成文件、受管标记、字段和兼容策略。
2. 再完成 `project-bootstrap-command`，落地 CLI/生成器和 init/onboarding 联动。
3. 随后完成 `host-onboarding-materialization`，按真实宿主能力补入口；未知能力只能生成 generic/manual 路径。
4. 最后完成 `project-bootstrap-acceptance`，在临时多项目 daemon 上执行完整验收。

## 实施步骤

### A. 契约和模板

- 增加项目集成 manifest 的 schema、canonical serializer、版本和 digest 规则。
- 增加 `AGENTS.md` 受管区块、`.tsunagou/agent-context.md`、`.agents/skills/tsunagou-project/SKILL.md` 模板；模板引用 `docs/overview/agent-quick-start.md`、`docs/overview/subagent-guide.md` 和安装 checkout 的规范根。
- 明确共享文件与 `.tsunagou/local` 私有文件的 gitignore 规则及冲突错误码。
- 增加正反 fixture：首次生成、重复生成、用户编辑受管块、缺标记、来源路径移动、缺 source root。

### B. CLI/安装联动

- 在 `src/tsunagou/cli/app.py` 增加 `project bootstrap`（必要时提供 `project init --bootstrap` 兼容快捷方式），复用现有 daemon/project 发现和控制凭据读取，不新增业务权限。
- 将文件写入放入独立的 project integration service；不得在 CLI 中直接 new 领域 Task/Agent service 或绕过 UoW。
- 更新 `tools/install/install.py` 和两个 Tsunagou skills：安装 checkout 后只报告 source root；用户选定业务项目后由 onboarding 调用 bootstrap。
- 输出结构化结果和下一步：文件状态、project_id、source reference、daemon 未启动/已启动，不显示任何秘密。

### C. 宿主入口

- 验证 Codex 对项目 `AGENTS.md`/`.agents/skills` 的发现路径；生成不依赖全局安装路径的项目入口。
- 对 OpenCode、DeepSeek Harness 等只生成已证实的 project context 或手动加载说明；没有证据时返回 `unknown`，不创建虚假 hook。
- 将主/worker/user、Full Access、claim/start、Git 归属、消息 ACK 和恢复规则写入入口，并要求 Agent 首次工作先读取 context/inbox。

### D. 验收和文档

- 新建真实 CLI 集成测试：临时 Git 项目、两个项目共用一个 daemon、两个 daemon/project 入口互不串读。
- 测试已有 `AGENTS.md`/`.gitignore`、并发 bootstrap、重复刷新、源码 checkout 移动和无源码安装包场景。
- 更新 `docs/overview/agent-quick-start.md`、`docs/overview/cli-http-manual.md`、`docs/overview/product.md`、`docs/implementation/cli-contract.md` 和 `docs/standalone/debugging-runbook.md`。
- 运行 Python/TypeScript/Schema 回归、文档校验、diff 检查和源码树外 smoke；保存非秘密证据 JSON。

## 关键文件候选

- `src/tsunagou/cli/app.py`：用户命令和输出。
- `src/tsunagou/modules/projects.py` 与 `src/tsunagou/application/project_integration.py`：项目事实读取与项目入口生成器；后者不是新的业务模块。
- `src/tsunagou/protocol_data/schemas/commands/project/`、registry/fixtures：公开命令契约。
- `tools/install/install.py`、`.agents/skills/tsunagou-install/SKILL.md`、`.agents/skills/tsunagou-agent-onboarding/SKILL.md`：发行安装与向导联动。
- `tests/unit/`、`tests/integration/`、`tools/dev/`：正反例和真实进程验证。
- `docs/overview/`、`docs/implementation/`、`docs/standalone/`：用户和实施文档。

## 验证门禁

```powershell
uv run pytest -q
corepack pnpm --dir packages/bridge-server run check
corepack pnpm --dir packages/bridge-server run build
python tools/docs/validate_docs.py
git diff --check
```

额外必须执行：

```powershell
# 在源码树外的临时 Git 项目运行 project bootstrap，并检查生成文件
# 用同一 daemon 初始化两个项目，分别读取各自 project-integration.json
# 将 Tsunagou checkout 移动后执行 --refresh，确认 project_id/任务/Agent 不变
```

验收证据必须记录实际命令、退出码、生成文件摘要和秘密扫描结果；不能以“skill 已安装”或 `tools/list` alone 代替项目本地约束已生效。

## 回滚点

- 契约阶段失败：只回滚模板/schema，不动现有 runtime。
- CLI 阶段失败：删除本次生成的带 digest 文件，保留用户原文和 `.tsunagou/local`。
- 宿主阶段失败：关闭专属入口，保留 generic `AGENTS.md`/context，标记能力 unknown。
- 文档/验收阶段失败：不把 bootstrap 标记为可交付，保存失败证据并修正对应子任务。

## 实际执行证据（2026-09-22）

- `uv run pytest -q`：全量 Python 测试通过。
- `corepack pnpm --dir packages/bridge-server run check` 与 `run build`：通过。
- `powershell -ExecutionPolicy Bypass -File tools/dev/package_smoke.ps1`：源码树外 wheel/bridge 安装烟测通过。
- `uv run python tools/dev/smoke_standalone.py`：真实 daemon、双 bridge、重启恢复和用户决定烟测通过；不把该 smoke 解读为多 project runtime 验收。
- `uv run python -m tsunagou --json project bootstrap ...`：临时 Git 项目首次生成五个入口；第二次全部 `unchanged`。
- `python tools/docs/validate_docs.py` 与 `git diff --check`：通过。

宿主 hook 的自动注入仍按能力证据单列；本任务实现并验证的是 generic 项目入口和安装/onboarding 联动，不宣称 OS 级工具门禁。
