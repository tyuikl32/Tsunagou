<!-- TRELLIS:START -->
# Trellis Instructions

These instructions are for AI assistants working in this project.

This project is managed by Trellis. The working knowledge you need lives under `.trellis/`:

- `.trellis/workflow.md` — development phases, when to create tasks, skill routing
- `.trellis/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.trellis/workspace/` — per-developer journals and session traces
- `.trellis/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Trellis command is available on your platform (e.g. `/trellis:finish-work`, `/trellis:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Trellis skills
- `.codex/agents/` — optional custom subagents

Managed by Trellis. Edits outside this block are preserved; edits inside may be overwritten by a future `trellis update`.

<!-- TRELLIS:END -->

## Tsunagou 项目约定

- 当前仓库先完成设计与任务初始化，产品代码尚未实现。入口是 [实施基线](docs/implementation/README.md) 与 [用户说明](docs/overview/product.md)。
- 规范优先级和历史追溯见 [文档目录](docs/README.md)。`docs/history/2026-09-18-source/` 是原始记录，不修改；新实现以当前 implementation、已确认 decisions 为准。
- 开发前读相应 `.trellis/spec`、当前任务 PRD/design/implement 与上下文。任务依赖以 [task-plan.json](docs/implementation/task-plan.json) 和 `meta.depends_on` 为准；Trellis 父子关系不是依赖调度器。
- 已确认的问题不要重新逐项询问用户。普通实现选择自行完成并留档；用户目标、重大设计和固定用户权限边界的实质变化才升级。
- 系统代码维护身份、范围、版本、状态等机械不变量；业务语义交给运行时主 Agent。八模块以公开端口协作，workflows/blackboard 不新增领域真相。
- 四宿主都需正式共同基线真机证据；不得把未知能力写成 supported，模拟器通过不代表真实宿主通过。
- 项目说明中的运行命令是待实现规范，不能据此报告已运行成功。每项验收以实际测试/版本/证据为准。
- 文档校验：`python tools/docs/validate_docs.py`。修改公共语义时同步 Schema、命令目录、fixtures、任务和用户文档。
- 实施步骤和文件位置见 [搭建指南](docs/implementation/build-guide.md)、[预期目录](docs/implementation/directory-layout.md)；用户子Agent接入与CLI/HTTP示例分别见 [接入指南](docs/overview/subagent-guide.md)、[操作手册](docs/overview/cli-http-manual.md)。示例不能创造未注册的U权限或把宿主临时subagent视为已认证项目成员。
- 当前开发者 `tyuikl32`，开发平台 Codex。会话/任务自动 Git commit 已关闭；提交和发布按当前用户授权执行。
