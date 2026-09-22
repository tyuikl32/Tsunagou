# 实施计划

1. 扩展 `tools/install/install.py` 的项目阶段参数和结果：自动检测 `project.json`，缺失时执行 `project init`，再执行 `project bootstrap`；保存命令和阶段状态，保持 dry-run 可解释。
2. 更新 `tsunagou-install` 与 onboarding skill，要求克隆前保存当前业务项目根，显式传递 `--project-root`，说明自动 init 的条件和所有不会自动执行的动作。
3. 更新用户手册、架构和消息模块文档，描述 pull-first inbox、无通用 host wake 的现状和未来 adapter 扩展点。
4. 添加安装器 dry-run/临时 Git 项目回归测试；添加消息投递不依赖在线 host、下次 pull 可见的测试或现有证据引用。
5. 运行 Python 全量测试、Ruff、bridge 类型检查/构建、文档校验、package smoke 和独立 runtime smoke；记录实际证据后归档任务。

回滚：去掉自动 `project init` 调用即可恢复旧 source/skill-only 安装路径；不回滚既有项目的用户文本或私有 runtime。

## 实际执行证据（2026-09-22）

- `tests/unit/test_install.py`、项目 bootstrap 单元/集成测试：通过。
- dry-run 对比：无 `--project-root` 不包含 init/bootstrap；显式项目根且无 manifest 时按 init -> bootstrap 排序；已有 manifest 时返回 `project_initialization=existing`。
- 源码树外临时 Git 项目真实运行 `tools/install/install.py --destination D:\Tsunagou --project-root <temp> --host codex`：实际生成 `project.json`、`project-integration.json`、`agent-context.md`、项目 skill、`AGENTS.md` 和 `.gitignore`，返回 `project_initialization=initialized`。
- `uv run pytest -q`、`uv run ruff check src/tsunagou tools/install/install.py tests`、bridge check/build、`python tools/docs/validate_docs.py`、`git diff --check`：通过。
- 消息唤醒审计：`message.send` 持久化 delivery，bridge 只有 pull inbox 工具；generic stdio bridge 没有宿主反向 wake API。文档和 F17 记录该限制，不把消息写入成功报告成 Codex 已被唤醒。
