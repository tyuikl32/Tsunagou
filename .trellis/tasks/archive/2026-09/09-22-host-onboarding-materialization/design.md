# 宿主接入入口与 Agent 引导设计

## 层次

1. `AGENTS.md`：宿主通常会自动读取的短强制规则。
2. `.agents/skills/tsunagou-project/SKILL.md`：项目 skill 的 discoverability wrapper。
3. `.tsunagou/agent-context.md`：完整共享上下文与规范链接。
4. `.agents/skills/tsunagou-agent-onboarding`：安装到用户/发行 checkout 的通用 onboarding skill；项目 wrapper 只引用它，不复制它。
5. hook：可选注入，只有 probe 证据支持才报告 enabled。

Codex 首发只需验证 1–3 层实际发现和手动执行；其他宿主若没有等价自动发现，生成 `manual-load.md` 或命令提示，不返回“已接入”。

## 首次对话规则

入口要求 Agent 依次：读取项目 context → 调 bridge 的 `context__project_read` →报告自己的 agent/session/role →读取增量 inbox → worker等待或 main检查任务。任何 `ticket_issued`、skill 文件存在或宿主窗口打开都不能单独成为 ready 证据。

## 不能做的事

入口不得让 worker 自任 main、用自然语言绕过 scope、直接读取私有 token、把 Full Access描述为OS沙箱、让 daemon 代替 main 写 Git，或把 hook 存在描述为 enforced tool gate。
