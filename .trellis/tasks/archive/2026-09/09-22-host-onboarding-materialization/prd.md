# 宿主接入入口与 Agent 引导

## Goal

让 Codex 及其他首发宿主在新项目目录中能找到统一的 Tsunagou 接入规则，并在宿主能力不足时给出诚实的手动路径；不把 skill/hook 误报为安全边界。

## Requirements

- 验证并使用项目 `AGENTS.md`、`.agents/skills/tsunagou-project` 作为 generic baseline。
- 为 Codex 提供可发现的入口；OpenCode、DeepSeek Harness 仅在已有能力证据时生成平台文件，否则保留 generic/manual 说明。
- 入口必须指导读取 context/inbox、识别独立 conversation、等待任务、claim/preflight/start 和主/worker/user边界。
- bridge 配置仍逐会话私有生成；项目 bootstrap 不创建共享 token/session 或将临时 subagent视为成员。

## Acceptance Criteria

- [x] 新项目中的 Codex 会话能通过项目 `AGENTS.md`、skill wrapper 和 context 找到规则及 onboarding 下一步。
- [x] 不支持 hook 的宿主仍能通过 generic 文档完成接入，且未被宣称为 enforced。
- [x] 入口明确 Full Access、Git、主权限、用户决定和恢复限制；不新增未注册领域命令。
