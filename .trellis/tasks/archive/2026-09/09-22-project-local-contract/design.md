# 项目本地约束包与源码引用契约设计

## 受管文件

```text
.tsunagou/project-integration.json  # 共享 manifest
.tsunagou/agent-context.md           # 项目上下文
.agents/skills/tsunagou-project/SKILL.md
AGENTS.md                            # TSUNAGOU 标记区块
.gitignore                            # TSUNAGOU 私有标记区块
```

manifest 必须包含：`schema_version`、`project_id`、`source.repository`、`source.ref`、`source.commit`、`source.install_path_hint?`、`generator_version`、`managed_files[]`、`content_digest`、`updated_at`。禁止 `control_token`、`session_token`、`ticket`、`endpoint_url`、私信正文和本机数据库路径成为字段；`install_path_hint` 只作本机诊断。

## 入口内容

`agent-context.md` 是唯一长文真相，必须引用：

- `docs/overview/principles.md`
- `docs/overview/subagent-guide.md`
- `docs/implementation/modules/02-agents.md`
- `docs/implementation/modules/03-tasks.md`
- `docs/implementation/runtime-prompts.md`

引用优先采用 Tsunagou checkout 的相对路径；同时写入 GitHub source URL 和当前 checkout 提示。内容必须包含：先读取项目上下文/收件箱、独立 conversation 身份、主 Agent 的 Git 与任务统筹、worker 只能 claim 自己的 Attempt、Full Access 不是 Tsunagou scope、用户保留重大决定、ACK 不等于接受、任务恢复和公开队列语义。

`AGENTS.md` 只保存短版强制前置：进入项目先读 `.tsunagou/agent-context.md`；无 ready bridge 不得声称已接入；不要把 token 粘贴到对话；按主/worker/user边界行动。长文不重复维护。

`.agents/skills/tsunagou-project/SKILL.md` 只是一层 discoverability wrapper：frontmatter 名称、描述、读取顺序、source/reference 提示和 onboarding 下一步。它不能定义新的权限或命令。

## 更新冲突

- 受管区块使用 `<!-- TSUNAGOU:START <schema> <digest> -->` / `<!-- TSUNAGOU:END -->`。
- 标记内 digest 与内容不匹配：返回 `managed_content_conflict`；只有显式刷新才替换。
- 无标记的同名已有文件：返回 `managed_file_conflict`，不备份覆盖。
- manifest 的 `project_id` 变化：拒绝更新，要求用户确认项目根是否正确。
