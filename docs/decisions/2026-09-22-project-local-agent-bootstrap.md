# 项目本地 Agent 约束与快速初始化

## 背景

2026-09-22 检查 `D:\ALL.NET\SegaImageManageTool` 时发现：虽然用户已为该项目创建 Tsunagou 项目，业务项目目录中没有 `AGENTS.md`、项目 skill、hook 或其他可被宿主发现的 Tsunagou 入口。原因不是 daemon 没有管理项目，而是当前安装器只安装 Tsunagou 自身的 checkout、依赖和通用 skill；当前 `project init` 只建立 `.tsunagou` runtime，没有执行项目本地入口物化。

## 决策

1. **安装 checkout、项目共享入口、daemon runtime 分离。**
   - 安装 checkout 保存 Tsunagou 源码、规范和 bridge 构建产物。
   - 每个业务项目在协调根保存无秘密的 `.tsunagou/project-integration.json`、`.tsunagou/agent-context.md`、`.agents/skills/tsunagou-project/SKILL.md` 和 `AGENTS.md` 的受管区块。
   - 一个本机 daemon 仍可管理多个项目；每个项目的 `.tsunagou/local/`、SQLite、endpoint、token、ticket 和 bridge session 是本机私有运行数据。
2. **新增项目 bootstrap 阶段。** `project init` 保持项目事实初始化语义；当用户明确把当前业务项目作为安装目标时，installer 可在缺少 `project.json` 时先执行一次 `project init`，随后执行 `project bootstrap`，把共享约束写入该项目。bootstrap/installer 联动不启动 Agent、不任命 main、不创建/发布任务。
3. **项目入口不复制源码。** 入口写入 GitHub source URL、规范相对路径、生成器版本和可选的本机 checkout 诊断路径。source checkout 移动后可以刷新诊断信息，但不能改变 project_id、任务、Agent 或历史事实。
4. **受管内容增量更新。** 不覆盖已有 `AGENTS.md`、skill 或 `.gitignore` 用户内容；使用 `TSUNAGOU:START/END` 标记块、digest 和冲突结果。只有显式 refresh/force-managed 才能替换受管块。
5. **通用入口是首发硬要求，hook 是增强。** `AGENTS.md`、项目 skill 和 context 必须表达主/worker/user、Full Access、scope、claim/preflight/start、Git、ACK、恢复和用户重大决策边界。没有真实宿主能力证据时不生成或不宣称 hook/tool gate 已生效。
6. **本轮不扩大 daemon runtime 范围。** 本轮证明项目入口可由同一安装 checkout 为多个项目分别生成且不串读；一个 daemon 进程同时加载多个 project runtime 仍必须由原 runtime 任务的真实证据证明，不能由项目 manifest 或 bootstrap 输出推断。

## 实施任务

父任务：[项目本地 Agent 约束与快速初始化](../../.trellis/tasks/archive/2026-09/09-22-project-local-agent-bootstrap/prd.md)

- [项目本地约束包与源码引用契约](../../.trellis/tasks/archive/2026-09/09-22-project-local-contract/prd.md)
- [项目初始化与安装脚本联动](../../.trellis/tasks/archive/2026-09/09-22-project-bootstrap-command/prd.md)
- [宿主接入入口与 Agent 引导](../../.trellis/tasks/archive/2026-09/09-22-host-onboarding-materialization/prd.md)
- [独立多项目验收与使用文档](../../.trellis/tasks/archive/2026-09/09-22-project-bootstrap-acceptance/prd.md)

## 当前边界

上述任务已完成并归档。当前可确认的是：安装器支持显式指定业务项目并生成通用项目入口，CLI bootstrap 已通过源码树外临时 Git 项目验收，入口不复制源码、不写入秘密，且重复运行幂等。仍不能宣称 OS 级 hook、宿主工具门禁或 Full Access 机制已被 Tsunagou 自动接管；这些能力必须以后续宿主实测证据为准。
